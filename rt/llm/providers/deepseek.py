"""
rt.llm.providers.deepseek
Adapter per DeepSeek API ufficiale (Chat Completions con Thinking Mode).
"""

import json
from typing import Optional, Dict, Any, List
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk
from rt.llm.capabilities import get_capabilities


class DeepSeekProvider(BaseLLMProvider):
    @property
    def name(self) -> str:
        return "deepseek"

    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        base = (base_url or "https://api.deepseek.com").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def get_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }

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
        clean_model = model.lstrip("~").strip()
        if clean_model.startswith("deepseek/"):
            clean_model = clean_model[len("deepseek/"):]

        payload: Dict[str, Any] = {
            "model": clean_model,
            "messages": messages,
            "stream": stream,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if stream:
            payload["stream_options"] = {"include_usage": True}

        if response_format:
            payload["response_format"] = response_format

        # Configurazione nativa DeepSeek Thinking Mode e verifica capabilities formali
        caps = get_capabilities(self.name, thinking_mode=thinking)
        if thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = str(reasoning_effort or "low").lower().strip()
        else:
            payload["thinking"] = {"type": "disabled"}

        if temperature is not None and caps.supports_temperature:
            payload["temperature"] = temperature

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
        reasoning_delta = None
        finish_reason = None
        req_id = chunk_dict.get("id")
        usage = chunk_dict.get("usage")

        choices = chunk_dict.get("choices", [])
        if choices and len(choices) > 0:
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            delta = choice.get("delta", {})
            content_delta = delta.get("content")
            # DeepSeek restituisce il reasoning del chunk in reasoning_content
            reasoning_delta = delta.get("reasoning_content")

        return StreamChunk(
            content_delta=content_delta,
            reasoning_delta=reasoning_delta,
            usage=usage,
            finish_reason=finish_reason,
            request_id=req_id,
            resolved_model=chunk_dict.get("model")
        )

    def normalize_response(
        self,
        raw_json: Dict[str, Any],
        model_name: str,
        request_id: Optional[str] = None
    ) -> NormalizedResponse:
        choices = raw_json.get("choices", [])
        content = ""
        reasoning = None
        finish_reason = None

        if choices and len(choices) > 0:
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            msg = choice.get("message", {})
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content")

        return NormalizedResponse(
            content=content,
            reasoning=reasoning,
            usage=raw_json.get("usage"),
            finish_reason=finish_reason,
            provider=self.name,
            model=model_name,
            resolved_model=raw_json.get("model"),
            request_id=request_id or raw_json.get("id")
        )
