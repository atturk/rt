"""Stato precedente calcolato dai cambi dell'unità, senza migrare lo studio."""
from datetime import datetime, timezone

from rt.pipeline.source_update import _read_state


def is_previous(lesson_dir, unit_ids, created_at):
    if not created_at:
        return False
    created = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    changes = _read_state(lesson_dir).get("unit_changed_at", {})
    return any(uid in changes and created < datetime.fromisoformat(changes[uid]) for uid in unit_ids)


def previous_for_lesson(lesson_id, unit_id, created_at):
    from rt.db.engine import get_database
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    with read_scope(get_database()) as session:
        lesson = session.get(Lesson, lesson_id)
        return bool(lesson and is_previous(lesson.path, [unit_id], created_at))
