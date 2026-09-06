"""
tests/test_llm_google_provider.py
Unit test dedicati per l'adapter Google Gemini Provider (rt.llm.providers.google):
- Formattazione endpoint REST e header Authorization con Bearer token
- Costruzione payload pulito (rimozione prefisso 'google/', supporto streaming e thinking)
- Parsing SSE streaming con chunk normalizzati
- Riconoscimento e normalizzazione di tutti i segnali di sicurezza Google:
    - promptFeedback.blockReason = "SAFETY"
    - candidates[0].finishReason = "SAFETY" / "finish_reason": "SAFETY"
    - finish_reason = "content_filter" / "BLOCKED"
- Normalizzazione risposte non-streaming
"""

import json
import pytest
from rt.llm.providers.google import GoogleProvider


def test_google_provider_endpoint_and_headers():
    provider = GoogleProvider()
    assert provider.name == "google"

    # Endpoint di default
    ep = provider.get_endpoint()
    assert ep == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    # Base URL custom
    custom_ep = provider.get_endpoint("https://custom.gemini.proxy/v1")
    assert custom_ep == "https://custom.gemini.proxy/v1/chat/completions"

    # Headers con Bearer token
    headers = provider.get_headers("AIzaSyTestKey12345")
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer AIzaSyTestKey12345"


def test_google_provider_build_payload():
    provider = GoogleProvider()

    # Modello con prefisso 'google/' da ripulire
    payload = provider.build_payload(
        model="google/gemini-2.5-flash",
        messages=[{"role": "user", "content": "Ciao"}],
        max_tokens=2048,
        temperature=0.2,
        stream=True
    )
    assert payload["model"] == "gemini-2.5-flash"
    assert payload["stream"] is True
    assert payload["max_tokens"] == 2048
    assert payload["temperature"] == 0.2
    assert len(payload["messages"]) == 1

    # Modello senza prefisso
    payload2 = provider.build_payload(
        model="gemini-2.0-flash",
        messages=[{"role": "user", "content": "Prompt"}]
    )
    assert payload2["model"] == "gemini-2.0-flash"


def test_google_provider_streaming_sse_content_and_done():
    provider = GoogleProvider()

    # Linea vuota o non data
    assert provider.parse_stream_line("") is None
    assert provider.parse_stream_line(": keep-alive") is None

    # Linea [DONE]
    assert provider.parse_stream_line("data: [DONE]") is None

    # Chunk standard con testo
    sse_line = (
        'data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "Hello world"}, '
        '"finish_reason": null}], "usage": null}'
    )
    chunk = provider.parse_stream_line(sse_line)
    assert chunk is not None
    assert chunk.content_delta == "Hello world"
    assert chunk.finish_reason is None
    assert chunk.request_id == "chatcmpl-123"


def test_google_provider_streaming_sse_prompt_feedback_safety():
    provider = GoogleProvider()

    # Gemini promptFeedback safety block
    sse_line = (
        'data: {"id": "chatcmpl-safe", "promptFeedback": {"blockReason": "SAFETY"}, '
        '"choices": []}'
    )
    chunk = provider.parse_stream_line(sse_line)
    assert chunk is not None
    assert chunk.finish_reason == "content_filter"


def test_google_provider_streaming_sse_candidate_finish_reason_safety():
    provider = GoogleProvider()

    # Case 1: finish_reason = "SAFETY"
    sse_line_1 = (
        'data: {"id": "chatcmpl-safe1", "choices": [{"delta": {}, "finish_reason": "SAFETY"}]}'
    )
    chunk1 = provider.parse_stream_line(sse_line_1)
    assert chunk1 is not None
    assert chunk1.finish_reason == "content_filter"

    # Case 2: finishReason = "BLOCKED"
    sse_line_2 = (
        'data: {"id": "chatcmpl-safe2", "choices": [{"delta": {}, "finishReason": "BLOCKED"}]}'
    )
    chunk2 = provider.parse_stream_line(sse_line_2)
    assert chunk2 is not None
    assert chunk2.finish_reason == "content_filter"

    # Case 3: finish_reason standard "stop"
    sse_line_3 = (
        'data: {"id": "chatcmpl-stop", "choices": [{"delta": {}, "finish_reason": "stop"}]}'
    )
    chunk3 = provider.parse_stream_line(sse_line_3)
    assert chunk3 is not None
    assert chunk3.finish_reason == "stop"


def test_google_provider_normalize_response_non_streaming():
    provider = GoogleProvider()

    # Risposta completa valida
    raw_success = {
        "id": "res-999",
        "choices": [
            {
                "message": {"role": "assistant", "content": '{"status": "ok"}'},
                "finish_reason": "stop"
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }
    norm = provider.normalize_response(raw_success, model_name="gemini-2.5-flash")
    assert norm.provider == "google"
    assert norm.model == "gemini-2.5-flash"
    assert norm.content == '{"status": "ok"}'
    assert norm.finish_reason == "stop"
    assert norm.usage["total_tokens"] == 15

    # Risposta con prompt feedback safety block
    raw_blocked = {
        "id": "res-block",
        "promptFeedback": {"blockReason": "SAFETY"},
        "choices": []
    }
    norm_block = provider.normalize_response(raw_blocked, model_name="gemini-2.5-flash")
    assert norm_block.finish_reason == "content_filter"

    # Risposta con candidate finishReason SAFETY
    raw_candidate_blocked = {
        "id": "res-cand-block",
        "choices": [
            {
                "message": {"content": ""},
                "finishReason": "SAFETY"
            }
        ]
    }
    norm_cand = provider.normalize_response(raw_candidate_blocked, model_name="gemini-2.5-flash")
    assert norm_cand.finish_reason == "content_filter"
