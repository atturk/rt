"""
rt.services.document_edit_service
Modifica a mano dell'anteprima del documento (RT4-FA3, funzione beta).

L'utente modifica il Markdown dell'anteprima, lo stesso che il build scriverebbe ora:

    # [data] MATERIA - Titolo della lezione        (non si modifica)
    ## 1. Titolo della sezione                     (titolo modificabile)
    ![descrizione](assets/images/abcd1234.png)     (solo immagini sotto il titolo di sezione)
    ### 1.1 Titolo dell'unità                      (titolo modificabile)
    12:34                                          (timecode: MM:SS o H:MM:SS, riga subito sotto)

    Testo dell'unità, con link e immagini.

Sezioni e unità restano quelle della scaletta, nello stesso ordine. Il salvataggio:
- il testo di un'unità cambiata va nella bozza (draft.json), con le decisioni della revisione
  già dentro (l'unità è segnata 'edited' e le decisioni non si riapplicano);
- titoli e timecode vanno in document_edits.json; un timecode si aggancia all'inizio del
  segmento audio in cui cade, deve stare nella durata dell'audio e venire dopo quello
  dell'unità precedente;
- le immagini sotto i titoli di sezione aggiornano il posizionamento;
- il documento finale diventa da ricreare (le impronte del build cambiano) e le issue il cui
  testo non c'è più risultano orfane (rt.services.review_service.orphan_issue_ids).
Gli errori tornano con la riga e il motivo; con un errore non si salva nulla.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rt.core.lesson_paths import lesson_path

TIMECODE_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")
MACRO_RE = re.compile(r"^##\s+(\S+?)\.\s+(.+?)\s*$")
UNIT_RE = re.compile(r"^###\s+(\S+)\s+(.+?)\s*$")
IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
LOCAL_IMAGE_PREFIX = "assets/images/"


class DocumentEditError(ValueError):
    """Markdown non riconvertibile nella bozza: errors = [{"line": n, "message": ...}]."""

    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        super().__init__("; ".join(f"riga {e['line']}: {e['message']}" if e.get("line") else e["message"]
                                   for e in errors))


def parse_timecode(text: str) -> Optional[int]:
    m = TIMECODE_RE.match(text.strip())
    if not m:
        return None
    hours, minutes, seconds = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    if seconds >= 60 or (m.group(1) is not None and minutes >= 60):
        return None
    return hours * 3600 + minutes * 60 + seconds


@dataclass
class _Unit:
    unit_id: str
    title: str
    title_line: int
    timecode: Optional[str] = None
    timecode_line: Optional[int] = None
    content_lines: List[Tuple[int, str]] = field(default_factory=list)


@dataclass
class _Macro:
    macro_id: str
    title: str
    line: int
    images: List[Tuple[int, str]] = field(default_factory=list)
    units: List[_Unit] = field(default_factory=list)


def _parse_structure(markdown: str) -> Tuple[Optional[Tuple[int, str]], List[_Macro], List[Dict[str, Any]]]:
    """Titolo H1, sezioni con immagini e unità, errori di forma."""
    errors: List[Dict[str, Any]] = []
    title: Optional[Tuple[int, str]] = None
    macros: List[_Macro] = []
    unit: Optional[_Unit] = None
    for n, raw in enumerate(markdown.replace("\r\n", "\n").split("\n"), start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if line.startswith("# "):
            if title is None and not macros:
                title = (n, line)
            else:
                errors.append({"line": n, "message": "Un solo titolo di primo livello (#), in cima al documento."})
            continue
        if line.startswith("## "):
            m = MACRO_RE.match(line)
            if not m:
                errors.append({"line": n, "message": "Titolo di sezione non riconosciuto: scrivi '## <numero>. <titolo>'."})
                continue
            macros.append(_Macro(m.group(1), m.group(2), n))
            unit = None
            continue
        if line.startswith("### "):
            m = UNIT_RE.match(line)
            if not m or not macros:
                errors.append({"line": n, "message": "Titolo di unità non riconosciuto: scrivi '### <numero> <titolo>' dentro una sezione."})
                continue
            unit = _Unit(m.group(1), m.group(2), n)
            macros[-1].units.append(unit)
            continue
        if unit is not None:
            if unit.timecode is None and not unit.content_lines:
                if not stripped:
                    continue
                unit.timecode, unit.timecode_line = stripped, n
                continue
            unit.content_lines.append((n, line))
            continue
        if not stripped:
            continue
        if macros and IMAGE_LINE_RE.match(stripped):
            macros[-1].images.append((n, stripped))
            continue
        where = "sotto il titolo di una sezione vanno solo immagini" if macros else "prima della prima sezione non va testo"
        errors.append({"line": n, "message": f"Testo fuori da un'unità: {where}. Spostalo dentro un'unità."})
    return title, macros, errors


def _content(unit: _Unit) -> str:
    lines = [text for _n, text in unit.content_lines]
    return "\n".join(lines).strip()


def _image_ref_errors(lesson_dir: str, text: str, first_line: int, known: set) -> List[Dict[str, Any]]:
    errors = []
    for offset, line in enumerate(text.split("\n")):
        for target in IMAGE_REF_RE.findall(line):
            if target.startswith(LOCAL_IMAGE_PREFIX) and target not in known:
                errors.append({"line": first_line + offset,
                               "message": f"Immagine non trovata nella lezione: {target}."})
    return errors


def plan_document_edit(lesson_dir: str, markdown: str) -> Dict[str, Any]:
    """Confronta il Markdown con l'anteprima attuale e prepara le modifiche, senza scrivere.
    Solleva DocumentEditError con tutti gli errori trovati."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.core.segments import load_segments_json
    from rt.core.timestamp import format_timestamp
    from rt.pipeline.add_images import load_image_descriptions
    from rt.pipeline.build import clean_unit_content, render_lesson_documents
    from rt.pipeline.document_edits import load_document_edits, unit_start_segment
    from rt.pipeline.image_placement import load_image_placement
    from rt.pipeline.ledger import load_resolved_draft
    from rt.pipeline.outline import load_outline
    from rt.services.lesson_service import strip_yaml_frontmatter

    status, reason = check_phase_status(lesson_dir, "rewrite")
    if status != PhaseStatus.VALID:
        raise DocumentEditError([{"line": None, "message": f"La bozza non è pronta ({reason}): l'anteprima non si modifica."}])

    outline = load_outline(lesson_dir)
    segments = load_segments_json(lesson_path(lesson_dir, "segments.json")).segments
    seg_by_id = {s.id: s for s in segments}
    duration = max((s.end_seconds for s in segments), default=0.0)
    edits = load_document_edits(lesson_dir)
    resolved = {u.unit_id: u for u in load_resolved_draft(lesson_dir).units}
    descriptions = load_image_descriptions(lesson_dir)
    hash_by_file = {d.get("filename"): h for h, d in descriptions.items() if d.get("filename")}
    current = strip_yaml_frontmatter(render_lesson_documents(lesson_dir)["rielaborato"])
    current_title = next((line.rstrip() for line in current.split("\n") if line.startswith("# ")), "")

    title, macros, errors = _parse_structure(markdown)
    if title is None:
        errors.append({"line": 1, "message": "Manca il titolo della lezione (# ...) in cima."})
    elif title[1] != current_title:
        errors.append({"line": title[0], "message": "Il titolo della lezione non si modifica dall'anteprima: rimetti "
                                                    f"«{current_title[2:]}»."})

    expected_macros = [(str(m.id), m) for m in outline.macro_sections]
    new_edits: Dict[str, Any] = {"macros": {}, "units": {}}
    content_changes: Dict[str, str] = {}
    placement: Dict[str, List[str]] = {}
    previous_start: Optional[float] = None
    previous_label = ""
    structure_ok = True

    for idx, (macro_id, macro) in enumerate(expected_macros):
        if idx >= len(macros):
            errors.append({"line": None, "message": f"Manca la sezione {macro_id}. {macro.title}: le sezioni non si tolgono."})
            structure_ok = False
            break
        got = macros[idx]
        if got.macro_id != macro_id:
            errors.append({"line": got.line, "message": f"Qui va la sezione {macro_id}: sezioni e unità restano quelle "
                                                        "della scaletta, nello stesso ordine."})
            structure_ok = False
            break
        if got.title != macro.title:
            new_edits["macros"][macro_id] = {"title": got.title}
        for n, image_line in got.images:
            target = IMAGE_LINE_RE.match(image_line).group(2)
            h = hash_by_file.get(target)
            if h is None:
                errors.append({"line": n, "message": f"Immagine non trovata nella lezione: {target}."})
            else:
                placement.setdefault(macro_id, []).append(h)

        expected_units = list(macro.units)
        for u_idx, out_unit in enumerate(expected_units):
            if u_idx >= len(got.units):
                errors.append({"line": got.line, "message": f"Manca l'unità {out_unit.id} nella sezione {macro_id}: "
                                                            "le unità non si tolgono."})
                structure_ok = False
                break
            unit = got.units[u_idx]
            if unit.unit_id != str(out_unit.id):
                errors.append({"line": unit.title_line, "message": f"Qui va l'unità {out_unit.id}: sezioni e unità restano "
                                                                   "quelle della scaletta, nello stesso ordine."})
                structure_ok = False
                break
            uid = str(out_unit.id)
            unit_edit: Dict[str, Any] = {}
            if unit.title != out_unit.title:
                unit_edit["title"] = unit.title

            # timecode
            start_id = unit_start_segment(edits, uid, out_unit.start_segment_id)
            start_seg = seg_by_id.get(start_id) or seg_by_id.get(out_unit.start_segment_id)
            current_tc = format_timestamp(start_seg.start_seconds) if start_seg else None
            seconds = parse_timecode(unit.timecode or "")
            if unit.timecode is None or seconds is None:
                errors.append({"line": unit.timecode_line or unit.title_line,
                               "message": f"Sotto il titolo dell'unità {uid} va il timecode, per esempio 12:34 o 1:02:03."})
                continue
            if unit.timecode == current_tc and start_seg is not None:
                chosen = start_seg
            elif seconds > duration:
                errors.append({"line": unit.timecode_line,
                               "message": f"Il timecode {unit.timecode} è oltre la fine dell'audio ({format_timestamp(duration)})."})
                continue
            else:
                # l'inizio del segmento in cui cade il tempo scritto
                chosen = segments[0]
                for s in segments:
                    if s.start_seconds <= seconds:
                        chosen = s
                    else:
                        break
            if previous_start is not None and chosen.start_seconds <= previous_start:
                errors.append({"line": unit.timecode_line,
                               "message": f"Il timecode dell'unità {uid} ({format_timestamp(chosen.start_seconds)}) deve "
                                          f"venire dopo quello dell'unità {previous_label}."})
            previous_start, previous_label = chosen.start_seconds, uid
            if chosen.id != out_unit.start_segment_id:
                unit_edit["start_segment_id"] = chosen.id

            # testo
            text = _content(unit)
            first_content_line = unit.content_lines[0][0] if unit.content_lines else (unit.timecode_line or unit.title_line)
            if not text:
                errors.append({"line": first_content_line, "message": f"L'unità {uid} è vuota: scrivi il suo testo."})
                continue
            errors.extend(_image_ref_errors(lesson_dir, "\n".join(t for _n, t in unit.content_lines),
                                            unit.content_lines[0][0], set(hash_by_file)))
            draft_unit = resolved.get(uid)
            shown = clean_unit_content(draft_unit.content.strip()) if draft_unit else ""
            was_edited = bool((edits["units"].get(uid) or {}).get("edited"))
            if text != shown:
                content_changes[uid] = text
                unit_edit["edited"] = True
            elif was_edited:
                unit_edit["edited"] = True
            if unit_edit:
                new_edits["units"][uid] = unit_edit
        else:
            extra = got.units[len(expected_units):]
            if extra:
                errors.append({"line": extra[0].title_line, "message": f"L'unità {extra[0].unit_id} non è nella scaletta: "
                                                                       "le unità non si aggiungono."})
                structure_ok = False
        if not structure_ok:
            break
    if structure_ok and len(macros) > len(expected_macros):
        extra = macros[len(expected_macros)]
        errors.append({"line": extra.line, "message": f"La sezione {extra.macro_id} non è nella scaletta: le sezioni "
                                                      "non si aggiungono."})

    if errors:
        errors.sort(key=lambda e: (e.get("line") is None, e.get("line") or 0))
        raise DocumentEditError(errors)

    old_placement = load_image_placement(lesson_dir)
    placement_changed = (old_placement or {"macros": {}}).get("macros", {}) != placement
    if old_placement is None and not placement:
        placement_changed = False
    return {
        "content_changes": content_changes,
        "edits": new_edits,
        "edits_changed": new_edits != {"macros": {k: v for k, v in edits["macros"].items() if v},
                                       "units": {k: v for k, v in edits["units"].items() if v}},
        "placement": placement,
        "placement_changed": placement_changed,
        "carousel": bool((old_placement or {}).get("carousel")),
    }


def save_document_edit(lesson_dir: str, markdown: str) -> Dict[str, Any]:
    """Salva il Markdown modificato (vedi il docstring del modulo). Restituisce cosa è cambiato,
    lo stato del documento finale e le issue orfane."""
    from rt.core.idempotency import check_phase_status
    from rt.pipeline.document_edits import save_document_edits
    from rt.pipeline.image_placement import save_image_placement
    from rt.pipeline.rewrite import load_draft, save_draft
    from rt.services.review_service import orphan_issue_ids

    plan = plan_document_edit(lesson_dir, markdown)
    changed_units = sorted(plan["content_changes"])
    if plan["content_changes"]:
        draft = load_draft(lesson_dir)
        draft.units = [u.model_copy(update={"content": plan["content_changes"][u.unit_id]})
                       if u.unit_id in plan["content_changes"] else u for u in draft.units]
        save_draft(draft, lesson_dir)
    edits_changed = save_document_edits(lesson_dir, plan["edits"]) if plan["edits_changed"] else False
    if plan["placement_changed"]:
        save_image_placement(lesson_dir, plan["placement"], plan["carousel"])
    changed = bool(changed_units or edits_changed or plan["placement_changed"])
    build_status, build_reason = check_phase_status(lesson_dir, "build")
    return {
        "changed": changed,
        "units_changed": changed_units,
        "build_status": build_status.value,
        "build_reason": build_reason,
        "orphan_issues": orphan_issue_ids(lesson_dir),
    }


def check_document_edit(lesson_dir: str, markdown: str) -> Dict[str, Any]:
    """Anteprima renderizzata del Markdown in modifica e gli eventuali errori, senza salvare."""
    from rt.core.markdown_render import render_markdown
    try:
        plan_document_edit(lesson_dir, markdown)
        errors: List[Dict[str, Any]] = []
    except DocumentEditError as exc:
        errors = exc.errors
    html = render_markdown(markdown)
    return {"html": html, "errors": errors}
