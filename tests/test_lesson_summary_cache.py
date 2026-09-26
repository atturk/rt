"""
FA4: la cache dei riepiloghi di GET /lessons. Una lezione invariata non si ricalcola; ogni
scrittura (file della lezione in cartella o nel DB, decisioni, chiamate LLM) la invalida.
"""
import pytest

from rt.services import lesson_service
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def counted(monkeypatch):
    calls = []
    real = lesson_service._lesson_summary

    def spy(lesson_id, lesson_dir):
        calls.append(lesson_id)
        return real(lesson_id, lesson_dir)

    monkeypatch.setattr(lesson_service, "_lesson_summary", spy)
    lesson_service.clear_summary_cache()
    return calls


def _waiting_on_issues(tmp_path, monkeypatch):
    from rt.services.outline_service import approve_outline
    lesson_dir = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=False)
    approve_outline(lesson_dir, channel="api")
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=False)
    return lesson_dir


def test_unchanged_lessons_are_not_recomputed(tmp_path, monkeypatch, rt_db, counted):
    lesson_dir = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    first = lesson_service.list_lessons()
    assert len(counted) == 1
    assert lesson_service.list_lessons() == first
    assert lesson_service.list_lessons(text="lipidi") == first
    assert len(counted) == 1
    # Una modifica al file della lezione (anche fatta fuori da RT) invalida la voce.
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=False)
    after = lesson_service.list_lessons()
    assert len(counted) == 2
    assert after[0]["phases"]["outline"] == "VALID" != first[0]["phases"]["outline"]


def test_cached_items_are_copies(tmp_path, monkeypatch, rt_db, counted):
    make_lesson(isolated_workspace(tmp_path, monkeypatch))
    lesson_service.list_lessons()[0]["phases"]["prepare"] = "ALTERATO"
    assert lesson_service.list_lessons()[0]["phases"]["prepare"] != "ALTERATO"


@pytest.mark.parametrize("storage", ["folder", "db"])
def test_decision_invalidates_the_summary(tmp_path, monkeypatch, rt_db, counted, storage):
    from rt.services import review_service
    lesson_dir = _waiting_on_issues(tmp_path, monkeypatch)
    if storage == "db":
        from rt.storage.migrate import migrate_storage
        assert not migrate_storage(lesson_service.lessons_root()).errors
    before = lesson_service.list_lessons()[0]
    assert before["pending_issues"] > 0
    assert lesson_service.list_lessons()[0] == before
    issue = review_service.list_pending_issues(lesson_dir, with_context=False)[0]["issue"]
    review_service.record_review_decision(lesson_dir, issue["id"], "accepted", channel="api")
    assert lesson_service.list_lessons()[0]["pending_issues"] == before["pending_issues"] - 1


def test_llm_call_invalidates_the_cost(tmp_path, monkeypatch, rt_db, counted):
    from rt.db.repositories import LessonRepository, LlmCallRepository
    from rt.db.session import session_scope
    lesson_dir = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    lesson_service.list_lessons()
    with session_scope(rt_db) as session:  # solo il DB: nessun file della lezione cambia
        lesson = LessonRepository(session).get_by_path(lesson_dir)
        LlmCallRepository(session).add(lesson, {"job": "outline", "status": "success", "estimated_cost": 0.5,
                                                "provider": "mock", "model": "m"})
    assert lesson_service.list_lessons()[0]["cost_usd"] == pytest.approx(0.5)
