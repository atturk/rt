"""Prompt edits affect the actual LLM instruction and phase freshness."""

from rt.core.idempotency import compute_source_fingerprint
from rt.services.prompt_settings import append_extra, effective_system, set_extra
from tests.api_support import isolated_workspace


def test_prompt_settings_and_job_payload(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    path = "/api/v1/settings/prompts"
    before = api_client.get(path).json()
    assert before["outline"]["instruction"] == ""
    assert "segment" in before["outline"]["default"].lower()

    lesson = str(tmp_path / "lesson")
    first = compute_source_fingerprint(lesson, "outline")
    assert api_client.put(path + "/outline", json={"instruction": "Usa titoli brevi."}).status_code == 200
    assert "Usa titoli brevi." in effective_system("outline", "Istruzione base")
    assert compute_source_fingerprint(lesson, "outline") != first

    set_extra(lesson, "outline", "Metti in risalto la metodologia.")
    assert "Metti in risalto la metodologia." in append_extra(lesson, "outline", "Prompt dinamico")
    second = compute_source_fingerprint(lesson, "outline")
    assert second != first
    assert api_client.put(path + "/outline", json={"instruction": ""}).status_code == 200
    assert api_client.get(path).json()["outline"]["instruction"] == ""
    assert compute_source_fingerprint(lesson, "outline") != second
    assert api_client.put(path + "/unknown", json={"instruction": "test"}).status_code == 422
