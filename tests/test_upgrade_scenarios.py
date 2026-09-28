"""Scenari di aggiornamento: checkpoint della 4.0.0 e lezioni a cartelle della 3.x."""
import os

from rt.core.idempotency import (
    PROCESSOR_VERSIONS, compute_file_sha256, compute_source_fingerprint, compute_string_sha256,
)
from rt.core.lesson_paths import lesson_path
from rt.storage import fs
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


def _v400_fingerprint(lesson_dir, phase):
    """Formula delle impronte della 4.0.0 (rt/core/idempotency.py al tag v4.0.0)."""
    seg = compute_file_sha256(lesson_path(lesson_dir, "segments.json"))
    if phase == "rewrite":
        out = compute_file_sha256(lesson_path(lesson_dir, "outline.json"))
        return compute_string_sha256(f"{seg}|{out}|{PROCESSOR_VERSIONS['rewrite']}")
    draft = compute_file_sha256(lesson_path(lesson_dir, "draft.json"))
    return compute_string_sha256(f"{draft}|{seg}|{PROCESSOR_VERSIONS['review']}")


def test_checkpoints_written_by_v400_stay_valid(tmp_path, monkeypatch, rt_db):
    lesson_dir = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    run_mock_pipeline(lesson_dir, with_review=True, auto_accept=True)
    for phase in ("rewrite", "review"):
        assert compute_source_fingerprint(lesson_dir, phase) == _v400_fingerprint(lesson_dir, phase)


def test_update_converts_folder_lessons_so_the_web_app_shows_them(api_client, tmp_path, monkeypatch, rt_db):
    """Come il job CI 'upgrade': una lezione a cartelle (3.x, non nel DB) dopo 'rt -u' è visibile."""
    from rt.services.data_service import _convert_folder_lessons
    from rt.services.doctor_service import WARN, OK, check_folder_lessons
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root, index=False)
    assert api_client.get("/api/v1/lessons").json() == []
    assert check_folder_lessons().status == WARN

    messages = []
    assert _convert_folder_lessons(messages.append)
    lessons = api_client.get("/api/v1/lessons").json()
    assert [item["folder_name"] for item in lessons] == [os.path.basename(lesson_dir)]
    assert fs.is_db_lesson(lesson_dir)
    assert check_folder_lessons().status == OK
    assert any("Backup" in m for m in messages)
    # idempotente: al secondo 'rt -u' non c'è più niente da convertire
    messages.clear()
    assert _convert_folder_lessons(messages.append) and messages == []
