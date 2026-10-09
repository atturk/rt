"""Cache indipendente dei due verdetti che precedono la revisione."""
import json
from datetime import datetime, timezone
from functools import wraps

from rt.core.lesson_paths import lesson_path
from rt.services.recall_context import digest, lesson_context
from rt.services.unit_relevance import _lock
from rt.storage import fs


def load(lesson_dir):
    try:
        with fs.open(lesson_path(lesson_dir, "unit_prefilter.json"), encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def configuration(cfg, task):
    from rt.services.jev_mapping import effective_decision
    return digest([cfg.model, cfg.credential, cfg.base_url,
                   effective_decision("prefilter", cfg).model_dump() if task == "task_a" else "drift-1",
                   cfg.task_a_skip_confidence_threshold, cfg.task_b_fabrication_threshold])


def cached(task):
    def decorate(fn):
        @wraps(fn)
        def run(unit, *args, force=False):
            cfg, lesson_dir = args[-2:]
            text_hash = digest([unit.title, unit.content, lesson_context(lesson_dir)])
            config_hash = configuration(cfg, task)
            # La deriva diventa vecchia anche se cambia soltanto il trascritto.
            source_hash = digest(args[0]) if task == "task_b" else None
            row = load(lesson_dir).get(unit.unit_id, {})
            entry = row.get(task) or {}
            if (not force and row.get("text_hash") == text_hash and entry.get("config_hash") == config_hash
                    and entry.get("source_hash") == source_hash and entry.get("verdict") is not None):
                from rt.pipeline.review import JevTaskAVerdict, JevTaskBVerdict
                return (JevTaskAVerdict if task == "task_a" else JevTaskBVerdict)(**entry["verdict"])
            verdict = fn(unit, *args)
            now = datetime.now(timezone.utc).isoformat()
            try:
                with _lock(lesson_dir, "draft"):
                    records = load(lesson_dir)
                    row = records.get(unit.unit_id, {})
                    if row.get("text_hash") != text_hash:
                        row = {"text_hash": text_hash}
                    row.update(config_hash=config_hash, at=now, error=None if verdict else "Classificazione non disponibile")
                    row[task] = {"config_hash": config_hash, "source_hash": source_hash, "at": now,
                                 "error": None if verdict else "Classificazione non disponibile",
                                 "verdict": vars(verdict) if verdict else None}
                    records[unit.unit_id] = row
                    path = lesson_path(lesson_dir, "unit_prefilter.json")
                    with fs.open(path + ".tmp", "w", encoding="utf-8") as stream:
                        json.dump(records, stream, ensure_ascii=False, indent=2)
                    fs.replace(path + ".tmp", path)
            except (OSError, TimeoutError):
                pass  # La cache non impedisce la revisione se il salvataggio fallisce.
            return verdict
        return run
    return decorate


def refresh_prefilter(lesson_dir, unit_ids=None, force=False):
    from rt.core.config import load_config
    from rt.core.segments import load_segments_json
    from rt.pipeline.rewrite import load_draft
    from rt.pipeline.review import run_jev_task_a, run_jev_task_b
    cfg = load_config().jev
    segments = {s.id: s for s in load_segments_json(lesson_path(lesson_dir, "segments.json")).segments}
    for unit in load_draft(lesson_dir).units:
        if unit_ids is not None and unit.unit_id not in unit_ids:
            continue
        source = "\n".join(f"[{sid}] {segments[sid].text_raw}" for sid in unit.source_segment_ids if sid in segments)
        run_jev_task_a(unit, cfg, lesson_dir, force=force)
        run_jev_task_b(unit, source, cfg, lesson_dir, force=force)
    return load(lesson_dir)
