"""Opt-in paid integration checks. Never run from the default suite/CI.

RT_RUN_LIVE_ENRICHMENT=1 OPENROUTER_API_KEY=... python -m pytest tests/test_enrichment_live.py -q
Only the three explicitly approved model IDs are used. No secret is persisted.
"""
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RT_RUN_LIVE_ENRICHMENT") != "1", reason="Real API tests require explicit opt-in")

TEXT_MODEL = "openai/gpt-6-luna"
IMAGE_MODEL = "inclusionai/ming-image-0.1-design"
DECISION_MODEL = "typesafe/jev-1.13"
FIXTURES = Path(__file__).parent / "fixtures" / "enrichment"


@pytest.fixture
def live_config(monkeypatch):
    from rt.core.config import RTConfig, RouteConfig, JobRoutingConfig
    from rt.services import enrichment_service
    from rt.llm import client, enrichment_media
    from rt.llm.telemetry import current_telemetry
    current_telemetry().clear()
    assert os.environ.get("OPENROUTER_API_KEY"), "Set OPENROUTER_API_KEY outside the repository"
    cfg = RTConfig(show_monitor=False, streaming=False)
    for job in ("enrichment_writer", "enrichment_visualizer", "enrichment_image"):
        cfg.jobs[job] = JobRoutingConfig(max_attempts=1, primary=RouteConfig(provider="openrouter", credential="openrouter",
            model=IMAGE_MODEL if job == "enrichment_image" else TEXT_MODEL,
            thinking=False, max_tokens=12000, timeout_seconds=240))
    cfg.enrichment.decision_model = DECISION_MODEL
    cfg.enrichment.decision_timeout = 60
    cfg.retry.max_timeout_retries = 0
    for module in (client, enrichment_service, enrichment_media):
        monkeypatch.setattr(module, "load_config", lambda *a, **k: cfg)
    import requests
    post = requests.post
    calls = {}
    def limited_post(url, **kwargs):
        model = kwargs.get("json", {}).get("model")
        assert model in {TEXT_MODEL, IMAGE_MODEL, DECISION_MODEL}, "Model not explicitly authorized"
        calls[model] = calls.get(model, 0) + 1
        assert calls[model] <= (2 if model == DECISION_MODEL else 1), "No automatic retries in live QC"
        return post(url, **kwargs)
    monkeypatch.setattr(requests, "post", limited_post)
    return cfg


def source(name):
    text = (FIXTURES / (name + ".md")).read_text()
    lines = text.splitlines()
    return {"id": lines[0].split()[1], "title": " ".join(lines[0].split()[2:]), "content": "\n".join(lines[2:]).strip()}


def output_dir():
    path = Path(os.environ.get("RT_ENRICHMENT_LIVE_OUTPUT", "/tmp/rt-enrichment-live"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize("name,mode", [("engineering", "interactive"), ("medicine", "static")])
def test_real_visualizer_is_self_contained_and_renders(live_config, tmp_path, name, mode):
    from rt.llm.client import LLMClient
    from rt.llm.enrichment_media import Visualization, VISUALIZER_SYSTEM, standalone, snapshot
    from rt.llm.telemetry import current_telemetry
    unit = source(name)
    prompt = ("Rappresenta questa singola subunità in modalità " + mode + ". " +
        ("Per la matrice evidenzia la relazione tra coefficienti e variabili. Non aggiungere termini noti o vincoli." if name == "engineering" else
         "Mostra il circuito di stimolo, mediatore, recettore e risposta, con le sole relazioni descritte.") +
        "\n\n" + unit["content"])
    visual = LLMClient().call_structured(prompt=prompt, system_prompt=VISUALIZER_SYSTEM,
        response_model=Visualization, job_name="enrichment_visualizer", unit_id=unit["id"], lesson_dir=str(tmp_path), stream=False, max_retries=0)
    html = standalone(visual.body)
    (output_dir() / (name + ".html")).write_text(html)
    png = snapshot(html)
    (output_dir() / (name + ".png")).write_bytes(png)
    assert len(png) > 5000
    assert "connect-src 'none'" in html
    assert any(marker in html.lower() for marker in ("<svg", "<canvas", "<table", "display:grid", "display: grid"))
    records = [r.model_dump(exclude_none=True) for r in current_telemetry().get_all()]
    (output_dir() / (name + "-telemetry.json")).write_text(json.dumps(records, indent=2))


def test_real_infographic_images_api(live_config, tmp_path):
    from rt.llm.enrichment_media import generate_image
    unit = source("medicine")
    png = generate_image("Crea una semplice infografica didattica in italiano. Usa solo la fonte seguente, non inventare dati. "
        "Rappresenta il percorso sintetico descritto senza aggiungere nomi clinici.\n\n" + unit["content"], str(tmp_path))
    (output_dir() / "infographic.png").write_bytes(png)
    assert png.startswith(b"\x89PNG") and len(png) > 5000


def test_real_jev_utility_and_unique_macro_choice(live_config, tmp_path):
    from rt.services.enrichment_service import decision, UTILITY
    from rt.llm.jev_client import JevChoiceQuestion, JevNoulQuestion, JevNoulAnswer, JevChoiceAnswer
    engineering, medicine = source("engineering"), source("medicine")
    assessment = decision(engineering["content"], {k: JevNoulQuestion(instructions=v) for k, v in UTILITY.items()},
        lesson_dir=str(tmp_path), job_name="enrichment_decision", unit_id=engineering["id"])
    assert all(isinstance(assessment.answers[k], JevNoulAnswer) for k in UTILITY)
    response = decision("[macro_0] Algebra\n" + engineering["content"] + "\n[macro_1] Medicina\n" + medicine["content"] +
        "\nDescrizione immagine: matrice A con righe di vincoli e colonne di variabili decisionali.", {
        "placement": JevChoiceQuestion(instructions="Scegli l'unica macro unità pertinente per l'immagine.",
            criteria={"macro_0": "Algebra e matrici", "macro_1": "Diagrammi e percorso fisiologico astratto", "none": "Nessuna"})},
        lesson_dir=str(tmp_path), job_name="image_unit_judge")
    assert isinstance(response.answers["placement"], JevChoiceAnswer)
    assert response.answers["placement"].choice == "macro_0"
    (output_dir() / "decisions.json").write_text(json.dumps({"utility": assessment.model_dump(), "placement": response.model_dump()}, indent=2))
