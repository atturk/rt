"""
rt.db.repositories
Accesso ai dati per i servizi: ogni repository lavora su una Session aperta dal chiamante
(rt.db.session.session_scope), così più operazioni stanno nella stessa transazione.
"""
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from rt.db.models import Issue, Lesson, LlmCall, PhaseRun, ReviewDecision, Setting, utcnow


def normalize_lesson_path(lesson_dir: str) -> str:
    return os.path.realpath(os.path.abspath(lesson_dir))


class LessonRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_path(self, lesson_dir: str) -> Optional[Lesson]:
        return self.session.scalar(select(Lesson).where(Lesson.path == normalize_lesson_path(lesson_dir)))

    def get_or_create(self, lesson_dir: str) -> Lesson:
        lesson = self.get_by_path(lesson_dir)
        if lesson is None:
            path = normalize_lesson_path(lesson_dir)
            lesson = Lesson(path=path, folder_name=os.path.basename(path))
            self.session.add(lesson)
            self.session.flush()
        return lesson

    def update_fields(self, lesson: Lesson, fields: Dict[str, Any]) -> None:
        for key, value in fields.items():
            if getattr(lesson, key) != value:
                setattr(lesson, key, value)

    def list_all(self, under_root: Optional[str] = None) -> List[Lesson]:
        stmt = select(Lesson).order_by(Lesson.folder_name)
        lessons = list(self.session.scalars(stmt))
        if under_root:
            root = normalize_lesson_path(under_root)
            lessons = [l for l in lessons if os.path.dirname(l.path) == root]
        return lessons

    def delete(self, lesson: Lesson) -> None:
        self.session.delete(lesson)


class PhaseRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def for_lesson(self, lesson: Lesson) -> Dict[str, PhaseRun]:
        return {p.phase: p for p in self.session.scalars(select(PhaseRun).where(PhaseRun.lesson_id == lesson.id))}

    def replace_for_lesson(self, lesson: Lesson, runs: Dict[str, Dict[str, Any]]) -> None:
        existing = self.for_lesson(lesson)
        for phase, fields in runs.items():
            row = existing.pop(phase, None)
            if row is None:
                self.session.add(PhaseRun(lesson_id=lesson.id, phase=phase, **fields))
            else:
                for key, value in fields.items():
                    if getattr(row, key) != value:
                        setattr(row, key, value)
        for row in existing.values():
            self.session.delete(row)


class IssueRepository:
    def __init__(self, session: Session):
        self.session = session

    def for_lesson(self, lesson: Lesson) -> Dict[str, Issue]:
        return {i.issue_id: i for i in self.session.scalars(select(Issue).where(Issue.lesson_id == lesson.id))}

    def replace_for_lesson(self, lesson: Lesson, issues: Dict[str, Dict[str, Any]]) -> None:
        existing = self.for_lesson(lesson)
        for issue_id, fields in issues.items():
            row = existing.pop(issue_id, None)
            if row is None:
                self.session.add(Issue(lesson_id=lesson.id, issue_id=issue_id, **fields))
            else:
                for key, value in fields.items():
                    if getattr(row, key) != value:
                        setattr(row, key, value)
        for row in existing.values():
            self.session.delete(row)


DECISION_FIELDS = ("issue_id", "decision", "resolved_text", "resolved_by", "timestamp",
                   "notes", "original_context", "channel", "actor")


class DecisionRepository:
    def __init__(self, session: Session):
        self.session = session

    def active(self, lesson: Lesson) -> List[ReviewDecision]:
        """Decisioni non annullate, nell'ordine del ledger."""
        stmt = (select(ReviewDecision)
                .where(ReviewDecision.lesson_id == lesson.id, ReviewDecision.reverted_at.is_(None))
                .order_by(ReviewDecision.id))
        return list(self.session.scalars(stmt))

    def append(self, lesson: Lesson, fields: Dict[str, Any]) -> ReviewDecision:
        row = ReviewDecision(lesson_id=lesson.id, **{k: fields.get(k) for k in DECISION_FIELDS})
        if row.resolved_by is None:
            row.resolved_by = "user"
        self.session.add(row)
        self.session.flush()
        return row

    def revert(self, rows: Iterable[ReviewDecision], when: Optional[datetime] = None) -> int:
        when = when or utcnow()
        count = 0
        for row in rows:
            row.reverted_at = when
            count += 1
        self.session.flush()
        return count

    def revert_last(self, lesson: Lesson, issue_id: str) -> Optional[ReviewDecision]:
        rows = [r for r in self.active(lesson) if r.issue_id == issue_id]
        if not rows:
            return None
        self.revert(rows[-1:])
        return rows[-1]

    def revert_prefix(self, lesson: Lesson, prefix: str) -> int:
        return self.revert(r for r in self.active(lesson) if r.issue_id.startswith(prefix))

    def replace_active(self, lesson: Lesson, decisions: Iterable[Dict[str, Any]]) -> None:
        """Rende attive esattamente `decisions` (import da file): le righe identiche restano,
        le altre attive vengono marcate come annullate, le nuove aggiunte in coda."""
        wanted = [{k: d.get(k) for k in DECISION_FIELDS} for d in decisions]
        current = self.active(lesson)
        keep = 0
        while keep < min(len(current), len(wanted)) and \
                all(getattr(current[keep], k) == wanted[keep][k] for k in DECISION_FIELDS):
            keep += 1
        self.revert(current[keep:])
        for fields in wanted[keep:]:
            self.append(lesson, fields)


class LlmCallRepository:
    def __init__(self, session: Session):
        self.session = session

    COLUMNS = ("execution_id", "request_id", "job", "unit_id", "route_role", "provider", "model",
               "input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
               "estimated_cost", "status", "failure_class", "timestamp")

    def add(self, lesson: Optional[Lesson], entry: Dict[str, Any]) -> LlmCall:
        fields = {}
        for key in self.COLUMNS:
            value = entry.get(key)
            if key in ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
                value = value if isinstance(value, int) and not isinstance(value, bool) else None
            elif key == "estimated_cost":
                value = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            elif value is not None:
                value = str(value)
            fields[key] = value
        row = LlmCall(lesson_id=lesson.id if lesson else None, payload=dict(entry), **fields)
        self.session.add(row)
        return row

    def count_for_lesson(self, lesson: Lesson) -> int:
        return self.session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.lesson_id == lesson.id)) or 0

    def entries_for_lesson(self, lesson: Lesson) -> List[Dict[str, Any]]:
        stmt = select(LlmCall.payload).where(LlmCall.lesson_id == lesson.id).order_by(LlmCall.id)
        return [dict(p) for p in self.session.scalars(stmt)]

    def delete_for_lesson(self, lesson: Lesson) -> None:
        self.session.execute(delete(LlmCall).where(LlmCall.lesson_id == lesson.id))


class SettingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str, default: Any = None) -> Any:
        row = self.session.get(Setting, key)
        return row.value if row is not None else default

    def set(self, key: str, value: Any) -> None:
        row = self.session.get(Setting, key)
        if row is None:
            self.session.add(Setting(key=key, value=value))
        else:
            row.value = value

    def delete(self, key: str) -> None:
        row = self.session.get(Setting, key)
        if row is not None:
            self.session.delete(row)
