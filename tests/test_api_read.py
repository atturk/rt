"""
tests/test_api_read.py
RT4-E2: endpoint di lettura (lezioni, fasi, documento, audio, outline, issue, costi).
"""
import os

import pytest

from tests.api_support import add_audio, isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    result = run_mock_pipeline(lesson_dir, auto_accept=False)
    assert result.status.value == "waiting_for_decision"  # outline da approvare
    return lesson_dir


def _only_lesson(client):
    items = client.get("/api/v1/lessons").json()
    assert len(items) == 1
    return items[0]


def test_list_and_filters(api_client, lesson):
    item = _only_lesson(api_client)
    assert item["materia"] == "BIOCHIMICA" and item["phases"]["outline"] == "VALID"
    assert api_client.get("/api/v1/lessons", params={"materia": "biochimica"}).json()
    assert api_client.get("/api/v1/lessons", params={"materia": "FISICA"}).json() == []
    assert api_client.get("/api/v1/lessons", params={"q": "lipidi"}).json()
    assert api_client.get("/api/v1/lessons", params={"q": "zzz"}).json() == []


def test_lesson_id_is_stable(api_client, lesson):
    first = _only_lesson(api_client)["id"]
    assert _only_lesson(api_client)["id"] == first


def test_detail_matches_cli_status(api_client, lesson):
    from rt.core.idempotency import check_phase_status
    lesson_id = _only_lesson(api_client)["id"]
    detail = api_client.get(f"/api/v1/lessons/{lesson_id}").json()
    for row in detail["phase_report"]:
        status, reason = check_phase_status(lesson, row["phase"])
        assert (row["status"], row["reason"]) == (status.value, reason)
    assert detail["outline_approved"] is False
    assert api_client.get("/api/v1/lessons/9999").status_code == 404


def test_phases_include_validation_reports(api_client, lesson):
    lesson_id = _only_lesson(api_client)["id"]
    report = api_client.get(f"/api/v1/lessons/{lesson_id}/phases").json()
    assert report["outline_validation"]["valid"] is True
    assert report["draft_validation"] is None  # rewrite non ancora eseguito


def test_outline_tree(api_client, lesson):
    lesson_id = _only_lesson(api_client)["id"]
    outline = api_client.get(f"/api/v1/lessons/{lesson_id}/outline").json()
    assert outline["approved"] is False and outline["macro_sections"][0]["units"]


def test_document_issues_and_costs_after_full_run(api_client, lesson):
    from rt.services.outline_service import approve_outline
    approve_outline(lesson, channel="api")
    assert run_mock_pipeline(lesson, auto_accept=True).status.value == "completed"
    lesson_id = _only_lesson(api_client)["id"]

    doc = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()
    assert doc["final"] is True and doc["markdown"].strip()
    assert doc["sections"] and doc["sections"][0]["start_seconds"] is not None

    issues = api_client.get(f"/api/v1/lessons/{lesson_id}/issues", params={"status": "all"}).json()
    assert issues["pending"] == 0 and issues["review_complete"] is True
    assert all(item["decision"] for item in issues["items"])
    decisions = api_client.get(f"/api/v1/lessons/{lesson_id}/decisions").json()
    assert len(decisions) == issues["total"]

    costs = api_client.get("/api/v1/costs").json()
    assert costs["total_calls"] >= 1 and costs["lessons"][0]["id"] == lesson_id


def test_document_html_escapes_raw_html(api_client, lesson):
    from rt.core.lesson_paths import lesson_path
    with open(lesson_path(lesson, "rielaborato.md"), "w", encoding="utf-8") as f:
        f.write("# Titolo\n\n<script>alert(1)</script>\n")
    lesson_id = _only_lesson(api_client)["id"]
    html = api_client.get(f"/api/v1/lessons/{lesson_id}/document").json()["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_audio_with_range(api_client, lesson):
    lesson_id = _only_lesson(api_client)["id"]
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/audio").status_code == 404
    path = add_audio(lesson)
    full = api_client.get(f"/api/v1/lessons/{lesson_id}/audio")
    assert full.status_code == 200 and len(full.content) == os.path.getsize(path)
    part = api_client.get(f"/api/v1/lessons/{lesson_id}/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100


def test_audio_path_traversal_refused(api_client, lesson, tmp_path):
    """info.yaml e manifest puntano fuori dalla cartella o a file non audio: niente da servire."""
    secret = tmp_path / "secret.m4a"
    secret.write_bytes(b"segreto")
    (tmp_path / "work" / ".env").write_text("RT_X=segreto\n", encoding="utf-8")
    info = os.path.join(lesson, "info.yaml")
    text = open(info, encoding="utf-8").read()
    lesson_id = _only_lesson(api_client)["id"]
    for target in ("../../secret.m4a", str(secret), "../../work/.env", "info.yaml"):
        with open(info, "w", encoding="utf-8") as f:
            f.write(text.replace("file_audio: lezione.m4a", f"file_audio: {target!r}"))
        res = api_client.get(f"/api/v1/lessons/{lesson_id}/audio")
        assert res.status_code == 404, target
    # un link simbolico dentro la cartella che punta fuori non vale
    os.symlink(secret, os.path.join(lesson, "link.m4a"))
    with open(info, "w", encoding="utf-8") as f:
        f.write(text.replace("file_audio: lezione.m4a", "file_audio: link.m4a"))
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/audio").status_code == 404
    # e un percorso nell'URL non è un id
    assert api_client.get("/api/v1/lessons/..%2F..%2Fetc/audio").status_code in (404, 422)


def test_read_endpoints_need_auth(api_client, lesson):
    from fastapi.testclient import TestClient
    from rt.api.app import create_app
    anon = TestClient(create_app())
    for path in ("/api/v1/lessons", "/api/v1/costs"):
        assert anon.get(path).status_code == 401


def test_response_schemas_in_openapi(api_client):
    schema = api_client.get("/openapi.json").json()
    for path in ("/api/v1/lessons", "/api/v1/lessons/{lesson_id}", "/api/v1/lessons/{lesson_id}/document",
                 "/api/v1/lessons/{lesson_id}/issues", "/api/v1/costs"):
        content = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]
        assert "schema" in content and content["schema"]


def test_lesson_id_survives_build_rename(api_client, lesson):
    from rt.services.context import RunContext
    from rt.services.outline_service import approve_outline
    from rt.services.pipeline_service import PipelineOptions, run_pipeline
    lesson_id = _only_lesson(api_client)["id"]
    approve_outline(lesson, channel="api")
    result = run_pipeline([lesson], PipelineOptions(mock=True, with_review=True, auto_accept=True,
                                                    rename=True, channel="terminal"), RunContext())
    assert result.status.value == "completed" and result.lesson_dir != lesson
    item = _only_lesson(api_client)
    assert item["id"] == lesson_id and item["path"] == os.path.realpath(result.lesson_dir)
