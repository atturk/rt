import hashlib

import pytest

from rt.core.sources import add_source, load_sources, remove_source


def test_legacy_registry_is_lazy_and_preserves_files(tmp_path):
    info = tmp_path / "info.yaml"
    info.write_text("file_audio: lezione.wav\n", encoding="utf-8")
    audio = tmp_path / "lezione.wav"
    audio.write_bytes(b"original audio")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    sources = load_sources(str(tmp_path))
    assert sources[0].id == "src_000001"
    assert sources[0].impronta == hashlib.sha256(audio.read_bytes()).hexdigest()
    assert sources == load_sources(str(tmp_path))
    assert all((tmp_path / name).read_bytes() == data for name, data in before.items())


def test_add_remove_are_ordered_and_never_overwrite_sources(tmp_path):
    (tmp_path / "info.yaml").write_text("file_audio: original.wav\n")
    (tmp_path / "original.wav").write_bytes(b"original")
    first = add_source(str(tmp_path), "appunti", "note.txt", b"first", ordine=1)
    second = add_source(str(tmp_path), "appunti", "note.txt", b"second")
    assert [s.id for s in load_sources(str(tmp_path))] == [first.id, "src_000001", second.id]
    remove_source(str(tmp_path), first.id)
    assert (tmp_path / first.file).read_bytes() == b"first"
    assert (tmp_path / second.file).read_bytes() == b"second"
    assert (tmp_path / "original.wav").read_bytes() == b"original"
    assert [s.ordine for s in load_sources(str(tmp_path))] == [1, 2]
    with pytest.raises(KeyError):
        remove_source(str(tmp_path), "missing")


def test_source_registry_in_database(rt_db, tmp_path):
    from rt.db.models import Lesson
    from rt.db.session import session_scope
    from rt.storage import fs
    lesson = str(tmp_path / "virtual")
    with session_scope(rt_db) as session:
        session.add(Lesson(path=lesson, folder_name="virtual", storage="db", materia="Test", data="2026-10-12"))
    with fs.open(lesson + "/info.yaml", "w") as stream:
        stream.write("materia: Test\n")
    assert load_sources(lesson) == []
    source = add_source(lesson, "appunti", "note.txt", b"test")
    assert load_sources(lesson) == [source]
    with fs.open(lesson + "/" + source.file, "rb") as stream:
        assert stream.read() == b"test"
