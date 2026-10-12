"""Fotografie reversibili e ultime versioni della lezione, anche su storage DB."""
import json
import os
from contextlib import nullcontext
from datetime import datetime, timezone

from rt.core.lesson_paths import lesson_path
from rt.storage import fs

FILES = ("sources.json", "segments.json", "outline.json", "draft.json", "review_decisions.json",
         "info.yaml", "manifest.json", "source_update.json", "transcript_normalized.md",
         "pipeline_version.json", "science_issues.json", "review_units.json", "review_sequence.json",
         "enrichment.json", "unit_relevance.json", "unit_question_types.json", "unit_prefilter.json",
         "unit_relevance_resolved.json", "section_labels.json", "documents.json",
         "rielaborato.md", "pre-elaborato.md", "Errori concettuali.md")
POINTER = "update_snapshot.json"


def _read_pointer(lesson_dir):
    pointer = lesson_path(lesson_dir, POINTER)
    if not fs.isfile(pointer):
        return None
    with fs.open(pointer, encoding="utf-8") as stream:
        return json.load(stream)


def _write_pointer(lesson_dir, data):
    pointer = lesson_path(lesson_dir, POINTER)
    with fs.open(pointer + ".tmp", "w", encoding="utf-8") as stream:
        json.dump(data, stream)
    fs.replace(pointer + ".tmp", pointer)


def _capture(lesson_dir):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    history = os.path.join(lesson_dir, "history", stamp)
    fs.makedirs(history, exist_ok=True)
    entries = {}
    root_markdown = [name for name in fs.listdir(lesson_dir) if name.endswith(".md")
                     and fs.isfile(os.path.join(lesson_dir, name))]
    for name in dict.fromkeys((*FILES, *root_markdown)):
        path = lesson_path(lesson_dir, name)
        entries[name] = fs.isfile(path)
        if entries[name]:
            fs.copy2(path, os.path.join(history, name))
    return {"timestamp": stamp, "files": entries, "root_markdown": root_markdown}


def snapshot_update(lesson_dir, *, keep_previous=False):
    snapshot = _capture(lesson_dir)
    old = _read_pointer(lesson_dir)
    _write_pointer(lesson_dir, snapshot)
    if old and not keep_previous:
        fs.rmtree(os.path.join(lesson_dir, "history", old["timestamp"]), ignore_errors=True)
    return snapshot["timestamp"]


def begin_update(lesson_dir):
    """Fotografia dell'aggiornamento che parte; quella precedente resta finché non riesce."""
    previous = _read_pointer(lesson_dir)
    snapshot_update(lesson_dir, keep_previous=True)
    return previous


def finish_update(lesson_dir, previous):
    """Aggiornamento riuscito: resta una sola fotografia, la sua."""
    if previous:
        fs.rmtree(os.path.join(lesson_dir, "history", previous["timestamp"]), ignore_errors=True)


def abort_update(lesson_dir, previous):
    """Aggiornamento fallito: rimette la lezione com'era e la fotografia dell'aggiornamento
    precedente, così Annulla continua ad annullare quello."""
    undo_update(lesson_dir)
    if previous:
        _write_pointer(lesson_dir, previous)


def has_update_snapshot(lesson_dir):
    return fs.isfile(lesson_path(lesson_dir, POINTER))


def _restore_snapshot(lesson_dir, snapshot):
    """Il chiamante tiene il lock della lezione; ripristino transazionale nel DB."""
    from rt.db.engine import get_database
    from rt.db.session import session_scope
    from rt.db.sync import suspend_dual_write, dual_write_lesson
    from rt.pipeline.source_update import _read_state, _write_state
    history = os.path.join(lesson_dir, "history", snapshot["timestamp"])
    # Legge e verifica l'intera fotografia prima di scrivere un solo file.
    content = {}
    for name, present in snapshot["files"].items():
        if present:
            with fs.open(os.path.join(history, name), "rb") as stream:
                content[name] = stream.read()
        else:
            content[name] = None
    for name in fs.listdir(lesson_dir):
        if name.endswith(".md") and fs.isfile(os.path.join(lesson_dir, name)) and name not in snapshot["root_markdown"]:
            content.setdefault(name, None)
    current = {}
    for name in content:
        path = lesson_path(lesson_dir, name)
        if fs.isfile(path):
            with fs.open(path, "rb") as stream:
                current[name] = stream.read()
        else:
            current[name] = None
    highwater = _read_state(lesson_dir)["next_segment"]
    def restore(values):
        for name, data in values.items():
            path = lesson_path(lesson_dir, name)
            if data is None:
                if fs.isfile(path):
                    fs.remove(path)
            else:
                with fs.open(path + ".tmp", "wb") as stream:
                    stream.write(data)
                fs.replace(path + ".tmp", path)
    db = get_database()
    try:
        with session_scope(db) if db else nullcontext(), suspend_dual_write():
            restore(content)
            # Gli ID di arrivo non vengono riutilizzati nemmeno dopo Annulla.
            state = _read_state(lesson_dir)
            state["next_segment"] = max(state["next_segment"], highwater)
            _write_state(lesson_dir, state)
    except BaseException:
        if not fs.is_db_lesson(lesson_dir):
            restore(current)
        raise
    dual_write_lesson(lesson_dir)


def undo_update(lesson_dir):
    snapshot = _read_pointer(lesson_dir)
    if snapshot is None:
        raise ValueError("Non c'è un aggiornamento da annullare")
    _restore_snapshot(lesson_dir, snapshot)
    fs.remove(lesson_path(lesson_dir, POINTER))
    fs.rmtree(os.path.join(lesson_dir, "history", snapshot["timestamp"]), ignore_errors=True)
    return {"status": "update_undone"}


VERSIONS = "version_history.json"


def _versions(lesson_dir):
    path = lesson_path(lesson_dir, VERSIONS)
    if not fs.isfile(path):
        return []
    with fs.open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _save_versions(lesson_dir, versions):
    path = lesson_path(lesson_dir, VERSIONS)
    with fs.open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump(versions, stream, ensure_ascii=False, indent=2)
    fs.replace(path + ".tmp", path)


def record_version(lesson_dir, mode, *, added=None, new=0, changed=0):
    """Ogni voce conserva lo stato DOPO l'evento; massimo cinque oltre all'attuale."""
    snapshot = _capture(lesson_dir)
    version = {"id": snapshot["timestamp"], "il": datetime.now(timezone.utc).isoformat(),
        "modo": mode, "fonti_aggiunte": added or [], "unita_nuove": new,
        "unita_cambiate": changed, "snapshot": snapshot}
    versions = [version, *_versions(lesson_dir)]
    _save_versions(lesson_dir, versions[:6])
    for old in versions[6:]:
        fs.rmtree(os.path.join(lesson_dir, "history", old["id"]), ignore_errors=True)
    return version["id"]


def list_versions(lesson_dir):
    return [{**{k: v for k, v in version.items() if k != "snapshot"}, "attuale": i == 0}
            for i, version in enumerate(_versions(lesson_dir))]


def restore_version(lesson_dir, version_id):
    """Il worker tiene il lock. Studio e domande non fanno parte delle fotografie."""
    version = next((v for v in _versions(lesson_dir) if v["id"] == version_id), None)
    if version is None:
        raise ValueError("Versione non trovata")
    previous = begin_update(lesson_dir)
    try:
        _restore_snapshot(lesson_dir, version["snapshot"])
        record_version(lesson_dir, "restore")
    except BaseException:
        abort_update(lesson_dir, previous)
        raise
    finish_update(lesson_dir, previous)
    return {"status": "version_restored", "version": version_id}
