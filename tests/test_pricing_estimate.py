import pytest
from rt.llm.pricing import (
    estimate_lesson_cost,
    format_cost_estimate,
    estimate_configured_lesson_cost,
    TYPICAL_LESSON_INPUT_TOKENS,
    TYPICAL_LESSON_OUTPUT_TOKENS,
)


def test_estimate_lesson_cost_known_models():
    # deepseek-chat
    cost_ds = estimate_lesson_cost("deepseek", "deepseek-chat")
    assert cost_ds is not None
    assert cost_ds > 0

    # google gemini-flash
    cost_gemini = estimate_lesson_cost("google", "gemini-2.5-flash")
    assert cost_gemini is not None
    assert cost_gemini > 0

    # ollama o modello locale: costo zero
    assert estimate_lesson_cost("ollama", "llama3") == 0.0
    assert estimate_lesson_cost("local", "whisper") == 0.0

    # Modello sconosciuto
    assert estimate_lesson_cost("unknown-prov", "unknown-mod") is None


def test_format_cost_estimate():
    assert format_cost_estimate(None) == "stima non disponibile"
    assert format_cost_estimate(0.0) == "circa 0,00 € a lezione (stima)"
    assert format_cost_estimate(0.15) == "circa 0,15 € a lezione (stima)"


def test_api_cost_estimate(api_client):
    # Con parametri query espliciti
    res = api_client.get("/api/v1/settings/estimate?provider=google&model=gemini-2.5-flash")
    assert res.status_code == 200
    data = res.json()
    assert "cost_eur" in data
    assert data["cost_eur"] is not None
    assert "circa" in data["formatted"]

    # Con modello sconosciuto
    res_unk = api_client.get("/api/v1/settings/estimate?provider=unknown&model=unknown")
    assert res_unk.status_code == 200
    assert res_unk.json()["formatted"] == "stima non disponibile"


def test_api_import_sample_lesson(api_client, tmp_path, monkeypatch, rt_db):
    res = api_client.post("/api/v1/lessons/sample")
    assert res.status_code == 201
    data = res.json()
    assert data["materia"] == "ESEMPIO"
    assert data["titolo"] == "Introduzione a RT"
    assert isinstance(data["lesson_id"], int)

    # La lezione compare nell'elenco
    list_res = api_client.get("/api/v1/lessons")
    assert list_res.status_code == 200
    lessons = list_res.json()
    assert any(l["id"] == data["lesson_id"] for l in lessons)
