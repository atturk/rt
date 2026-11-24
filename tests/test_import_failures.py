"""Import che si ferma a metà: niente lezioni vuote che restano, calendario collegato lo stesso,
audio con appunti accettati, ispezione dei file con i limiti degli altri upload."""
import os

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace
from tests.test_material_import import wav_bytes
from tests.test_materials import pdf_bytes


def _boom(*_args, **_kwargs):
    raise OSError("disco pieno")


def test_source_lesson_is_removed_when_adding_sources_fails(rt_db, tmp_path, monkeypatch):
    from rt.services import materials_lesson_service
    from rt.services.materials_lesson_service import create_source_lesson
    root = isolated_workspace(tmp_path, monkeypatch)
    material = tmp_path / "slide.pdf"
    material.write_bytes(pdf_bytes("TESTO"))
    args = dict(audio=[], materiali=[str(material)], date="2026-10-12", materia="Test", ora="09:00", dest_dir=root)
    with monkeypatch.context() as patch:
        patch.setattr(materials_lesson_service, "add_source", _boom)
        with pytest.raises(OSError):
            create_source_lesson(**args)
    from rt.services.lesson_service import known_lesson_dirs
    assert known_lesson_dirs() == []
    # Il nuovo tentativo riprende lo stesso nome: niente "Esiste già una lezione".
    lesson = create_source_lesson(**args)
    assert os.path.basename(lesson) == "[2026-10-12] TEST - ore 09.00"


def test_notes_lesson_is_removed_when_adding_notes_fails(rt_db, tmp_path, monkeypatch):
    from rt.services import notes_lesson_service
    from rt.services.notes_lesson_service import create_notes_lesson
    root = isolated_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(notes_lesson_service, "add_source", _boom)
    with pytest.raises(OSError):
        create_notes_lesson("Testo", date="2026-10-12", materia="Test", ora="09:00", dest_dir=root)
    from rt.services.lesson_service import known_lesson_dirs
    assert known_lesson_dirs() == []


def test_link_after_failure_links_the_created_lesson_and_reraises(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from rt.services import materials_lesson_service
    from rt.services.materials_lesson_service import link_after_failure
    linked = []
    monkeypatch.setattr(materials_lesson_service, "link_imported_lesson", lambda *a: linked.append(a))
    payload = {"calendar_entry_id": "tpl_1", "calendar_date": "2026-10-12"}
    ctx = SimpleNamespace(lesson_dir=str(tmp_path))
    with pytest.raises(RuntimeError):
        with link_after_failure(ctx, payload):
            raise RuntimeError("trascrizione fallita")
    assert linked == [(str(tmp_path), "tpl_1", "2026-10-12", None, None)]
    # Prima che la lezione esista non c'è niente da collegare.
    with pytest.raises(RuntimeError):
        with link_after_failure(SimpleNamespace(lesson_dir=None), payload):
            raise RuntimeError("setup fallito")
    assert len(linked) == 1


def test_setup_tells_the_job_which_lesson_it_created(tmp_path):
    from rt.services.context import RunContext
    from rt.services.pipeline_service import _lesson_created
    ctx = RunContext()
    _lesson_created(ctx, str(tmp_path))
    assert ctx.lesson_dir == str(tmp_path)


def test_audio_with_notes_is_accepted_as_mixed_sources(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    response = api_client.post("/api/v1/lessons", data={"date": "2026-10-12", "materia": "Test", "appunti": "Note",
                               "mock": "true"}, files=[("audio", ("lezione.wav", wav_bytes(), "audio/wav"))])
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "ingest_sources"


def test_inspect_rejects_nameless_and_oversized_files(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    nameless = api_client.post("/api/v1/archive/inspect", files=[("file", ("", b"%PDF", "application/pdf"))])
    assert nameless.status_code in (415, 422), nameless.text
    monkeypatch.setenv("RT_API_MAX_UPLOAD_MB", "0.0001")
    big = api_client.post("/api/v1/archive/inspect", files=[("file", ("slide.pdf", b"x" * 1000, "application/pdf"))])
    assert big.status_code == 413, big.text
    monkeypatch.delenv("RT_API_MAX_UPLOAD_MB")
    ok = api_client.post("/api/v1/archive/inspect", files=[("file", ("slide.pdf", pdf_bytes("A"), "application/pdf"))])
    assert ok.status_code == 200 and ok.json()["pagine_totali"] == 1


def test_failed_import_job_leaves_no_empty_lesson_in_list(api_client, rt_db, tmp_path, monkeypatch):
    """Un import (fonti/appunti/zip) che fallisce subito non lascia righe vuote in elenco né cancella cartelle con file."""
    from rt.services import materials_lesson_service, notes_lesson_service
    from rt.services.lesson_import_service import import_archive
    from rt.services.lesson_service import list_lessons
    from rt.storage import fs
    from rt.storage.export import export_zip
    from tests.api_support import make_lesson

    root = isolated_workspace(tmp_path, monkeypatch)

    # 1. Import fonti fallisce subito via job ingest_sources
    monkeypatch.setattr(materials_lesson_service, "add_source", _boom)
    resp = api_client.post(
        "/api/v1/lessons",
        data={"date": "2026-10-12", "materia": "Test", "mock": "true"},
        files=[("materiali", ("slide.pdf", pdf_bytes("TESTO"), "application/pdf"))],
    )
    assert resp.status_code == 202
    job = Worker(DbJobQueue(rt_db), job_types=["ingest_sources"], on_message=lambda *_: None).run_once()
    assert job.state == "failed"
    assert list_lessons() == []
    assert api_client.get("/api/v1/lessons").json() == []

    # 2. Import appunti fallisce subito via job ingest_notes
    monkeypatch.setattr(notes_lesson_service, "add_source", _boom)
    resp2 = api_client.post(
        "/api/v1/lessons",
        data={"date": "2026-10-12", "materia": "Appunti", "appunti": "Note di prova", "mock": "true"},
    )
    assert resp2.status_code == 202
    job2 = Worker(DbJobQueue(rt_db), job_types=["ingest_notes"], on_message=lambda *_: None).run_once()
    assert job2.state == "failed"
    assert list_lessons() == []

    # 3. Import ZIP fallisce durante la copia dei file -> nessuna lezione nuova
    existing = make_lesson(root)
    archive = tmp_path / "export.zip"
    archive.write_bytes(export_zip(existing, scope="all"))
    from rt.services import lesson_delete_service
    from rt.services.lesson_service import lesson_id_for_dir
    lesson_delete_service.delete_lesson(lesson_id_for_dir(existing), existing)
    assert list_lessons() == []

    monkeypatch.setattr(fs, "copy2", _boom)
    with pytest.raises(OSError):
        import_archive(str(archive))
    assert list_lessons() == []

    # 4. discard_new_lesson non cancella mai una cartella che contiene file
    non_empty = tmp_path / "non_empty_folder"
    non_empty.mkdir()
    keep_file = non_empty / "keep.txt"
    keep_file.write_text("non toccare")
    materials_lesson_service.discard_new_lesson(str(non_empty))
    assert non_empty.is_dir() and keep_file.read_text() == "non toccare"

    # Ma rimuove una cartella vuota
    empty_dir = tmp_path / "empty_folder"
    empty_dir.mkdir()
    materials_lesson_service.discard_new_lesson(str(empty_dir))
    assert not empty_dir.exists()
