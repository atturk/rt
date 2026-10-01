from pathlib import Path

from tests.api_support import isolated_workspace
from rt.services.settings_service import save_route, route_settings


def test_new_model_role_can_be_saved_without_existing_yaml(tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    root = Path.cwd()
    with (root / "config" / "general.yaml").open("a") as f:
        f.write("credentials:\n  - name: openrouter\n    provider: openrouter\n    env_var: OPENROUTER_API_KEY\n")
    for job in ("enrichment_writer", "enrichment_visualizer", "enrichment_image"):
        save_route(root, job, "primary", "openrouter", "openrouter", "chosen-model",
                   "https://openrouter.ai/api/v1", False)
        assert route_settings(root, job, "primary")[:3] == ("openrouter", "openrouter", "chosen-model")
        assert (root / "config" / "rt" / (job + ".yaml")).is_file()


def test_enrichment_settings_round_trip_and_cap_validation(api_client, tmp_path, monkeypatch, rt_db):
    isolated_workspace(tmp_path, monkeypatch)
    cfg = api_client.get("/api/v1/settings/enrichment").json()
    assert cfg["cap_mode"] == "proportional" and cfg["automatic"] is False
    cfg.update(cap_mode="fixed", cap_number=3, automatic=True)
    assert api_client.put("/api/v1/settings/enrichment", json=cfg).status_code == 200
    assert api_client.get("/api/v1/settings/enrichment").json()["cap_number"] == 3
    cfg["cap_number"] = 0
    assert api_client.put("/api/v1/settings/enrichment", json=cfg).status_code == 422
