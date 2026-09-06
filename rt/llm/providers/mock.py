"""
rt.llm.providers.mock
Adapter deterministico per test offline, CI e simulazione scenari di routing (timeout, 429, safety, 500, schema, auth).
"""

import json
from typing import Optional, Dict, Any, List
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk


class MockProvider(BaseLLMProvider):
    """Provider mock per test in isolamento senza chiamate HTTP."""

    def __init__(self, simulation_mode: Optional[str] = None):
        self.simulation_mode = simulation_mode  # "success" | "timeout" | "rate_limit" | "safety" | "server_error" | "auth_error" | "schema_error"

    @property
    def name(self) -> str:
        return "mock"

    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        return "http://mock-internal/chat/completions"

    def get_headers(self, api_key: str) -> Dict[str, str]:
        return {"Authorization": "Bearer mock-key"}

    def build_payload(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        thinking: bool = True,
        reasoning_effort: str = "low",
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = True,
        max_thinking_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        return {
            "model": model,
            "messages": messages,
            "stream": stream,
            "simulation_mode": self.simulation_mode
        }

    def parse_stream_line(self, line: str) -> Optional[StreamChunk]:
        clean_line = line.strip()
        if not clean_line or not clean_line.startswith("data:"):
            return None
        raw_data = clean_line[5:].strip()
        if raw_data == "[DONE]":
            return None
        try:
            d = json.loads(raw_data)
            choices = d.get("choices", [])
            delta = choices[0].get("delta", {}) if choices else {}
            return StreamChunk(
                content_delta=delta.get("content"),
                finish_reason=choices[0].get("finish_reason") if choices else None,
                usage=d.get("usage"),
                request_id=d.get("id")
            )
        except Exception:
            return None

    def normalize_response(
        self,
        raw_json: Dict[str, Any],
        model_name: str,
        request_id: Optional[str] = None
    ) -> NormalizedResponse:
        choices = raw_json.get("choices", [])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        finish_reason = choices[0].get("finish_reason") if choices else "stop"
        return NormalizedResponse(
            content=content,
            finish_reason=finish_reason,
            provider=self.name,
            model=model_name,
            request_id=request_id or "mock_req_1"
        )
