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
    assert cfg["mode"] == "manual"
    cfg.update(cap_mode="fixed", cap_number=3, automatic=True)
    assert api_client.put("/api/v1/settings/enrichment", json=cfg).status_code == 200
    res = api_client.get("/api/v1/settings/enrichment").json()
    assert res["cap_number"] == 3
    assert res["mode"] == "automatic"
    cfg["cap_number"] = 0
    assert api_client.put("/api/v1/settings/enrichment", json=cfg).status_code == 422


def test_automatic_enrichment_options(tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    from rt.services.context import RunContext
    from rt.services.pipeline_service import automatic_enrichment
    ctx = RunContext()
    # Default is manual: skipped
    res = automatic_enrichment(str(tmp_path), mock=True, ctx=ctx)
    assert res.get("skipped") == "manual"
    # with_enrichment=True forces analysis even in manual mode
    res2 = automatic_enrichment(str(tmp_path), mock=True, ctx=ctx, with_enrichment=True)
    assert "skipped" not in res2

