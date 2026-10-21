from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from rt.core.manifest import load_manifest
from rt.pipeline.build import write_automatic_documents
from rt.services import lesson_service
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


def test_pipeline_at_picks_most_recent_of_outline_rewrite_and_build():
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)

    manifest = SimpleNamespace(
        phase_records={
            "outline": {"updated_at": t1.isoformat()},
            "rewrite": {"updated_at": t2.isoformat()},
            "build": {"pipeline_at": t3.isoformat(), "updated_at": (t3 + timedelta(hours=1)).isoformat()},
        },
    )

    result = lesson_service._pipeline_at(manifest)
    assert result == t3


def test_pipeline_at_ignores_build_without_pipeline_at():
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    t_auto = datetime(2026, 10, 5, 18, 0, tzinfo=timezone.utc)

    manifest = SimpleNamespace(
        phase_records={
            "outline": {"updated_at": t1.isoformat()},
            "rewrite": {"updated_at": t2.isoformat()},
            # build aggiornato solo da automatic_documents (senza pipeline_at)
            "build": {"updated_at": t_auto.isoformat(), "automatic_documents": True},
        },
    )

    result = lesson_service._pipeline_at(manifest)
    # Deve scegliere il più recente tra outline e rewrite (t2), ignorando t_auto
    assert result == t2


def test_document_rewrite_after_decision_does_not_change_pipeline_at(tmp_path, monkeypatch, rt_db):
    lesson_dir = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    lesson_service.clear_summary_cache()

    # Eseguiamo la pipeline in mock (completa fino a build)
    run_mock_pipeline(lesson_dir, with_review=False, auto_accept=True)

    manifest = load_manifest(lesson_dir)
    assert "pipeline_at" in manifest.phase_records.get("build", {})
    initial_pipeline_at = lesson_service._pipeline_at(manifest)
    assert initial_pipeline_at is not None

    lessons = lesson_service.list_lessons()
    assert len(lessons) == 1
    assert lessons[0]["pipeline_at"] == initial_pipeline_at

    # Ora simuliamo una riscrittura automatica del documento (es. dopo una decisione o modifica)
    lesson_service.clear_summary_cache()
    write_automatic_documents(lesson_dir)

    manifest_after = load_manifest(lesson_dir)
    # updated_at di build cambia, ma pipeline_at deve restare identico
    assert manifest_after.phase_records["build"].get("pipeline_at") == manifest.phase_records["build"]["pipeline_at"]

    lessons_after = lesson_service.list_lessons()
    assert lessons_after[0]["pipeline_at"] == initial_pipeline_at
