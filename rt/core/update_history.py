"""Una fotografia completa dell'ultimo aggiornamento, anche su storage DB."""
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


def snapshot_update(lesson_dir):
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
    pointer = lesson_path(lesson_dir, POINTER)
    old = None
    if fs.isfile(pointer):
        with fs.open(pointer, encoding="utf-8") as stream:
            old = json.load(stream)
    with fs.open(pointer + ".tmp", "w", encoding="utf-8") as stream:
        json.dump({"timestamp": stamp, "files": entries, "root_markdown": root_markdown}, stream)
    fs.replace(pointer + ".tmp", pointer)
    if old:
        fs.rmtree(os.path.join(lesson_dir, "history", old["timestamp"]), ignore_errors=True)
    return stamp


def has_update_snapshot(lesson_dir):
    return fs.isfile(lesson_path(lesson_dir, POINTER))


def undo_update(lesson_dir):
    """Il chiamante tiene il lock della lezione; ripristino transazionale nel DB."""
    from rt.db.engine import get_database
    from rt.db.session import session_scope
    from rt.db.sync import suspend_dual_write, dual_write_lesson
    from rt.pipeline.source_update import _read_state, _write_state
    pointer = lesson_path(lesson_dir, POINTER)
    if not fs.isfile(pointer):
        raise ValueError("Non c'è un aggiornamento da annullare")
    with fs.open(pointer, encoding="utf-8") as stream:
        snapshot = json.load(stream)
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
            fs.remove(pointer)
    except BaseException:
        if not fs.is_db_lesson(lesson_dir):
            restore(current)
        raise
    dual_write_lesson(lesson_dir)
    fs.rmtree(history, ignore_errors=True)
    return {"status": "update_undone"}
