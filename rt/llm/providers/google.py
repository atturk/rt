"""
rt.llm.providers.google
Adapter per Google Gemini API (endpoint REST OpenAI-compatible /v1beta/openai e streaming SSE).
Supporta qualsiasi modello Gemini configurato (es. gemini-2.0-flash, gemini-2.5-flash, gemini-2.0-flash-lite).
Riconosce ed estrae esplicitamente tutte le condizioni di blocco safety di Gemini (promptFeedback, candidate safety).
"""

import json
from typing import Optional, Dict, Any, List
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk


class GoogleProvider(BaseLLMProvider):
    """Adapter ufficiale per modelli Google Gemini tramite interfaccia REST."""

    @property
    def name(self) -> str:
        return "google"

    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        base = (base_url or "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def get_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
        }

    def build_payload(
        self,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        thinking: bool = False,
        reasoning_effort: str = "low",
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = True,
        max_thinking_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        clean_model = model.strip()
        if clean_model.startswith("google/"):
            clean_model = clean_model[len("google/"):]

        payload: Dict[str, Any] = {
            "model": clean_model,
            "messages": messages,
            "stream": stream,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if temperature is not None:
            payload["temperature"] = temperature

        if response_format:
            payload["response_format"] = response_format

        return payload

    def parse_stream_line(self, line: str) -> Optional[StreamChunk]:
        clean_line = line.strip()
        if not clean_line or not clean_line.startswith("data:"):
            return None

        raw_data = clean_line[5:].strip()
        if raw_data == "[DONE]":
            return None

        try:
            chunk_dict = json.loads(raw_data)
        except json.JSONDecodeError:
            return None

        content_delta = None
        finish_reason = None
        req_id = chunk_dict.get("id")
        usage = chunk_dict.get("usage")

        # Verifica blocco a livello di prompt feedback Google
        prompt_feedback = chunk_dict.get("promptFeedback") or {}
        if prompt_feedback.get("blockReason") in ("SAFETY", "OTHER", "BLOCKLIST"):
            finish_reason = "content_filter"

        choices = chunk_dict.get("choices", [])
        if choices and len(choices) > 0:
            choice = choices[0]
            raw_fr = choice.get("finish_reason") or choice.get("finishReason")
            if raw_fr:
                # Normalizza verso standard content_filter se safety
                if str(raw_fr).upper() in ("SAFETY", "CONTENT_FILTER", "BLOCKED"):
                    finish_reason = "content_filter"
                else:
                    finish_reason = str(raw_fr).lower()

            delta = choice.get("delta", {})
            content_delta = delta.get("content")

        return StreamChunk(
            content_delta=content_delta,
            reasoning_delta=None,
            usage=usage,
            finish_reason=finish_reason,
            request_id=req_id
        )

    def normalize_response(
        self,
        raw_json: Dict[str, Any],
        model_name: str,
        request_id: Optional[str] = None
    ) -> NormalizedResponse:
        content = ""
        finish_reason = None

        prompt_feedback = raw_json.get("promptFeedback") or {}
        if prompt_feedback.get("blockReason") in ("SAFETY", "OTHER", "BLOCKLIST"):
            finish_reason = "content_filter"

        choices = raw_json.get("choices", [])
        if choices and len(choices) > 0:
            choice = choices[0]
            raw_fr = choice.get("finish_reason") or choice.get("finishReason")
            if raw_fr:
                if str(raw_fr).upper() in ("SAFETY", "CONTENT_FILTER", "BLOCKED"):
                    finish_reason = "content_filter"
                else:
                    finish_reason = str(raw_fr).lower()

            msg = choice.get("message", {})
            content = msg.get("content") or ""

        return NormalizedResponse(
            content=content,
            reasoning=None,
            usage=raw_json.get("usage"),
            finish_reason=finish_reason,
            provider=self.name,
            model=model_name,
            request_id=request_id or raw_json.get("id")
        )
