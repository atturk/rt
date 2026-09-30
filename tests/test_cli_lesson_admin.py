"""
tests/test_cli_lesson_admin.py
Parità CLI ↔ web per eliminazione e import ZIP delle lezioni (docs/RT4_PARITY.md): 'rt delete'
e 'rt import' chiamano gli stessi servizi di DELETE /lessons/{id} e POST /lessons/import-zip.
"""
import os

import pytest

from rt.cli import main
from rt.db.models import Lesson
from rt.db.session import session_scope
from rt.storage.export import export_zip
from tests.api_support import isolated_workspace, make_lesson


@pytest.fixture
def workspace(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def _lesson_ids(rt_db):
    with session_scope(rt_db) as session:
        return {row.path: row.id for row in session.query(Lesson)}


def test_delete_asks_confirmation_and_removes_like_the_api(workspace, rt_db, monkeypatch, capsys):
    path = make_lesson(workspace)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    main(["delete", path])
    assert os.path.isdir(path) and "annullata" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda _prompt: "s")
    main(["delete", os.path.basename(path)])  # anche per nome sotto lessons_root
    assert not os.path.exists(path)
    assert _lesson_ids(rt_db) == {}


def test_delete_with_yes_by_id_and_errors(workspace, rt_db, api_client, capsys):
    path = make_lesson(workspace)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    job = api_client.post(f"/api/v1/lessons/{lesson_id}/jobs", json={"type": "run_phase", "phase": "prepare"})
    with pytest.raises(SystemExit) as exit_info:
        main(["delete", str(lesson_id), "--yes"])
    assert exit_info.value.code == 1
    assert "job ancora attivi" in capsys.readouterr().err  # stesso rifiuto dell'API (409 lesson_busy)
    assert os.path.isdir(path)
    api_client.post(f"/api/v1/jobs/{job.json()['job_id']}/cancel")
    main(["delete", str(lesson_id), "--yes"])
    assert not os.path.exists(path)
    assert api_client.get(f"/api/v1/lessons/{lesson_id}").status_code == 404
    with pytest.raises(SystemExit):
        main(["delete", "inesistente", "--yes"])
    assert "Lezione non trovata" in capsys.readouterr().err


def test_import_matches_api_and_reports_rejected_archives(workspace, rt_db, api_client, tmp_path, capsys):
    lesson = make_lesson(workspace)
    archive = tmp_path / "lezione.zip"
    archive.write_bytes(export_zip(lesson, scope="all"))
    corrupt = tmp_path / "rotto.zip"
    corrupt.write_bytes(b"not a zip")
    os.rename(lesson, lesson + "-fuori")

    with pytest.raises(SystemExit) as exit_info:
        main(["import", str(archive), str(corrupt), str(archive)])
    assert exit_info.value.code == 1  # almeno un archivio rifiutato
    out, err = capsys.readouterr()
    assert "lezione.zip: importata come" in out
    assert "rotto.zip: Archivio ZIP non valido." in err
    assert "esiste già." in err  # il secondo import della stessa lezione, come nell'API
    imported = [item for item in api_client.get("/api/v1/lessons").json()
                if item["folder_name"] == os.path.basename(lesson)]
    assert len(imported) == 1
    assert api_client.get(f"/api/v1/lessons/{imported[0]['id']}").status_code == 200
