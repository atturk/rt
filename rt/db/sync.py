"""
rt.db.sync
Import dei file della lezione nel DB (rt db sync), dual-write dopo ogni scrittura dei file
di stato e confronto DB/file (rt db check).

I file restano la fonte di verità per lezione, fasi e issue: questo modulo li legge e non li
modifica mai. Il ledger delle decisioni si importa solo se review_decisions.json è cambiato
rispetto all'ultima copia nota al DB (hash in Lesson.ledger_sha).
"""
import hashlib
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from rt.db.engine import Database, get_database
from rt.db.models import Lesson
from rt.db.repositories import (
    DECISION_FIELDS, DecisionRepository, IssueRepository, LessonRepository,
    PhaseRunRepository, normalize_lesson_path,
)
from rt.db.session import session_scope

logger = logging.getLogger(__name__)

MISSING_LEDGER_SHA = "missing"
_local = threading.local()
_warned_dual_write = False


# ---------------------------------------------------------------- lettura dei file

def ledger_file_sha(lesson_dir: str) -> str:
    from rt.pipeline.ledger import get_ledger_path
    path = get_ledger_path(lesson_dir)
    if not os.path.isfile(path):
        return MISSING_LEDGER_SHA
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def lesson_fields_from_files(lesson_dir: str) -> Optional[Dict[str, Any]]:
    """Campi di Lesson da info.yaml, oppure None se la cartella non è una lezione."""
    from rt.core.lesson_paths import lesson_path
    from rt.core.state import read_info_yaml
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    if not os.path.isfile(yaml_path):
        return None
    info = read_info_yaml(yaml_path)
    return {
        "folder_name": os.path.basename(normalize_lesson_path(lesson_dir)),
        "data": str(info.get("data", "")),
        "materia": str(info.get("materia", "")).strip().upper(),
        "titolo": str(info.get("titolo", "")),
        "argomenti": str(info.get("argomenti", "")),
        "workflow_state": str(info.get("fase_corrente", "") or info.get("stato", "")),
    }


def phase_runs_from_files(lesson_dir: str) -> Dict[str, Dict[str, Any]]:
    from rt.core.manifest import load_manifest
    manifest = load_manifest(lesson_dir)
    runs: Dict[str, Dict[str, Any]] = {}
    for phase, rec in ((manifest.phase_records if manifest else {}) or {}).items():
        if phase == "review_science" or not isinstance(rec, dict):
            continue  # alias storico di "review" (vedi load_manifest)

        def _s(key):
            value = rec.get(key)
            return None if value is None else str(value)

        runs[phase] = {
            "status": str(rec.get("status") or "UNKNOWN"),
            "source_fingerprint": _s("source_fingerprint"),
            "processor_version": _s("processor_version"),
            "stale_reason": _s("stale_reason"),
            "started_at": _s("started_at"),
            "finished_at": _s("updated_at"),
        }
    return runs


def issues_from_files(lesson_dir: str) -> Dict[str, Dict[str, Any]]:
    from rt.pipeline.review import load_science_issues
    try:
        issues = load_science_issues(lesson_dir)
    except Exception as exc:
        logger.warning("science_issues.json illeggibile in %s: %s", lesson_dir, exc)
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for iss in issues:
        type_value = getattr(iss.type, "value", str(iss.type))
        out[iss.id] = {
            "kind": "asr" if str(type_value).startswith("ERR_ASR") else "science",
            "type": type_value,
            "severity": getattr(iss.severity, "value", str(iss.severity)),
            "payload": iss.model_dump(mode="json"),
        }
    return out


def decisions_from_files(lesson_dir: str) -> List[Dict[str, Any]]:
    from rt.pipeline.ledger import load_ledger
    return [d.model_dump(mode="json") for d in load_ledger(lesson_dir, strict=True).decisions]


# ---------------------------------------------------------------- import nel DB

def import_ledger(session: Session, lesson: Lesson, lesson_dir: str, force: bool = False) -> bool:
    """Importa review_decisions.json se diverso dall'ultima copia nota. True se importato."""
    sha = ledger_file_sha(lesson_dir)
    if not force and lesson.ledger_sha == sha:
        return False
    decisions = decisions_from_files(lesson_dir) if sha != MISSING_LEDGER_SHA else []
    DecisionRepository(session).replace_active(lesson, decisions)
    lesson.ledger_sha = sha
    return True


def sync_lesson(session: Session, lesson_dir: str) -> Optional[Lesson]:
    """Porta nel DB lo stato dei file di una lezione. None se non è una lezione."""
    fields = lesson_fields_from_files(lesson_dir)
    if fields is None:
        return None
    repo = LessonRepository(session)
    lesson = repo.get_or_create(lesson_dir)
    repo.update_fields(lesson, fields)
    PhaseRunRepository(session).replace_for_lesson(lesson, phase_runs_from_files(lesson_dir))
    IssueRepository(session).replace_for_lesson(lesson, issues_from_files(lesson_dir))
    import_ledger(session, lesson, lesson_dir)
    return lesson


def lesson_dirs(lessons_root: str) -> List[str]:
    from rt.core.lesson_index import scan_lessons
    return [e.lesson_dir for e in scan_lessons(lessons_root)]


def sync_all(db: Database, lessons_root: str) -> Dict[str, Any]:
    """rt db sync: importa tutte le lezioni di lessons_root, una transazione per lezione."""
    result = {"synced": 0, "errors": []}
    for lesson_dir in lesson_dirs(lessons_root):
        try:
            with session_scope(db) as session:
                if sync_lesson(session, lesson_dir) is not None:
                    result["synced"] += 1
        except Exception as exc:
            result["errors"].append(f"{os.path.basename(lesson_dir)}: {exc}")
    return result


# ---------------------------------------------------------------- dual-write

def dual_write_lesson(lesson_dir: str) -> None:
    """Aggiorna il DB dopo una scrittura dei file di stato. Mai bloccante: senza DB non fa
    nulla, e un errore del DB diventa un avviso nei log (i file restano la verità)."""
    global _warned_dual_write
    if getattr(_local, "active", False):
        return
    db = get_database()
    if db is None:
        return
    _local.active = True
    try:
        with session_scope(db) as session:
            sync_lesson(session, lesson_dir)
    except Exception as exc:
        if not _warned_dual_write:
            _warned_dual_write = True
            logger.warning("Aggiornamento del database non riuscito (i file restano validi): %s", exc)
    finally:
        _local.active = False


def lesson_dir_of_state_file(path: str) -> str:
    """Cartella della lezione per un file di stato (radice o sottocartella _state/)."""
    from rt.core.lesson_paths import STATE_SUBDIR
    parent = os.path.dirname(os.path.abspath(path))
    return os.path.dirname(parent) if os.path.basename(parent) == STATE_SUBDIR else parent


# ---------------------------------------------------------------- confronto

def check_lesson(session: Session, lesson_dir: str) -> List[str]:
    name = os.path.basename(normalize_lesson_path(lesson_dir))
    fields = lesson_fields_from_files(lesson_dir)
    lesson = LessonRepository(session).get_by_path(lesson_dir)
    if fields is None:
        return [f"{name}: info.yaml mancante"] if lesson is not None else []
    if lesson is None:
        return [f"{name}: lezione assente dal database"]
    diffs = [f"{name}: {k} = {getattr(lesson, k)!r} nel DB, {v!r} nei file"
             for k, v in fields.items() if getattr(lesson, k) != v]
    db_runs = {p: {k: getattr(r, k) for k in ("status", "source_fingerprint")}
               for p, r in PhaseRunRepository(session).for_lesson(lesson).items()}
    file_runs = {p: {k: r[k] for k in ("status", "source_fingerprint")}
                 for p, r in phase_runs_from_files(lesson_dir).items()}
    if db_runs != file_runs:
        diffs.append(f"{name}: stato delle fasi diverso (DB {sorted(db_runs)} / file {sorted(file_runs)})")
    if set(IssueRepository(session).for_lesson(lesson)) != set(issues_from_files(lesson_dir)):
        diffs.append(f"{name}: elenco delle issue diverso")
    db_decisions = [{k: getattr(d, k) for k in DECISION_FIELDS} for d in DecisionRepository(session).active(lesson)]
    file_decisions = [{k: d.get(k) for k in DECISION_FIELDS} for d in decisions_from_files(lesson_dir)]
    if db_decisions != file_decisions:
        diffs.append(f"{name}: decisioni diverse ({len(db_decisions)} nel DB, {len(file_decisions)} in review_decisions.json)")
    return diffs


def check_all(db: Database, lessons_root: str) -> List[str]:
    """rt db check: differenze tra DB e file (lista vuota = allineati)."""
    diffs: List[str] = []
    dirs = lesson_dirs(lessons_root)
    on_disk = {normalize_lesson_path(d) for d in dirs}
    with session_scope(db) as session:
        for lesson_dir in dirs:
            try:
                diffs.extend(check_lesson(session, lesson_dir))
            except Exception as exc:
                diffs.append(f"{os.path.basename(lesson_dir)}: errore di lettura ({exc})")
        for lesson in LessonRepository(session).list_all(under_root=lessons_root):
            if lesson.path not in on_disk:
                diffs.append(f"{lesson.folder_name}: nel database ma la cartella non esiste più")
    return diffs
