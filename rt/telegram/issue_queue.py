"""
rt.telegram.issue_queue
Coda ordinata delle issue ASR/scientifiche da rivedere via Telegram per una
lezione (telegram_issue_queue.json dentro lesson_dir). A differenza della
conferma outline, qui non c'è un concetto di "round"/rigenerazione: è una
semplice camminata sequenziale su una lista calcolata una volta all'avvio.
"""
import os
import json
from typing import Optional, Dict, List
from rt.core.models import IssueReviewQueueState


def get_queue_path(lesson_dir: str) -> str:
    return os.path.join(lesson_dir, "telegram_issue_queue.json")


def load_queue(lesson_dir: str) -> Optional[IssueReviewQueueState]:
    path = get_queue_path(lesson_dir)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return IssueReviewQueueState.model_validate(data)


def _save(state: IssueReviewQueueState, lesson_dir: str) -> None:
    path = get_queue_path(lesson_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def create_queue(lesson_dir: str, issue_ids: List[str], issue_types: Dict[str, str]) -> IssueReviewQueueState:
    state = IssueReviewQueueState(issue_ids=issue_ids, issue_types=issue_types, current_index=0)
    _save(state, lesson_dir)
    return state


def advance(lesson_dir: str) -> Optional[IssueReviewQueueState]:
    state = load_queue(lesson_dir)
    if state is None:
        return None
    state.current_index += 1
    _save(state, lesson_dir)
    return state
