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


def test_failed_update_restores_lesson_and_keeps_sources_pending(tmp_path, monkeypatch):
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update, sources_pending
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
    assert (tmp_path / "segments.json").read_bytes() == before
    assert sources_pending(lesson)
    # Nessun aggiornamento riuscito: niente da annullare e nessuna fotografia lasciata.
    assert not has_update_snapshot(lesson)
    assert not (tmp_path / "history").exists() or not list((tmp_path / "history").iterdir())


LESSON_FILES = ("segments.json", "outline.json", "info.yaml", "draft.json", "sources.json", "manifest.json")


def _files(tmp_path):
    return {name: (tmp_path / name).read_bytes() if (tmp_path / name).exists() else None for name in LESSON_FILES}


@pytest.fixture
def extended_twice(tmp_path, monkeypatch):
    """Lezione storica + appunti A aggiornata, poi appunti B aggiornata."""
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update
    from tests.test_source_update import legacy
    monkeypatch.setattr("rt.services.classifier.classify_units", lambda *a, **k: None)
    legacy(tmp_path)
    lesson = str(tmp_path)
    run_source_update(lesson, mode="rebuild", mock=True)
    add_source(lesson, "appunti", "a.txt", b"notes A")
    run_source_update(lesson, mock=True)
    after_a = _files(tmp_path)
    b = add_source(lesson, "appunti", "b.txt", b"notes B")
    run_source_update(lesson, mock=True)
    return lesson, b, after_a


def test_estendi_rejected_before_writing_when_removed_source_empties_unit(tmp_path, extended_twice):
    from rt.core.sources import remove_source
    from rt.core.segments import load_segments_json
    from rt.pipeline.source_update import run_source_update, sources_pending
    from rt.pipeline.validator import ValidationError
    lesson, b, after_a = extended_twice
    remove_source(lesson, b.id)
    before = _files(tmp_path)
    pointer = (tmp_path / "update_snapshot.json").read_bytes()
    import rt.pipeline.source_update as source_update
    prepare = source_update.prepare_source_update
    def must_not_prepare(*args, **kwargs):
        raise AssertionError("Estendi impossibile: niente da preparare")
    source_update.prepare_source_update = must_not_prepare
    try:
        with pytest.raises(ValidationError, match="svuota"):
            run_source_update(lesson, mock=True)
    finally:
        source_update.prepare_source_update = prepare
    assert _files(tmp_path) == before
    assert (tmp_path / "update_snapshot.json").read_bytes() == pointer
    assert sources_pending(lesson)
    # Ricostruisci invece riesce e usa le fonti in attesa.
    result = run_source_update(lesson, mode="rebuild", mock=True)
    assert result["status"] == "draft_validated"
    assert all("notes B" != s.text_raw for s in load_segments_json(str(tmp_path / "segments.json")).segments)
    assert not sources_pending(lesson)


def test_failure_after_writing_restores_everything_and_retry_sees_new_units(tmp_path, extended_twice, monkeypatch):
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update, sources_pending
    lesson, _b, after_a = extended_twice
    add_source(lesson, "appunti", "c.txt", b"notes C")
    before = _files(tmp_path)
    pointer = (tmp_path / "update_snapshot.json").read_bytes()
    import rt.pipeline.outline_extension as extension
    real = extension.extend_outline
    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("outline non valida")
    monkeypatch.setattr(extension, "extend_outline", fail)
    with pytest.raises(RuntimeError, match="outline non valida"):
        run_source_update(lesson, mock=True)
    assert _files(tmp_path) == before
    assert (tmp_path / "update_snapshot.json").read_bytes() == pointer
    assert sources_pending(lesson)
    monkeypatch.setattr(extension, "extend_outline", real)
    result = run_source_update(lesson, mock=True)
    assert result["status"] == "draft_validated" and result["changed_units"]
    assert not sources_pending(lesson)
    # Annulla toglie l'ultimo aggiornamento riuscito (C), non quelli precedenti.
    undo_update(lesson)
    assert _files(tmp_path)["segments.json"] == before["segments.json"]


def test_failed_attempt_keeps_previous_update_undoable(tmp_path, extended_twice, monkeypatch):
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update
    lesson, _b, after_a = extended_twice
    add_source(lesson, "appunti", "c.txt", b"notes C")
    def fail(*args, **kwargs):
        raise RuntimeError("rewrite interrotto")
    monkeypatch.setattr("rt.pipeline.rewrite.run_rewrite", fail)
    with pytest.raises(RuntimeError):
        run_source_update(lesson, mock=True)
    # Annulla annulla ancora l'aggiornamento con B, riuscito prima del tentativo fallito.
    undo_update(lesson)
    restored = _files(tmp_path)
    for name in ("segments.json", "outline.json", "draft.json"):
        assert restored[name] == after_a[name]
    assert [p.name for p in (tmp_path / "history").iterdir()] == []


def test_failed_units_restore_the_lesson(tmp_path, extended_twice, monkeypatch):
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update
    lesson, _b, _after_a = extended_twice
    add_source(lesson, "appunti", "c.txt", b"notes C")
    before = _files(tmp_path)
    monkeypatch.setattr("rt.pipeline.rewrite.run_rewrite", lambda *a, **k: {
        "status": "draft_partial", "failed_units": [{"unit_id": "x"}]})
    with pytest.raises(RuntimeError, match="incompleto"):
        run_source_update(lesson, mock=True)
    assert _files(tmp_path) == before
