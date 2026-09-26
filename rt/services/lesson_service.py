"""
rt.services.lesson_service
Lettura delle lezioni per API e interfacce: indice (DB), riepilogo, stato delle fasi con i
report di validazione, documento Markdown con timecode strutturati, audio, costi. Tutto si
calcola dai file della lezione (fonte di verità per artefatti e freschezza delle fasi); il
DB dà l'id stabile della lezione (Lesson.id) e l'elenco delle cartelle note.
"""
import os
import re
from typing import Any, Dict, List, Optional

from rt.core.lesson_paths import lesson_path
from rt.storage import fs

PHASES = ("prepare", "outline", "rewrite", "review", "build")
AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".mp4", ".webm", ".aiff", ".aif"}


class LessonNotFound(LookupError):
    """Nessuna lezione con quell'id, oppure la sua cartella non esiste più."""


# ---------------------------------------------------------------- indice

def lessons_root() -> Optional[str]:
    from rt.core.config import load_config
    root = load_config().telegram.lessons_root
    return os.path.abspath(os.path.expanduser(root)) if root else None


def _require_db():
    from rt.db.engine import get_database
    db = get_database()
    if db is None:
        raise RuntimeError("Database non disponibile.")
    return db


def ensure_indexed(lesson_dirs: List[str]) -> Dict[str, int]:
    """Porta nel DB le cartelle non ancora note e restituisce percorso reale -> Lesson.id."""
    from rt.db.repositories import LessonRepository, normalize_lesson_path
    from rt.db.session import session_scope
    from rt.db.sync import sync_lesson
    db = _require_db()
    ids: Dict[str, int] = {}
    with session_scope(db) as session:
        repo = LessonRepository(session)
        for lesson_dir in lesson_dirs:
            path = normalize_lesson_path(lesson_dir)
            lesson = repo.get_by_path(path) or sync_lesson(session, path)
            if lesson is not None:
                ids[path] = lesson.id
    return ids


def lesson_id_for_dir(lesson_dir: str) -> Optional[int]:
    return ensure_indexed([lesson_dir]).get(os.path.realpath(os.path.abspath(lesson_dir)))


def known_lesson_dirs() -> List[str]:
    """Cartelle lezione di lessons_root più quelle già nel DB che esistono ancora."""
    from rt.core.lesson_index import scan_lessons
    from rt.db.repositories import LessonRepository, normalize_lesson_path
    from rt.db.session import session_scope
    dirs = [normalize_lesson_path(e.lesson_dir) for e in scan_lessons(lessons_root() or "")]
    with session_scope(_require_db()) as session:
        for lesson in LessonRepository(session).list_all():
            if lesson.path not in dirs and fs.isfile(lesson_path(lesson.path, "info.yaml")):
                dirs.append(lesson.path)
    return dirs


def resolve_lesson_dir(lesson_id: int) -> str:
    from rt.db.models import Lesson
    from rt.db.session import session_scope
    with session_scope(_require_db()) as session:
        lesson = session.get(Lesson, lesson_id)
        path = lesson.path if lesson is not None else None
    if not path or not fs.isdir(path):
        raise LessonNotFound(f"Lezione {lesson_id} non trovata.")
    return path


# ---------------------------------------------------------------- riepilogo e dettaglio

def _pending_count(lesson_dir: str) -> int:
    from rt.pipeline.ledger import load_ledger
    from rt.pipeline.review import load_science_issues
    decided = {d.issue_id for d in load_ledger(lesson_dir).decisions}
    return sum(1 for i in load_science_issues(lesson_dir) if i.id not in decided)


def lesson_summary(lesson_id: int, lesson_dir: str) -> Dict[str, Any]:
    """Stessi dati della dashboard (rt/tui/data.py) in forma JSON."""
    with fs.read_snapshot():
        return _lesson_summary(lesson_id, lesson_dir)


def _lesson_summary(lesson_id: int, lesson_dir: str) -> Dict[str, Any]:
    from rt.core.idempotency import check_phase_status
    from rt.core.state import compute_effective_workflow_state, read_info_yaml
    from rt.pipeline.cost import compute_lesson_cost
    out: Dict[str, Any] = {
        "id": lesson_id, "folder_name": os.path.basename(lesson_dir), "path": lesson_dir,
        "data": "", "materia": "", "titolo": "", "argomenti": "", "state": None,
        "phases": {ph: "MISSING" for ph in PHASES}, "pending_issues": 0, "cost_usd": None, "error": None,
    }
    try:
        info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
        state = compute_effective_workflow_state(lesson_dir)
        out.update({
            "data": str(info.get("data") or ""),
            "materia": str(info.get("materia") or "").strip().upper(),
            "titolo": str(info.get("titolo") or ""),
            "argomenti": str(info.get("argomenti") or ""),
            "state": state.value if state else info.get("fase_corrente"),
            "phases": {ph: check_phase_status(lesson_dir, ph)[0].value for ph in PHASES},
            "pending_issues": _pending_count(lesson_dir),
            "cost_usd": (compute_lesson_cost(lesson_dir) or {}).get("total_estimated_cost_usd"),
        })
    except Exception as exc:  # una lezione illeggibile non blocca l'elenco
        out["error"] = str(exc)
    return out


def list_lessons(materia: Optional[str] = None, state: Optional[str] = None,
                 text: Optional[str] = None) -> List[Dict[str, Any]]:
    with fs.read_snapshot():  # centinaia di letture per lezione, una query ciascuna senza
        ids = ensure_indexed(known_lesson_dirs())
        items = [lesson_summary(lesson_id, path) for path, lesson_id in ids.items()]
    if materia:
        items = [i for i in items if i["materia"] == materia.strip().upper()]
    if state:
        items = [i for i in items if i["state"] == state]
    if text:
        needle = text.casefold()
        items = [i for i in items if any(needle in str(i[k]).casefold()
                                         for k in ("folder_name", "titolo", "argomenti", "materia"))]
    items.sort(key=lambda i: (i["data"], i["folder_name"]), reverse=True)
    return items


def phase_report(lesson_dir: str) -> Dict[str, Any]:
    """Freschezza di ogni fase (come 'rt status') e report di validazione di outline e draft
    (come 'rt validate-outline' e 'rt validate-draft')."""
    from rt.core.idempotency import check_phase_status
    from rt.core.segments import load_segments_json
    from rt.pipeline.outline import get_outline_path, load_outline
    from rt.pipeline.rewrite import get_draft_path, load_draft
    from rt.pipeline.validator import validate_draft, validate_outline

    from rt.services.review_service import build_warnings

    phases = []
    for ph in PHASES:
        status, reason = check_phase_status(lesson_dir, ph)
        item = {"phase": ph, "status": status.value, "reason": reason, "warnings": []}
        if ph == "build":
            try:
                item["warnings"] = build_warnings(lesson_dir)
            except Exception as exc:
                item["warnings"] = [{"code": "check_failed", "count": None,
                                     "message": f"Controlli della revisione non riusciti: {exc}."}]
        phases.append(item)
    report: Dict[str, Any] = {"phases": phases, "outline_validation": None, "draft_validation": None}
    seg_path = lesson_path(lesson_dir, "segments.json")
    try:
        if fs.isfile(get_outline_path(lesson_dir)) and fs.isfile(seg_path):
            outline, segments = load_outline(lesson_dir), load_segments_json(seg_path)
            report["outline_validation"] = validate_outline(outline, segments)
            if fs.isfile(get_draft_path(lesson_dir)):
                report["draft_validation"] = validate_draft(load_draft(lesson_dir), outline, segments)
    except Exception as exc:
        report["validation_error"] = str(exc)
    return report


def lesson_detail(lesson_id: int, lesson_dir: str) -> Dict[str, Any]:
    from rt.core.manifest import load_manifest
    from rt.pipeline.cost import compute_lesson_cost
    from rt.services.outline_service import is_outline_approved
    out = lesson_summary(lesson_id, lesson_dir)
    manifest = load_manifest(lesson_dir)
    out["phase_report"] = phase_report(lesson_dir)["phases"]
    out["segment_count"] = manifest.segment_count if manifest else 0
    out["outline_approved"] = is_outline_approved(lesson_dir)
    out["has_audio"] = lesson_audio_file(lesson_dir) is not None
    out["cost"] = compute_lesson_cost(lesson_dir)
    out["actions"] = lesson_actions(lesson_dir)
    return out


def lesson_actions(lesson_dir: str) -> Dict[str, Dict[str, Any]]:
    """Azioni di studio e download della vista lezione: se sono disponibili e, se no, cosa
    manca. Recall, immagini e download richiedono solo la bozza pronta (prepare, outline e
    rewrite VALID), non il documento finale; il download usa il documento finale se è
    aggiornato, altrimenti l'anteprima."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.storage.export import ExportError, export_mode
    status, _reason = check_phase_status(lesson_dir, "rewrite")
    ready = status == PhaseStatus.VALID
    if ready:
        missing = None
    elif status == PhaseStatus.PARTIAL:
        missing = "La rielaborazione non è completa: servono tutte le unità della bozza."
    elif status == PhaseStatus.MISSING:
        missing = "Serve prima la rielaborazione della lezione (fase Rielaborazione)."
    else:
        missing = "La bozza non è aggiornata: rifai la rielaborazione."
    try:
        mode = export_mode(lesson_dir)
    except ExportError:
        mode = "none"
    download = {
        "available": mode != "none",
        "reason": None if mode != "none" else missing,
        "preview": mode == "preview",
    }
    return {
        "recall": {"available": ready, "reason": missing, "preview": False},
        "images": {"available": ready, "reason": missing, "preview": False},
        "export_markdown": dict(download),
        "export_zip": dict(download),
    }


# ---------------------------------------------------------------- documento

def strip_yaml_frontmatter(content: str) -> str:
    """Rimuove un eventuale blocco di frontmatter YAML in testa alla stringa
    (es. '---\n...\n---\n') per evitare che appaia come testo corrotto nel widget
    MarkdownViewer, preservando intatto il resto del Markdown."""
    if not content or not content.startswith("---"):
        return content
    pattern = r"^---\r?\n.*?\r?\n---\r?\n?"
    return re.sub(pattern, "", content, count=1, flags=re.DOTALL).lstrip("\r\n")


def _document_is_final(lesson_dir: str) -> bool:
    """True se il documento finale esiste ed è aggiornato (build VALID)."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    return (fs.isfile(lesson_path(lesson_dir, "rielaborato.md"))
            and check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID)


def _read_rielaborato(lesson_dir: str) -> Optional[str]:
    try:
        with fs.open(lesson_path(lesson_dir, "rielaborato.md"), "r", encoding="utf-8") as f:
            return strip_yaml_frontmatter(f.read())
    except OSError:
        return None


def load_markdown_preview(lesson_dir: str) -> str:
    """Il documento da mostrare, senza frontmatter YAML:
    1. il documento finale, se esiste ed è aggiornato (build VALID);
    2. altrimenti, con la bozza pronta (rewrite VALID), l'anteprima: lo stesso Markdown che
       il build scriverebbe ora (bozza, decisioni della revisione, immagini posizionate);
    3. altrimenti il documento finale superato, se c'è, o un placeholder onesto."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    if _document_is_final(lesson_dir):
        final = _read_rielaborato(lesson_dir)
        if final is not None:
            return final
    if check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.VALID:
        try:
            from rt.pipeline.build import render_lesson_documents
            return strip_yaml_frontmatter(render_lesson_documents(lesson_dir)["rielaborato"])
        except Exception:
            pass
    if fs.isfile(lesson_path(lesson_dir, "rielaborato.md")):
        final = _read_rielaborato(lesson_dir)
        if final is not None:
            return final
    try:
        # bozza non ancora valida (es. rewrite parziale): anteprima di quello che c'è
        from rt.pipeline.build import render_lesson_documents
        return strip_yaml_frontmatter(render_lesson_documents(lesson_dir)["rielaborato"])
    except Exception:
        return (
            "# Nessuna anteprima disponibile\n\n"
            "Il documento Markdown di questa lezione non è ancora stato generato.\n\n"
            "Serve almeno la fase di *rewrite* completata per un'anteprima live, "
            "oppure la fase di *build* per il documento finale."
        )


def document_sections(lesson_dir: str) -> List[Dict[str, Any]]:
    """Timecode strutturati: per ogni unità del draft (un blocco del documento) i secondi di
    inizio e fine presi da segments.json, non ricavati dal testo."""
    from rt.core.segments import load_segments_json
    from rt.pipeline.ledger import load_resolved_draft
    try:
        draft = load_resolved_draft(lesson_dir)
        segments = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    except Exception:
        return []
    by_id = {s.id: s for s in (segments.segments if segments else [])}
    out = []
    for unit in draft.units:
        start, end = by_id.get(unit.start_segment_id), by_id.get(unit.end_segment_id)
        out.append({
            "unit_id": unit.unit_id,
            "title": unit.title,
            "start_segment_id": unit.start_segment_id,
            "end_segment_id": unit.end_segment_id,
            "start_seconds": start.start_seconds if start else None,
            "end_seconds": end.end_seconds if end else None,
            "start_formatted": start.start_formatted if start else None,
        })
    return out


def lesson_document(lesson_dir: str) -> Dict[str, Any]:
    from markdown_it import MarkdownIt
    markdown = load_markdown_preview(lesson_dir)
    final = _document_is_final(lesson_dir)
    sections = document_sections(lesson_dir)
    # html=False: l'HTML grezzo del Markdown viene escapato, quindi l'output è sicuro.
    md = MarkdownIt("commonmark", {"html": False})
    tokens = md.parse(markdown)
    _mark_unit_blocks(tokens, sections)
    html = md.renderer.render(tokens, md.options, {})
    return {"final": final, "markdown": markdown, "html": html, "sections": sections}


def _mark_unit_blocks(tokens: list, sections: List[Dict[str, Any]]) -> None:
    """Marca nell'HTML l'intestazione di ogni unità ('### <id> <titolo>', come la scrive
    build) con data-unit-id, e la riga del timecode che la segue con data-unit-timecode:
    la SPA ci aggancia i timecode strutturati di 'sections' senza cercarli nel testo."""
    by_id = {s["unit_id"]: s for s in sections}
    for i, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag not in ("h2", "h3") or i + 1 >= len(tokens):
            continue
        unit_id = tokens[i + 1].content.split(" ", 1)[0].rstrip(".")
        section = by_id.get(unit_id)
        if section is None:
            continue
        token.attrSet("data-unit-id", unit_id)
        token.attrSet("id", f"unit-{unit_id}")
        nxt = i + 3
        if (nxt + 1 < len(tokens) and tokens[nxt].type == "paragraph_open"
                and section.get("start_formatted")
                and tokens[nxt + 1].content.strip() == section["start_formatted"]):
            tokens[nxt].attrSet("data-unit-timecode", unit_id)


# ---------------------------------------------------------------- audio

def lesson_audio_file(lesson_dir: str) -> Optional[str]:
    """Audio della lezione, solo se è un file audio dentro la cartella della lezione."""
    from rt.core.audio_clip import resolve_audio_path
    from rt.core.state import read_info_yaml
    root = os.path.realpath(lesson_dir)
    candidates = []
    try:
        candidates.append(resolve_audio_path(lesson_dir))
    except Exception:
        pass
    try:
        raw = read_info_yaml(lesson_path(lesson_dir, "info.yaml")).get("file_audio")
        if raw:
            candidates.append(os.path.join(lesson_dir, os.path.basename(str(raw))))
    except Exception:
        pass
    if fs.is_db_lesson(lesson_dir):
        # lezione nel database: l'audio è un media registrato della lezione
        for cand in candidates:
            if cand and os.path.splitext(cand)[1].lower() in AUDIO_SUFFIXES:
                if os.path.dirname(cand) == fs.media_dir() and os.path.isfile(cand):
                    return cand
                real = fs.real_path(os.path.join(lesson_dir, os.path.basename(cand)))
                if real:
                    return real
        return None
    for cand in candidates:
        if not cand:
            continue
        real = os.path.realpath(cand)
        if (fs.isfile(real) and os.path.commonpath([root, real]) == root
                and os.path.splitext(real)[1].lower() in AUDIO_SUFFIXES):
            return real
    return None


# ---------------------------------------------------------------- costi

def costs_summary() -> Dict[str, Any]:
    """Riepilogo dei costi di tutte le lezioni note (stessi numeri di 'rt cost')."""
    from rt.pipeline.cost import compute_lesson_cost
    ids = ensure_indexed(known_lesson_dirs())
    lessons, by_job, total, requests = [], {}, 0.0, 0
    for path, lesson_id in ids.items():
        data = compute_lesson_cost(path)
        if not data:
            continue
        cost = float(data.get("total_estimated_cost_usd") or 0.0)
        total += cost
        calls = int(data.get("total_calls") or 0)
        requests += calls
        lessons.append({"id": lesson_id, "folder_name": os.path.basename(path), "cost_usd": cost,
                        "calls": calls, "has_unknown_cost": bool(data.get("has_unknown_cost"))})
        for job, info in (data.get("by_job") or {}).items():
            agg = by_job.setdefault(job, {"cost_usd": 0.0, "calls": 0})
            agg["cost_usd"] += float(info.get("total_cost") or 0.0)
            agg["calls"] += int(info.get("total_calls") or 0)
    lessons.sort(key=lambda x: x["cost_usd"], reverse=True)
    return {"total_cost_usd": round(total, 6), "total_calls": requests, "by_job": by_job, "lessons": lessons}
