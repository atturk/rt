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


def test_lesson_listing_uses_database_index_without_scanning_root(tmp_path, monkeypatch, rt_db):
    make_lesson(isolated_workspace(tmp_path, monkeypatch))
    monkeypatch.setattr("rt.core.lesson_index.scan_lessons", lambda *_: (_ for _ in ()).throw(
        AssertionError("non deve scandire la cartella delle lezioni")))
    assert len(lesson_service.list_lessons()) == 1


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


def test_global_prompt_does_not_make_done_phases_stale(tmp_path, monkeypatch, rt_db, counted):
    """Report 2, §5.3: cambiare un prompt vale per le esecuzioni future, non rende STALE le fasi fatte."""
    from rt.services.prompt_settings import set_global_instruction
    lesson_dir = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)
    assert lesson_service.list_lessons()[0]["phases"]["rewrite"] == "VALID"
    set_global_instruction("rewrite", "Metti in evidenza i collegamenti clinici.")
    lesson_service.clear_summary_cache()
    phases = lesson_service.list_lessons()[0]["phases"]
    assert phases["rewrite"] == "VALID" and phases["review"] == "VALID"


def test_metadata_change_recomputes_only_that_lesson(tmp_path, monkeypatch, rt_db, counted, capsys):
    from rt.services.lesson_metadata_service import update_metadata
    from rt.core.config import load_config
    root = isolated_workspace(tmp_path, monkeypatch)
    load_config()  # la migrazione una tantum di general.yaml invaliderebbe tutte le lezioni
    edited = make_lesson(root)
    make_lesson(root, "[2026-09-06] ALTRA")
    lesson_service.list_lessons()
    assert len(counted) == 2
    assert "2 lezioni, 0 dalla vetrina, 2 ricalcolate" in capsys.readouterr().out
    lesson_id = lesson_service.lesson_id_for_dir(edited)
    update_metadata(lesson_id, edited, {"titolo": "Nuovo titolo"})
    counted.clear()
    titles = {i["id"]: i["titolo"] for i in lesson_service.list_lessons()}
    assert counted == [lesson_id] and titles[lesson_id] == "Nuovo titolo"


def test_cold_restart_simulation_uses_vetrina_without_recomputing(tmp_path, monkeypatch, rt_db, counted, capsys):
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root, "[2026-09-05] LEZIONE 1")
    make_lesson(root, "[2026-09-06] LEZIONE 2")
    first = lesson_service.list_lessons()
    assert len(counted) == 2
    capsys.readouterr()

    # Riavvio simulato: memoria svuotata, tabella del DB piena
    lesson_service._summary_cache.clear()
    counted.clear()

    second = lesson_service.list_lessons()
    assert len(counted) == 0  # nessun _lesson_summary chiamato!
    assert second == first
    assert "2 lezioni, 2 dalla vetrina, 0 ricalcolate" in capsys.readouterr().out


def test_fingerprint_change_recomputes_and_updates_vetrina(tmp_path, monkeypatch, rt_db, counted):
    from sqlalchemy import select
    from rt.db.models import LessonSummaryCache
    from rt.db.session import read_scope
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    lesson_service.list_lessons()
    assert len(counted) == 1
    lid = lesson_service.lesson_id_for_dir(lesson_dir)

    with read_scope(rt_db) as s:
        old_fp = s.execute(select(LessonSummaryCache.fingerprint).where(LessonSummaryCache.lesson_id == lid)).scalar()

    # Riavvio simulato + modifica al file
    lesson_service._summary_cache.clear()
    counted.clear()
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=False)

    after = lesson_service.list_lessons()
    assert len(counted) == 1
    assert after[0]["phases"]["outline"] == "VALID"

    with read_scope(rt_db) as s:
        new_fp = s.execute(select(LessonSummaryCache.fingerprint).where(LessonSummaryCache.lesson_id == lid)).scalar()
    assert new_fp != old_fp


def test_different_schema_recomputes_and_updates_vetrina(tmp_path, monkeypatch, rt_db, counted):
    from sqlalchemy import select, update
    from rt.db.models import LessonSummaryCache
    from rt.db.session import read_scope, session_scope
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    lesson_service.list_lessons()
    assert len(counted) == 1
    lid = lesson_service.lesson_id_for_dir(lesson_dir)

    # Simula una riga con schema obsoleto (es. schema 0 o 99)
    with session_scope(rt_db) as s:
        s.execute(update(LessonSummaryCache).where(LessonSummaryCache.lesson_id == lid).values(schema=0))

    # Riavvio simulato
    lesson_service._summary_cache.clear()
    counted.clear()

    lesson_service.list_lessons()
    assert len(counted) == 1  # ricalcolato perché schema != SUMMARY_SCHEMA

    with read_scope(rt_db) as s:
        sch = s.execute(select(LessonSummaryCache.schema).where(LessonSummaryCache.lesson_id == lid)).scalar()
    assert sch == lesson_service.SUMMARY_SCHEMA


def test_deleted_lesson_row_is_deleted_from_vetrina(tmp_path, monkeypatch, rt_db, counted):
    import shutil
    from sqlalchemy import select
    from rt.db.models import LessonSummaryCache
    from rt.db.session import read_scope
    root = isolated_workspace(tmp_path, monkeypatch)
    l1 = make_lesson(root, "[2026-09-05] LEZIONE 1")
    l2 = make_lesson(root, "[2026-09-06] LEZIONE 2")
    lesson_service.list_lessons()
    id2 = lesson_service.lesson_id_for_dir(l2)

    with read_scope(rt_db) as s:
        assert len(s.execute(select(LessonSummaryCache)).all()) == 2

    # Rimuovi l2 dal filesystem
    shutil.rmtree(l2)
    lesson_service.list_lessons()

    with read_scope(rt_db) as s:
        rows = s.execute(select(LessonSummaryCache.lesson_id)).scalars().all()
        assert id2 not in rows
        assert len(rows) == 1


def test_clear_summary_cache_and_forget_summary_clear_table(tmp_path, monkeypatch, rt_db):
    from sqlalchemy import select
    from rt.db.models import LessonSummaryCache
    from rt.db.session import read_scope
    root = isolated_workspace(tmp_path, monkeypatch)
    l1 = make_lesson(root, "[2026-09-05] LEZIONE 1")
    l2 = make_lesson(root, "[2026-09-06] LEZIONE 2")
    lesson_service.list_lessons()
    id1 = lesson_service.lesson_id_for_dir(l1)
    id2 = lesson_service.lesson_id_for_dir(l2)

    with read_scope(rt_db) as s:
        assert len(s.execute(select(LessonSummaryCache)).all()) == 2

    lesson_service.forget_summary(id1)
    with read_scope(rt_db) as s:
        rows = s.execute(select(LessonSummaryCache.lesson_id)).scalars().all()
        assert id1 not in rows
        assert id2 in rows

    lesson_service.clear_summary_cache()
    with read_scope(rt_db) as s:
        assert len(s.execute(select(LessonSummaryCache)).all()) == 0


def test_concurrent_calls_do_not_recompute_the_same_lesson(tmp_path, monkeypatch, rt_db, counted):
    import concurrent.futures
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root, "[2026-09-05] LEZIONE 1")
    make_lesson(root, "[2026-09-06] LEZIONE 2")
    lesson_service.clear_summary_cache()
    counted.clear()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(lesson_service.list_lessons) for _ in range(4)]
        results = [f.result() for f in futures]

    assert len(results) == 4
    for res in results[1:]:
        assert res == results[0]
    # Nonostante 4 thread concorrenti su cache vuota, ogni lezione si calcola una sola volta!
    assert len(counted) == 2


def test_lifespan_warmup_runs_on_app_startup(tmp_path, monkeypatch, rt_db, counted):
    from rt.api.app import create_app
    from starlette.testclient import TestClient
    import time
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root)
    lesson_service.clear_summary_cache()
    counted.clear()

    app = create_app()
    with TestClient(app):
        # Il thread daemon parte durante l'entrata nel lifespan
        time.sleep(0.2)

    assert len(counted) >= 1


def test_memoization_load_segments_called_at_most_once_per_lesson(tmp_path, monkeypatch, rt_db):
    from rt.core import segments
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)

    lesson_service.clear_summary_cache()
    seg_calls = []
    real_load = segments.load_segments_json

    def spy_load(path):
        seg_calls.append(path)
        return real_load(path)

    monkeypatch.setattr(segments, "load_segments_json", spy_load)

    # list_lessons a freddo: load_segments_json deve essere chiamato al massimo 1 volta per lezione
    results = lesson_service.list_lessons()
    assert len(results) == 1
    assert len(seg_calls) <= 1


def test_memoization_returns_copies_preventing_mutation(tmp_path, monkeypatch, rt_db):
    from rt.core import segments
    from rt.core.lesson_paths import lesson_path
    from rt.storage import fs
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)

    seg_path = lesson_path(lesson_dir, "segments.json")
    with fs.read_snapshot():
        data1 = segments.load_segments_json(seg_path)
        if data1.segments:
            data1.segments[0].text_raw = "TESTO_MUTATO"
        data2 = segments.load_segments_json(seg_path)
        if data2.segments:
            assert data2.segments[0].text_raw != "TESTO_MUTATO"


def test_compute_file_sha256_uses_db_without_reading_bytes(tmp_path, monkeypatch, rt_db):
    from rt.core.idempotency import compute_file_sha256
    from rt.core.lesson_paths import lesson_path
    from rt.storage import fs
    from rt.storage.migrate import migrate_storage
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)
    assert not migrate_storage(lesson_service.lessons_root()).errors

    seg_path = lesson_path(lesson_dir, "segments.json")
    sha_val = compute_file_sha256(seg_path)
    assert len(sha_val) == 64

    # Per le lezioni nel DB, non deve aprire lo stream per rileggere i byte
    opened = []
    real_open = fs.open

    def spy_open(path, *args, **kwargs):
        opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(fs, "open", spy_open)
    assert compute_file_sha256(seg_path) == sha_val
    assert len(opened) == 0


def test_memoization_same_results_with_and_without(tmp_path, monkeypatch, rt_db):
    from contextlib import contextmanager
    from rt.storage import fs
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)

    lesson_service.clear_summary_cache()
    # Con memoizzazione attiva
    res_with = lesson_service.list_lessons()

    lesson_service.clear_summary_cache()
    # Senza memoizzazione (disabilitando i dizionari di snapshot)
    real_read_snapshot = fs.read_snapshot

    @contextmanager
    def no_cache_snapshot():
        with real_read_snapshot():
            fs._snapshot.segments_cache = None
            fs._snapshot.phase_status_cache = None
            yield

    monkeypatch.setattr(fs, "read_snapshot", no_cache_snapshot)
    res_without = lesson_service.list_lessons()

    assert res_with == res_without
