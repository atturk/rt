"""Fotografie reversibili e ultime versioni della lezione, anche su storage DB."""
import json
import os
import tempfile
from dataclasses import dataclass
from contextlib import nullcontext
from datetime import datetime, timezone

from rt.core.lesson_paths import lesson_path
from rt.storage import fs

FILES = ("sources.json", "segments.json", "outline.json", "draft.json", "review_decisions.json",
         "info.yaml", "manifest.json", "source_update.json", "transcript_normalized.md",
         "pipeline_version.json", "science_issues.json", "review_units.json", "review_sequence.json",
         "enrichment.json", "unit_relevance.json", "unit_question_types.json", "unit_prefilter.json",
         "unit_relevance_resolved.json", "section_labels.json", "documents.json",
         "rielaborato.md", "pre-elaborato.md", "Errori concettuali.md",
         "material_attachments.json", "assets/images/placement.json", "assets/images/descriptions.json")
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


def _material_cache_files(lesson_dir):
    """Anche la cache delle pagine deve tornare com'era dopo una rilettura delle fonti."""
    found = []
    def visit(relative):
        folder = os.path.join(lesson_dir, relative)
        if not fs.isdir(folder):
            return
        for name in fs.listdir(folder):
            child = relative + "/" + name
            path = os.path.join(lesson_dir, child)
            if os.path.islink(path):
                continue
            if fs.isdir(path):
                visit(child)
            elif fs.isfile(path):
                found.append(child)
    visit("materials")
    return sorted(found)


def _capture(lesson_dir, stamp=None, *, include_material_cache=True):
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    history = os.path.join(lesson_dir, "history", stamp)
    fs.makedirs(history, exist_ok=True)
    entries = {}
    material_cache = _material_cache_files(lesson_dir) if include_material_cache else []
    root_markdown = [name for name in fs.listdir(lesson_dir) if name.endswith(".md")
                     and fs.isfile(os.path.join(lesson_dir, name))]
    for name in dict.fromkeys((*FILES, *root_markdown, *material_cache)):
        path = lesson_path(lesson_dir, name)
        entries[name] = fs.isfile(path)
        if entries[name]:
            destination = os.path.join(history, name)
            fs.makedirs(os.path.dirname(destination), exist_ok=True)
            fs.copy2(path, destination)
    return {"timestamp": stamp, "files": entries, "root_markdown": root_markdown,
            **({"material_cache": material_cache} if include_material_cache else {})}


def snapshot_update(lesson_dir, *, keep_previous=False, include_material_cache=True):
    snapshot = _capture(lesson_dir, include_material_cache=include_material_cache)
    old = _read_pointer(lesson_dir)
    _write_pointer(lesson_dir, snapshot)
    if old and not keep_previous:
        fs.rmtree(os.path.join(lesson_dir, "history", old["timestamp"]), ignore_errors=True)
    return snapshot["timestamp"]


def begin_update(lesson_dir, *, include_material_cache=True):
    """Fotografia dell'aggiornamento che parte; quella precedente resta finché non riesce."""
    previous = _read_pointer(lesson_dir)
    snapshot_update(lesson_dir, keep_previous=True, include_material_cache=include_material_cache)
    return previous


def finish_update(lesson_dir, previous):
    """Aggiornamento riuscito: resta una sola fotografia, la sua."""
    if previous:
        fs.rmtree(os.path.join(lesson_dir, "history", previous["timestamp"]), ignore_errors=True)


def abort_update(lesson_dir, previous):
    """Aggiornamento fallito: rimette la lezione com'era e la fotografia dell'aggiornamento
    precedente, così Annulla continua ad annullare quello."""
    undo_update(lesson_dir, record_event=False)
    if previous:
        _write_pointer(lesson_dir, previous)


def has_update_snapshot(lesson_dir):
    return fs.isfile(lesson_path(lesson_dir, POINTER))


def _merge_newer_sources(restored, current):
    """Le fonti caricate dopo la fotografia (ancora da usare) sopravvivono al ripristino:
    si accodano al registro ripristinato e i loro file restano dove sono."""
    if restored is None or current is None:
        return restored
    try:
        restored_items = json.loads(restored)
        known = {item["id"] for item in restored_items}
        newer = [item for item in json.loads(current) if item["id"] not in known]
    except (ValueError, TypeError, KeyError):
        return restored
    if not newer:
        return restored
    for position, item in enumerate(newer, len(restored_items) + 1):
        restored_items.append({**item, "ordine": position})
    return json.dumps(restored_items, ensure_ascii=False, indent=2).encode("utf-8")


@dataclass(frozen=True)
class _CacheCopy:
    path: str


def _restore_snapshot(lesson_dir, snapshot):
    # Le immagini delle slide possono essere grandi: le copie di sicurezza restano su disco.
    with tempfile.TemporaryDirectory(prefix="rt-restore-cache-") as cache_backup:
        return _restore_snapshot_files(lesson_dir, snapshot, cache_backup)


def _restore_snapshot_files(lesson_dir, snapshot, cache_backup):
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
            path = os.path.join(history, name)
            if name.replace("\\", "/").startswith("materials/"):
                # Verifica tutta la copia prima di modificare la lezione, senza accumularla in RAM.
                with fs.materialize(path) as real, open(real, "rb") as stream:
                    while stream.read(1 << 20):
                        pass
                content[name] = _CacheCopy(path)
            else:
                with fs.open(path, "rb") as stream:
                    content[name] = stream.read()
        else:
            content[name] = None
    for name in fs.listdir(lesson_dir):
        if name.endswith(".md") and fs.isfile(os.path.join(lesson_dir, name)) and name not in snapshot["root_markdown"]:
            content.setdefault(name, None)
    if "material_cache" in snapshot:
        for name in _material_cache_files(lesson_dir):
            content.setdefault(name, None)
    current = {}
    for name in content:
        path = lesson_path(lesson_dir, name)
        if fs.isfile(path):
            if name.replace("\\", "/").startswith("materials/"):
                backup_path = os.path.join(cache_backup, str(len(current)))
                fs.copy2(path, backup_path)
                current[name] = _CacheCopy(backup_path)
            else:
                with fs.open(path, "rb") as stream:
                    current[name] = stream.read()
        else:
            current[name] = None
    highwater = _read_state(lesson_dir)["next_segment"]
    content["sources.json"] = _merge_newer_sources(content.get("sources.json"), current.get("sources.json"))
    def restore(values):
        for name, data in values.items():
            path = lesson_path(lesson_dir, name)
            if data is None:
                if fs.isfile(path):
                    fs.remove(path)
            else:
                fs.makedirs(os.path.dirname(path), exist_ok=True)
                if isinstance(data, _CacheCopy):
                    stem, extension = os.path.splitext(path)
                    temporary = stem + ".restore-tmp" + extension
                    try:
                        fs.copy2(data.path, temporary)
                        fs.replace(temporary, path)
                    finally:
                        if fs.isfile(temporary):
                            fs.remove(temporary)
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
        # Il DB ripristina le righe, ma i file multimediali sono su disco: si recuperano anch'essi.
        with session_scope(db) if db else nullcontext(), suspend_dual_write():
            restore(current)
        raise
    dual_write_lesson(lesson_dir)


def undo_update(lesson_dir, *, record_event=True):
    snapshot = _read_pointer(lesson_dir)
    if snapshot is None:
        raise ValueError("Non c'è un aggiornamento da annullare")
    _restore_snapshot(lesson_dir, snapshot)
    fs.remove(lesson_path(lesson_dir, POINTER))
    fs.rmtree(os.path.join(lesson_dir, "history", snapshot["timestamp"]), ignore_errors=True)
    if record_event:
        # Annulla aggiornamento: il riepilogo dell'ultimo aggiornamento non vale più.
        from rt.pipeline.source_update import _read_state, _write_state
        state = _read_state(lesson_dir)
        if state.get("ultimo_aggiornamento") is not None:
            state["ultimo_aggiornamento"] = None
            _write_state(lesson_dir, state)
    if record_event and _versions(lesson_dir):
        record_version(lesson_dir, "restore")
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
    existing = _versions(lesson_dir)
    sequence = max((int(v["id"][4:]) for v in existing if v["id"].startswith("ver_")), default=0) + 1
    snapshot = _capture(lesson_dir, stamp=f"ver_{sequence:06d}")
    version = {"id": snapshot["timestamp"], "il": datetime.now(timezone.utc).isoformat(),
        "modo": mode, "fonti_aggiunte": added or [], "unita_nuove": new,
        "unita_cambiate": changed, "snapshot": snapshot}
    versions = [version, *existing]
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


def refresh_current_version(lesson_dir):
    """Completa la fotografia dell'evento corrente dopo la scrittura dei documenti."""
    versions = _versions(lesson_dir)
    if versions:
        versions[0]["snapshot"] = _capture(lesson_dir, stamp=versions[0]["id"])
        _save_versions(lesson_dir, versions)
