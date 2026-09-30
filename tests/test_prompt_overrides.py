"""Prompt edits affect the actual LLM instruction, but not the freshness of phases already done."""

from rt.core.idempotency import compute_source_fingerprint
from rt.services.prompt_settings import append_extra, effective_system, extra_for, one_shot_extra, set_extra
from tests.api_support import isolated_workspace


def test_prompt_settings_do_not_invalidate_completed_phases(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    path = "/api/v1/settings/prompts"
    before = api_client.get(path).json()
    assert before["outline"]["instruction"] == ""
    assert "segment" in before["outline"]["default"].lower()

    lesson = str(tmp_path / "lesson")
    first = {phase: compute_source_fingerprint(lesson, phase) for phase in ("outline", "rewrite", "review")}
    assert api_client.put(path + "/outline", json={"instruction": "Usa titoli brevi."}).status_code == 200
    assert "Usa titoli brevi." in effective_system("outline", "Istruzione base")
    set_extra(lesson, "rewrite", "Metti in risalto la metodologia.")
    assert "Metti in risalto la metodologia." in append_extra(lesson, "rewrite", "Prompt dinamico")
    # Cambiare prompt o istruzioni non rende STALE le fasi già fatte (report 2, §5.3).
    assert {phase: compute_source_fingerprint(lesson, phase) for phase in first} == first

    assert api_client.put(path + "/outline", json={"instruction": ""}).status_code == 200
    assert api_client.get(path).json()["outline"]["instruction"] == ""
    assert api_client.put(path + "/unknown", json={"instruction": "test"}).status_code == 422


def test_extra_prompt_lasts_only_for_one_run(rt_db, tmp_path):
    lesson = str(tmp_path / "lesson")
    try:
        with one_shot_extra(lesson, "review", "Controlla le unità di misura."):
            assert extra_for(lesson, "review") == "Controlla le unità di misura."
            raise RuntimeError("job fallito")
    except RuntimeError:
        pass
    assert extra_for(lesson, "review") == ""
