"""rt.llm.jev_client: ogni risposta anomala del modello decisionale diventa JevError, così i
chiamanti (review, rilevanza) restano fail-open; costo e telemetria si registrano sempre."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from rt.llm import jev_client as jev
from rt.llm.telemetry import TelemetryStore, use_telemetry

QUESTIONS = {
    "rilevanza": jev.JevChoiceQuestion(instructions="Classifica", criteria={"didactic": "d", "no_content": "n"}),
    "dubbio": jev.JevNoulQuestion(instructions="Quanto è incerto?"),
}
GOOD = {
    "model": "typesafe/jev-1.13",
    "answers": {
        "rilevanza": {"type": "choice", "choice": "didactic", "confidence": 0.9,
                      "probabilities": {"didactic": 0.9, "no_content": 0.1}},
        "dubbio": {"type": "noul", "noul": 0.2},
    },
    "usage": {"input_tokens": 120, "output_tokens": 3, "cost": 0.0004},
}


def _response(status=200, body=None, json_error=None):
    resp = MagicMock(status_code=status)
    if json_error:
        resp.json.side_effect = json_error
    else:
        resp.json.return_value = GOOD if body is None else body
    return resp


def _call(post, key="sk-test", **kwargs):
    store = TelemetryStore()
    with patch.object(jev.GLOBAL_CREDENTIALS, "get_api_key", return_value=key), \
            patch.object(jev.requests, "post", post), use_telemetry(store):
        try:
            return jev.call_jev("stato", QUESTIONS, job_name="test_jev", **kwargs), store
        except jev.JevError as error:
            error.store = store
            raise


def test_valid_response_is_parsed_and_costed():
    post = MagicMock(return_value=_response())
    result, store = _call(post)
    assert result.answers["rilevanza"].choice == "didactic"
    assert result.answers["dubbio"].noul == 0.2
    sent = post.call_args.kwargs
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert set(sent["json"]["questions"]) == {"rilevanza", "dubbio"}
    record = store.get_last()
    assert record.status == "success" and record.estimated_cost == 0.0004 and record.input_tokens == 120


def test_missing_credential_does_not_call_the_network():
    post = MagicMock()
    with pytest.raises(jev.JevError, match="non configurata"):
        _call(post, key=None)
    post.assert_not_called()


@pytest.mark.parametrize("post, http_status", [
    (MagicMock(return_value=_response(status=401, body={"error": "unauthorized"})), 401),
    (MagicMock(side_effect=requests.Timeout("lento")), None),
    (MagicMock(return_value=_response(json_error=ValueError("non JSON"))), 200),
])
def test_http_and_network_failures_become_jev_errors_with_telemetry(post, http_status):
    with pytest.raises(jev.JevError) as error:
        _call(post)
    record = error.value.store.get_last()
    assert record.status == "error" and record.http_status == http_status and record.error_message


def test_error_message_hides_the_api_key():
    body = {"error": "chiave sk-segreta-123 rifiutata"}
    post = MagicMock(return_value=_response(status=403, body=body))
    with patch.object(jev.GLOBAL_CREDENTIALS, "sanitize_secrets", side_effect=lambda t: t.replace("sk-segreta-123", "***")):
        with pytest.raises(jev.JevError) as error:
            _call(post)
    assert "sk-segreta-123" not in str(error.value)


def _with_answer(**changes):
    answers = {**GOOD["answers"], **changes}
    return {**GOOD, "answers": {k: v for k, v in answers.items() if v is not None}}


@pytest.mark.parametrize("body", [
    {"model": "x"},                                                          # niente answers
    _with_answer(dubbio=None),                                               # domanda senza risposta
    _with_answer(dubbio={"type": "choice", "choice": "didactic", "confidence": 0.5}),  # tipo errato
    _with_answer(rilevanza={"type": "choice", "choice": "altro", "confidence": 0.5}),  # scelta non prevista
    _with_answer(rilevanza={"type": "choice", "choice": "didactic", "confidence": 0.5,
                            "probabilities": {"didactic": 1.0}}),            # probabilità incomplete
    _with_answer(rilevanza={"type": "choice", "choice": "didactic", "confidence": 1.5}),  # fuori intervallo
    _with_answer(dubbio={"type": "noul", "noul": "tanto"}),                  # non numerico
    _with_answer(dubbio={"type": "sconosciuto"}),                            # tipo ignoto
    _with_answer(dubbio="non un oggetto"),                                   # risposta non strutturata
])
def test_malformed_answers_become_jev_errors(body):
    with pytest.raises(jev.JevError):
        _call(MagicMock(return_value=_response(body=body)))


def test_debug_log_records_the_call(tmp_path):
    with patch("rt.llm.client._append_debug_log") as log:
        _call(MagicMock(return_value=_response()), lesson_dir=str(tmp_path), unit_id="1.1")
    entry = log.call_args.args[1]
    assert entry["provider"] == "typesafe" and entry["unit_id"] == "1.1"
    assert entry["jev_answers"] == GOOD["answers"]
