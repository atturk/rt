"""
tests/test_db_authoritative.py
RT4-B3: ledger con il DB come fonte di verità (e review_decisions.json esportato), chiamate
LLM e 'rt cost' dal DB, stato del daemon Telegram nel DB con import una tantum dai JSON,
concorrenza CLI + daemon sulla stessa lezione.
"""
import json
import os
import subprocess
import sys

import pytest

from rt.db.engine import reset_database_cache
from rt.db.models import ReviewDecision as DbDecision, StateDocument
from rt.db.repositories import DecisionRepository, LessonRepository, LlmCallRepository
from rt.db.session import session_scope
from rt.db.state_documents import MIGRATED_SUFFIX
from rt.db.sync import check_all, sync_all
from rt.pipeline.ledger import (
    get_ledger_path, load_ledger, purge_decisions_by_prefix, record_decision, revert_last_decision,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def lesson(tmp_path):
    root = tmp_path / "lezioni"
    lesson_dir = root / "[2026-09-01] BIOCHIMICA - Lipidi"
    (lesson_dir / "_state").mkdir(parents=True)
    (lesson_dir / "_state" / "info.yaml").write_text(
        "data: '2026-09-01'\nmateria: BIOCHIMICA\ntitolo: Lipidi\nfase_corrente: pronto_per_build\n", encoding="utf-8")
    return str(root), str(lesson_dir)


def _ledger_bytes(lesson_dir):
    with open(get_ledger_path(lesson_dir), "rb") as f:
        return f.read()


def _file_mode_ledger(tmp_path, monkeypatch, ops):
    """Stesse operazioni senza DB, per confrontare il file prodotto."""
    other = tmp_path / "senza_db"
    (other / "_state").mkdir(parents=True)
    monkeypatch.setenv("RT_DATABASE_URL", "off")
    reset_database_cache()
    for op in ops:
        op(str(other))
    return _ledger_bytes(str(other))


def _ops():
    return [
        lambda d: record_decision(d, "sci_000001", "accepted", resolved_text="A", channel="cli", actor="user"),
        lambda d: record_decision(d, "sci_000002", "rejected", resolved_text="B", notes="n"),
        lambda d: record_decision(d, "asr_000001", "edited", resolved_text="C", channel="telegram", actor="user"),
        lambda d: revert_last_decision(d, "sci_000002"),
        lambda d: record_decision(d, "sci_000002", "edited", resolved_text="B2", channel="web", actor="user"),
        lambda d: purge_decisions_by_prefix(d, "asr_"),
    ]


def test_ledger_written_through_db_and_exported(rt_db, lesson, tmp_path, monkeypatch):
    root, lesson_dir = lesson
    for op in _ops():
        op(lesson_dir)
    exported = _ledger_bytes(lesson_dir)
    ids = [d.issue_id for d in load_ledger(lesson_dir).decisions]
    assert ids == ["sci_000001", "sci_000002"]
    with session_scope(rt_db) as s:
        les = LessonRepository(s).get_by_path(lesson_dir)
        assert [d.resolved_text for d in DecisionRepository(s).active(les)] == ["A", "B2"]
        # le decisioni annullate restano nel DB come storico
        reverted = s.query(DbDecision).filter(DbDecision.reverted_at.isnot(None)).all()
        assert sorted(d.resolved_text for d in reverted) == ["B", "C"]
    assert check_all(rt_db, root) == []
    # stesso file, a parte i timestamp, del percorso senza DB
    file_mode = json.loads(_file_mode_ledger(tmp_path, monkeypatch, _ops()))
    db_mode = json.loads(exported)
    for d in file_mode["decisions"] + db_mode["decisions"]:
        d.pop("timestamp")
    assert db_mode == file_mode


def test_no_file_created_when_nothing_to_revert(rt_db, lesson):
    _, lesson_dir = lesson
    assert revert_last_decision(lesson_dir, "sci_x") is False
    assert purge_decisions_by_prefix(lesson_dir, "asr_") == 0
    assert not os.path.exists(get_ledger_path(lesson_dir))


def test_hand_edited_ledger_is_reimported_before_next_write(rt_db, lesson):
    root, lesson_dir = lesson
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="A")
    record_decision(lesson_dir, "sci_2", "accepted", resolved_text="B")
    path = get_ledger_path(lesson_dir)
    data = json.load(open(path, encoding="utf-8"))
    data["decisions"] = data["decisions"][1:]  # l'utente toglie a mano sci_1
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    record_decision(lesson_dir, "sci_3", "accepted", resolved_text="C")
    assert [d.issue_id for d in load_ledger(lesson_dir).decisions] == ["sci_2", "sci_3"]
    assert check_all(rt_db, root) == []


def test_sync_imports_only_changed_ledgers(rt_db, lesson):
    root, lesson_dir = lesson
    record_decision(lesson_dir, "sci_1", "accepted", resolved_text="A")
    revert_last_decision(lesson_dir, "sci_1")
    record_decision(lesson_dir, "sci_1", "rejected", resolved_text="A")
    with session_scope(rt_db) as s:
        before = s.query(DbDecision).count()
    sync_all(rt_db, root)
    with session_scope(rt_db) as s:
        assert s.query(DbDecision).count() == before  # file invariato: nessun reimport


def test_llm_calls_and_cost_from_db(rt_db, lesson):
    from rt.llm.client import _append_debug_log
    from rt.pipeline.cost import compute_lesson_cost
    _, lesson_dir = lesson
    log = os.path.join(lesson_dir, "_state", "llm_debug.log")
    # chiamata registrata prima che esistesse il DB: solo nel file
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({"job": "outline", "provider": "mock", "model": "m", "status": "success",
                            "estimated_cost": 0.5, "input_tokens": 10}) + "\n")
    _append_debug_log(lesson_dir, {"job": "rewrite", "unit_id": "u1", "provider": "mock", "model": "m",
                                   "status": "success", "estimated_cost": 0.25, "execution_id": "e1"})
    _append_debug_log(lesson_dir, {"job": "rewrite", "unit_id": "u1", "provider": "mock", "model": "m",
                                   "status": "error", "estimated_cost": None, "attempt": 2})
    with session_scope(rt_db) as s:
        les = LessonRepository(s).get_by_path(lesson_dir)
        assert LlmCallRepository(s).count_for_lesson(les) == 3
    from_db = compute_lesson_cost(lesson_dir)
    os.remove(log)
    assert compute_lesson_cost(lesson_dir) == from_db  # il DB basta da solo
    assert from_db["total_calls"] == 3 and from_db["total_estimated_cost_usd"] == 0.75
    assert from_db["unknown_cost_calls"] == 1


def test_cost_falls_back_to_file_without_db(lesson):
    from rt.llm.client import _append_debug_log
    from rt.pipeline.cost import compute_lesson_cost
    _, lesson_dir = lesson
    _append_debug_log(lesson_dir, {"job": "outline", "provider": "mock", "model": "m",
                                   "status": "success", "estimated_cost": 0.1})
    assert compute_lesson_cost(lesson_dir)["total_calls"] == 1


def test_telegram_state_imported_once_and_renamed(rt_db, tmp_path):
    from rt.telegram import audio_sent, conversation_state, issue_queue, last_lesson, recall_preferences, registry, session
    state_dir = tmp_path / "tg"
    state_dir.mkdir()
    lesson_dir = tmp_path / "lez"
    (lesson_dir / "_state").mkdir(parents=True)
    files = {
        "active_sessions.json": {"schema_version": "1.0", "sessions": {"1:general": {
            "kind": "review", "lesson_dir": str(lesson_dir), "started_at": "t", "chat_id": "1",
            "thread_id": None, "message_id": 5}}},
        "registry.json": {"schema_version": "1.0", "entries": {"abc123": {"lesson_dir": str(lesson_dir)}}},
        "awaiting_feedback.json": {"1": {"short_id": "abc123", "lesson_dir": str(lesson_dir), "kind": "outline_feedback"}},
        "recall_preferences.json": {"active_style": "vasta"},
        "last_lesson_per_topic.json": {"1:general": {"lesson_dir": str(lesson_dir), "updated_at": "t"}},
    }
    for name, data in files.items():
        (state_dir / name).write_text(json.dumps(data), encoding="utf-8")
    (lesson_dir / "_state" / "telegram_issue_queue.json").write_text(
        json.dumps({"issue_ids": ["a", "b"], "issue_types": {"a": "science", "b": "science"}, "current_index": 1}))
    (lesson_dir / "_state" / "telegram_audio_sent.json").write_text(json.dumps({"s1-s2": {"message_id": 9}}))

    # nessuna sessione attiva persa
    assert session.get_active_session(str(state_dir), 1)["message_id"] == 5
    assert registry._load_registry(str(state_dir))["entries"]["abc123"]["lesson_dir"] == str(lesson_dir)
    assert conversation_state.get_awaiting_feedback(str(state_dir), 1)["short_id"] == "abc123"
    assert recall_preferences.get_active_style(str(state_dir)) == "vasta"
    assert last_lesson.get_last_lesson(str(state_dir), 1, None) == str(lesson_dir)
    assert issue_queue.load_queue(str(lesson_dir)).current_index == 1
    assert audio_sent.get_sent_audio(str(lesson_dir), "s1", "s2")["message_id"] == 9

    for name in files:
        assert not (state_dir / name).exists() and (state_dir / (name + MIGRATED_SUFFIX)).exists()
    assert (lesson_dir / "_state" / ("telegram_issue_queue.json" + MIGRATED_SUFFIX)).exists()

    # da qui in poi solo DB: le scritture non ricreano i file
    session.update_session_message(str(state_dir), 1, None, 7)
    session.start_session(str(state_dir), 2, 44, "recall", str(lesson_dir))
    issue_queue.advance(str(lesson_dir))
    recall_preferences.set_active_style(str(state_dir), "quiz")
    conversation_state.clear_awaiting_feedback(str(state_dir), 1)
    audio_sent.record_sent_audio(str(lesson_dir), "s3", "s4", 10)
    last_lesson.record_last_lesson(str(state_dir), 2, 44, str(lesson_dir))
    assert not (state_dir / "active_sessions.json").exists()
    assert session.get_active_session(str(state_dir), 1)["message_id"] == 7
    assert session.get_active_session_for_lesson(str(state_dir), str(lesson_dir), kind="recall")["thread_id"] == "44"
    assert issue_queue.load_queue(str(lesson_dir)).current_index == 2
    assert recall_preferences.get_active_style(str(state_dir)) == "quiz"
    assert conversation_state.get_awaiting_feedback(str(state_dir), 1) is None
    assert audio_sent.get_sent_audio(str(lesson_dir), "s3", "s4")["message_id"] == 10
    assert last_lesson.get_last_lesson(str(state_dir), 2, 44) == str(lesson_dir)
    with session_scope(rt_db) as s:
        assert s.query(StateDocument).count() == 7


def test_telegram_state_without_db_uses_files(tmp_path):
    from rt.telegram import session
    session.start_session(str(tmp_path), 1, None, "review", str(tmp_path))
    assert (tmp_path / "active_sessions.json").exists()


CONCURRENT_WRITER = r"""
import os, sys
from rt.services.review_service import record_review_decision
lesson_dir, channel, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
for i in range(n):
    record_review_decision(lesson_dir, f"{channel}_{i:03d}", "accepted", "x", channel=channel)
"""


def test_concurrent_cli_and_daemon_decisions_on_same_lesson(rt_db, lesson):
    root, lesson_dir = lesson
    env = dict(os.environ)
    env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    procs = [subprocess.Popen([sys.executable, "-c", CONCURRENT_WRITER, lesson_dir, ch, "15"], env=env)
             for ch in ("cli", "telegram")]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    ids = [d.issue_id for d in load_ledger(lesson_dir).decisions]
    assert sorted(ids) == sorted([f"cli_{i:03d}" for i in range(15)] + [f"telegram_{i:03d}" for i in range(15)])
    assert ids == sorted(ids, key=ids.index)  # nessun duplicato
    assert len(set(ids)) == 30
    assert check_all(rt_db, root) == []
