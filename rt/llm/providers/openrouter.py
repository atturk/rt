"""
rt.llm.providers.openrouter
Adapter per OpenRouter API (Chat Completions con supporto unificato al Reasoning e Streaming).
"""

import json
from typing import Optional, Dict, Any, List
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk


class OpenRouterProvider(BaseLLMProvider):
    @property
    def name(self) -> str:
        return "openrouter"

    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        base = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def get_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
            "HTTP-Referer": "https://github.com/attilioturco/trt",
            "X-Title": "RT Academic Workflow"
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
        max_thinking_tokens: Optional[int] = None,
        provider_routing: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        # OpenRouter supporta alias di modelli con tilde (es. '~deepseek/deepseek-v4-flash-latest')
        clean_model = model.strip()
        if "/" not in clean_model and not clean_model.startswith("~") and clean_model.startswith("deepseek"):
            clean_model = f"deepseek/{clean_model}"
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

        if temperature is not None:
            payload["temperature"] = temperature

        # Configurazione unificata OpenRouter per modelli reasoning
        if thinking:
            if max_thinking_tokens is not None and max_thinking_tokens > 0:
                # Se è specificato max_thinking_tokens, ha priorità assoluta e reasoning_effort viene ignorato
                payload["reasoning"] = {
                    "max_tokens": int(max_thinking_tokens)
                }
            else:
                payload["reasoning"] = {
                    "enabled": True,
                    "effort": str(reasoning_effort or "low").lower().strip()
                }
        else:
            payload["reasoning"] = {
                "enabled": False
            }

        if provider_routing:
            payload["provider"] = provider_routing

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
            # OpenRouter può restituire il reasoning in 'reasoning' o 'reasoning_content'
            reasoning_delta = delta.get("reasoning") or delta.get("reasoning_content")

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
            reasoning = msg.get("reasoning") or msg.get("reasoning_content")

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
