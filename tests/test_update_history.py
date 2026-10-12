import json

import pytest

from rt.core.lesson_paths import lesson_path
from rt.core.update_history import snapshot_update, undo_update, has_update_snapshot
from rt.storage import fs


def test_photo_restores_required_files_and_removes_new_artifacts(tmp_path):
    lesson = str(tmp_path)
    originals = {"sources.json": b"[]", "segments.json": b'{"segments": []}',
                 "outline.json": b'{"original": true}', "review_decisions.json": b'{"decisions": []}',
                 "info.yaml": b"file_audio: original.wav\n", "Lesson.md": b"original document"}
    for name, data in originals.items():
        with fs.open(lesson_path(lesson, name), "wb") as stream:
            stream.write(data)
    stamp = snapshot_update(lesson)
    assert (tmp_path / "history" / stamp / "sources.json").is_file()
    for name in originals:
        with fs.open(lesson_path(lesson, name), "wb") as stream:
            stream.write(b"changed")
    with fs.open(lesson_path(lesson, "draft.json"), "w") as stream:
        stream.write("new draft")
    (tmp_path / "Rebuilt lesson.md").write_text("new deliverable")
    assert undo_update(lesson)["status"] == "update_undone"
    for name, data in originals.items():
        with fs.open(lesson_path(lesson, name), "rb") as stream:
            assert stream.read() == data
    assert not fs.isfile(lesson_path(lesson, "draft.json"))
    assert not (tmp_path / "Rebuilt lesson.md").exists()
    assert not has_update_snapshot(lesson)
    with pytest.raises(ValueError):
        undo_update(lesson)


def test_only_last_snapshot_and_counter_is_not_reused(tmp_path):
    lesson = str(tmp_path)
    with fs.open(lesson_path(lesson, "source_update.json"), "w") as stream:
        json.dump({"next_segment": 3, "sources": {}}, stream)
    first = snapshot_update(lesson)
    second = snapshot_update(lesson)
    assert not (tmp_path / "history" / first).exists()
    assert (tmp_path / "history" / second).exists()
    with fs.open(lesson_path(lesson, "source_update.json"), "w") as stream:
        json.dump({"next_segment": 10, "sources": {}}, stream)
    undo_update(lesson)
    with fs.open(lesson_path(lesson, "source_update.json")) as stream:
        assert json.load(stream)["next_segment"] == 10


def test_snapshot_and_restore_database_files(rt_db, tmp_path):
    lesson = fs.create_db_lesson(str(tmp_path / "virtual"))
    for name, text in {"sources.json": "[]", "info.yaml": "materia: Test\n", "draft.json": "old"}.items():
        with fs.open(lesson_path(lesson, name), "w") as stream:
            stream.write(text)
    snapshot_update(lesson)
    with fs.open(lesson_path(lesson, "draft.json"), "w") as stream:
        stream.write("new")
    undo_update(lesson)
    with fs.open(lesson_path(lesson, "draft.json")) as stream:
        assert stream.read() == "old"


def test_failed_update_leaves_snapshot_for_undo(tmp_path, monkeypatch):
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update
    from tests.test_source_update import legacy
    legacy(tmp_path)
    lesson = str(tmp_path)
    add_source(lesson, "appunti", "notes.txt", b"notes")
    before = (tmp_path / "segments.json").read_bytes()
    def fail(*args, **kwargs):
        raise RuntimeError("interrupted")
    monkeypatch.setattr("rt.pipeline.source_update.prepare_source_update", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_source_update(lesson, mock=True)
    assert has_update_snapshot(lesson)
    undo_update(lesson)
    assert (tmp_path / "segments.json").read_bytes() == before
