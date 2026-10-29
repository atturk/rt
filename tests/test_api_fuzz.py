"""
tests/test_api_fuzz.py
Fuzzing dell'API dallo schema OpenAPI (Schemathesis): per ogni endpoint genera richieste
valide e al limite (stringhe strane, numeri enormi, campi mancanti) e controlla che l'API
risponda con un errore gestito (4xx, o 502/503 per un servizio esterno irraggiungibile) e
mai con un 500, cioè un'eccezione non prevista.

L'API gira in processo su un DB e una cartella lezioni temporanei, con una lezione di prova
già elaborata in mock. Restano fuori gli endpoint che toccano il sistema (chiudere l'app,
installare aggiornamenti, aprire la finestra di scelta della cartella); la rete esterna è
bloccata, così nessuna richiesta generata raggiunge Telegram o i provider.

In CI gli esempi sono fissi (derandomize), così una PR non fallisce a caso. Per una ricerca più
ampia e casuale: RT_FUZZ_EXAMPLES=200 python -m pytest tests/test_api_fuzz.py
"""
import os

import pytest
import schemathesis
from hypothesis import HealthCheck, settings

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from tests.offline_network import block_external_network  # noqa: F401 (fixture autouse)

# Effetti fuori dall'API: processo, finestre native, rete verso GitHub.
EXCLUDED = [
    ("POST", "/api/v1/system/quit"),
    ("POST", "/api/v1/system/update"),
    ("POST", "/api/v1/system/update/install"),
    ("POST", "/api/v1/system/choose-folder"),
]


@pytest.fixture
def fuzz_app(tmp_path, monkeypatch, rt_db, api_token):
    root = isolated_workspace(tmp_path, monkeypatch)
    run_mock_pipeline(make_lesson(root), auto_accept=False)
    from rt.api.app import create_app
    return create_app(), api_token


@pytest.fixture
def api_schema(fuzz_app):
    app, token = fuzz_app
    schema = schemathesis.openapi.from_asgi("/openapi.json", app)
    for method, path in EXCLUDED:
        schema = schema.exclude(method=method, path=path)
    schema.config.headers = {"Authorization": f"Bearer {token}"}
    return schema


schema = schemathesis.pytest.from_fixture("api_schema")


def no_unexpected_error(ctx, response, case):
    """Solo il 500 è un'eccezione sfuggita: 502 e 503 sono errori gestiti di servizi esterni."""
    if response.status_code == 500:
        raise AssertionError(f"500 da {case.method} {case.path}: {response.text[:300]}")


@schema.parametrize()
@settings(max_examples=int(os.environ.get("RT_FUZZ_EXAMPLES", 20)), derandomize="RT_FUZZ_EXAMPLES" not in os.environ,
          deadline=None, suppress_health_check=list(HealthCheck))
def test_api_never_returns_500(case):
    case.call_and_validate(checks=[no_unexpected_error])


# Casi trovati dal fuzzing, fissati come regressioni deterministiche.

@pytest.fixture
def client(fuzz_app):
    from fastapi.testclient import TestClient
    app, token = fuzz_app
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_id_beyond_64_bits_is_a_bad_request(client):
    huge = 2 ** 63
    assert client.get(f"/api/v1/lessons/{huge}").status_code == 422
    assert client.get("/api/v1/jobs", params={"lesson_id": huge}).status_code == 422
    assert client.post("/api/v1/lessons/batch/pipeline", json={"lesson_ids": [huge], "mode": "run"}).status_code == 422


def test_missing_lesson_is_404_outside_the_lesson_routes(client):
    response = client.get("/api/v1/recall/types", params={"lesson_id": 999})
    assert response.status_code == 404 and response.json()["error"]["code"] == "lesson_not_found"


def test_empty_subject_is_a_validation_error(client):
    assert client.get("/api/v1/recall/types", params={"materia": ""}).status_code == 422
    assert client.post("/api/v1/recall/subject/next", params={"materia": ""}).status_code == 422


def test_decision_model_rejects_instructions_the_classifier_cannot_use(client):
    """Nel prefiltro 'score' le istruzioni aggiuntive vanno in un livello (max 4000 caratteri):
    salvarne di più lunghe rompeva il classificatore a ogni lezione."""
    body = client.get("/api/v1/settings/decision-model").json()
    body.update(prefilter_type="score", prefilter_prompt="x" * 5000)
    response = client.put("/api/v1/settings/decision-model", json=body)
    assert response.status_code == 422
    body.update(prefilter_prompt="Considera grave anche un'unità di misura sbagliata.")
    assert client.put("/api/v1/settings/decision-model", json=body).status_code == 200


def test_event_stream_rejects_an_id_beyond_64_bits(client):
    assert client.get("/api/v1/events", params={"after": 2 ** 63}).status_code == 422
    assert client.get("/api/v1/events", headers={"Last-Event-ID": str(2 ** 63)}).status_code == 422
