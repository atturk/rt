"""
rt.llm.providers.openai_compatible
Adapter generico per qualunque endpoint compatibile con l'API OpenAI Chat Completions
(es. Mistral AI ufficiale, OpenAI ufficiale, Groq, Together.ai, server locali vLLM/Ollama/LM Studio).
Nessuna estensione proprietaria di vendor: niente campi 'thinking'/'reasoning' (specifici di DeepSeek/OpenRouter).
"""

import json
from typing import Optional, Dict, Any, List
from rt.llm.providers.base import BaseLLMProvider, NormalizedResponse, StreamChunk


class OpenAICompatibleProvider(BaseLLMProvider):
    @property
    def name(self) -> str:
        return "openai_compatible"

    def get_endpoint(self, base_url: Optional[str] = None) -> str:
        if not base_url:
            raise ValueError(
                "Il provider 'openai_compatible' richiede un 'base_url' esplicito in rt.config.yaml "
                "(non esiste un endpoint di default per questo tipo di provider)."
            )
        base = base_url.rstrip("/")
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
        thinking: bool = True,
        reasoning_effort: str = "low",
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = True,
        max_thinking_tokens: Optional[int] = None,
        provider_routing: Optional[Dict[str, Any]] = None,
        response_json_schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        # 'thinking'/'reasoning_effort'/'max_thinking_tokens'/'provider_routing' sono ignorati volutamente:
        # non fanno parte della Chat Completions API standard OpenAI (provider_routing è specifico di OpenRouter).
        payload: Dict[str, Any] = {
            "model": model.strip(),
            "messages": messages,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        # Molti server OpenAI-compatible locali (LM Studio/llama.cpp) non accettano
        # response_format.type == 'json_object' ("must be 'json_schema' or 'text'"):
        # se disponibile lo schema della risposta attesa, usiamo la modalità
        # 'json_schema' (generazione vincolata allo schema), altrimenti il response_format
        # generico passato dal chiamante.
        if response_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "schema": response_json_schema,
                    "strict": True
                }
            }
        elif response_format:
            payload["response_format"] = response_format
        if temperature is not None:
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
        finish_reason = None
        req_id = chunk_dict.get("id")
        usage = chunk_dict.get("usage")

        choices = chunk_dict.get("choices", [])
        if choices:
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            delta = choice.get("delta", {})
            content_delta = delta.get("content")

        return StreamChunk(
            content_delta=content_delta,
            reasoning_delta=None,
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
        finish_reason = None
        if choices:
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            content = choice.get("message", {}).get("content") or ""

        return NormalizedResponse(
            content=content,
            reasoning=None,
            usage=raw_json.get("usage"),
            finish_reason=finish_reason,
            provider=self.name,
            model=model_name,
            resolved_model=raw_json.get("model"),
            request_id=request_id or raw_json.get("id")
        )
