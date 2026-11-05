"""Stato di studio nel solo manifesto degli ZIP completi, con import tollerante."""
import io
import json
import zipfile

import pytest

from rt.services import study_progress_service as progress
from rt.services.lesson_import_service import import_archive
from rt.storage.export import export_zip
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def ready(tmp_path, monkeypatch, rt_db, api_client):
    path = make_lesson(isolated_workspace(tmp_path, monkeypatch))
    assert not run_mock_pipeline(path).error
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    uid = api_client.get(f"/api/v1/lessons/{lid}/study").json()["units"][0]["id"]
    progress.set_status(lid, path, uid, "appreso")
    progress.mark_read(lid, path, uid)
    return path, lid, uid


def manifest(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.endswith("/rt-export.json"))
        return json.loads(archive.read(name)), archive.namelist()


@pytest.mark.parametrize("status", ["appreso", "ignorata"])
@pytest.mark.parametrize("study", [False, True])
def test_complete_zip_roundtrip_with_and_without_study(api_client, ready, study, status):
    path, lid, uid = ready
    progress.set_status(lid, path, uid, status)
    original = progress.list_units(lid)
    data = api_client.get(f"/api/v1/lessons/{lid}/export", params={"format": "zip", "scope": "all", "study": study}).content
    description, files = manifest(data)
    assert files == manifest(export_zip(path, "all", study=not study))[1]
    assert ("study" in description) is study
    if study:
        assert description["study"][0]["unit_id"] == uid
    assert api_client.delete(f"/api/v1/lessons/{lid}").status_code == 204
    imported = import_archive(io.BytesIO(data))
    assert progress.list_units(imported) == (original if study else [])
    assert api_client.get(f"/api/v1/lessons/{imported}/study").json()["units"][0]["status"] == (status if study else "da-imparare")


def test_invalid_study_rows_are_skipped_and_dates_are_normalized(api_client, ready):
    path, lid, uid = ready
    data = export_zip(path, "all")
    payload = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(payload, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name.endswith("/rt-export.json"):
                description = json.loads(content)
                description["study"] = [
                    {"unit_id": uid, "status": "in-apprendimento", "status_at": "2026-10-06T12:00:00+02:00", "last_read_at": None},
                    {"unit_id": "99.9", "status": "appreso"},  # unità scomparsa: la riga si conserva
                    {"unit_id": "", "status": "appreso"}, {"unit_id": "x" * 65, "status": "appreso"},
                    {"unit_id": "bad", "status": 123}, {"unit_id": "bad", "status": "appreso", "status_at": "ieri"},
                    {"unit_id": "bad", "status": "appreso", "last_read_at": 7}, "errore", None,
                ]
                content = json.dumps(description).encode()
            target.writestr(name, content)
    assert api_client.delete(f"/api/v1/lessons/{lid}").status_code == 204
    imported = import_archive(io.BytesIO(payload.getvalue()))
    rows = progress.list_units(imported)
    assert [r["unit_id"] for r in rows] == [uid, "99.9"]
    assert rows[0]["status_at"].isoformat() == "2026-10-06T10:00:00+00:00"
    assert progress.summaries({imported: path})[imported]["study_learning"] == 1
    assert progress.summaries({imported: path})[imported]["study_learned"] == 0


def test_study_does_not_change_final_zip_or_markdown(api_client, ready):
    path, lid, uid = ready
    assert manifest(export_zip(path, "all", study=True))[0]["study"]
    with zipfile.ZipFile(io.BytesIO(export_zip(path, "final", study=True))) as archive:
        assert not any(n.endswith("rt-export.json") for n in archive.namelist())
    url = f"/api/v1/lessons/{lid}/export?format=markdown"
    assert api_client.get(url).content == api_client.get(url + "&study=1").content


def test_export_sources_with_multipart_audio_contains_parti_txt(tmp_path):
    from rt.core.sources import Source, SourcePart, _save
    lesson = tmp_path / "test_lesson"
    lesson.mkdir()
    (lesson / "info.yaml").write_text("file_audio: merged.m4a\n")
    (lesson / "merged.m4a").write_bytes(b"dummy-audio")
    s = Source(
        id="src_audio",
        tipo="audio",
        file="merged.m4a",
        impronta="fake-sha",
        aggiunta_il="2026-11-02T00:00:00Z",
        ordine=1,
        parti=[
            SourcePart(nome="parte 1.m4a"),
            SourcePart(nome="parte 2.m4a"),
        ],
    )
    _save(str(lesson), [s])
    zip_bytes = export_zip(str(lesson), scope="sources")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        parti_name = next(n for n in names if n.endswith("parti.txt"))
        content = zf.read(parti_name).decode("utf-8")
        assert "1. parte 1.m4a" in content
        assert "2. parte 2.m4a" in content
