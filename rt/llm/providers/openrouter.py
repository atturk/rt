"""
rt.llm.providers.openrouter
Adapter per OpenRouter API (Chat Completions con supporto unificato al Reasoning e Streaming).
"""

import json
from typing import Optional, Dict, Any, List, Tuple
import requests

from rt.llm.errors import LLMFailure, RateLimitFailure, UnknownProviderFailure, classify_failure, parse_retry_after
from rt.llm.providers.base import BaseLLMProvider, BatchResultItem, NormalizedResponse, StreamChunk


class OpenRouterProvider(BaseLLMProvider):
    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def supports_batch(self) -> bool:
        return True

    def batch_model(self, model: str) -> str:
        clean = (model or "").strip()
        if "/" not in clean and not clean.startswith("~") and clean.startswith("deepseek"):
            clean = f"deepseek/{clean}"
        if clean and not clean.endswith(":batch"):
            return f"{clean}:batch"
        return clean

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
        thinking: Optional[bool] = None,
        reasoning_effort: Optional[str] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
        stream: bool = True,
        max_thinking_tokens: Optional[int] = None,
        provider_routing: Optional[Dict[str, Any]] = None,
        response_json_schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
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

        if response_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_response", "schema": response_json_schema, "strict": True},
            }
        elif response_format:
            payload["response_format"] = response_format

        if temperature is not None:
            payload["temperature"] = temperature

        # Configurazione unificata OpenRouter per modelli reasoning
        if thinking is True:
            if max_thinking_tokens is not None and max_thinking_tokens > 0:
                # Se è specificato max_thinking_tokens, ha priorità assoluta e reasoning_effort viene ignorato
                payload["reasoning"] = {
                    "max_tokens": int(max_thinking_tokens)
                }
            elif reasoning_effort and str(reasoning_effort).strip():
                payload["reasoning"] = {
                    "enabled": True,
                    "effort": str(reasoning_effort).lower().strip()
                }
            else:
                payload["reasoning"] = {
                    "enabled": True
                }
        # thinking is False o None: non includere affatto la chiave 'reasoning'. Non mandare mai
        # {"enabled": False} esplicito: alcuni modelli con reasoning obbligatorio (es. DeepSeek V3.1
        # Terminus su OpenRouter, confermato) rispondono con HTTP 400 "Reasoning is mandatory for this
        # endpoint and cannot be disabled". Omettere la chiave lascia decidere il comportamento nativo
        # del modello, che è l'unico modo sicuro di "non forzare" il reasoning su OpenRouter.

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

    def get_batches_endpoint(self, base_url: Optional[str] = None) -> str:
        base = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[:-len("/chat/completions")].rstrip("/")
        return f"{base}/batches"

    def build_batch_payload(self, requests_list: List[Dict[str, Any]], *, model: str) -> str:
        """Serializza il corpo JSON del lotto garantendo endpoint, model e completion_window PRIMA di requests."""
        clean_requests = []
        for item in requests_list:
            raw_body = dict(item.get("body") or {})
            raw_body.pop("stream", None)
            raw_body.pop("stream_options", None)
            clean_requests.append({
                "custom_id": str(item["custom_id"]),
                "body": raw_body,
            })
        payload = {
            "endpoint": "/v1/chat/completions",
            "model": self.batch_model(model),
            "completion_window": "24h",
            "requests": clean_requests,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _raise_batch_http_error(self, resp: Any, *, model: str = "") -> None:
        status = getattr(resp, "status_code", None)
        try:
            text = resp.content.decode("utf-8", errors="replace") if hasattr(resp, "content") else str(getattr(resp, "text", ""))
        except Exception:
            text = str(getattr(resp, "text", ""))
        headers = getattr(resp, "headers", None)
        if status == 429:
            raise RateLimitFailure(
                text or "Rate limit OpenRouter batch (HTTP 429)",
                retry_after=parse_retry_after(headers, text),
                provider=self.name,
                model=model,
                http_status=429,
            )
        if status == 402:
            err = LLMFailure(
                f"Crediti OpenRouter insufficienti per il lotto batch (HTTP 402): {text[:240]}",
                provider=self.name,
                model=model,
                http_status=402,
            )
            err.failure_class = "payment_required"
            raise err
        if status == 413:
            err = LLMFailure(
                f"Lotto batch troppo grande per OpenRouter (HTTP 413): {text[:240]}",
                provider=self.name,
                model=model,
                http_status=413,
            )
            err.failure_class = "payload_too_large"
            raise err
        raise classify_failure(
            http_status=status,
            raw_response=text,
            provider=self.name,
            model=model,
            headers=headers,
        )

    def submit_batch(
        self,
        requests_list: List[Dict[str, Any]],
        *,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> str:
        body_str = self.build_batch_payload(requests_list, model=model)
        resp = requests.post(
            self.get_batches_endpoint(base_url),
            headers=self.get_headers(api_key),
            data=body_str.encode("utf-8"),
            timeout=timeout,
        )
        if getattr(resp, "status_code", 200) >= 400:
            self._raise_batch_http_error(resp, model=model)
        data = resp.json()
        if isinstance(data.get("data"), dict) and "id" not in data and "batch_id" not in data:
            data = data["data"]
        batch_id = str(data.get("id") or data.get("batch_id") or "").strip()
        if not batch_id:
            raise UnknownProviderFailure(
                "Risposta OpenRouter /batches priva di id del lotto.",
                provider=self.name,
                model=model,
                http_status=getattr(resp, "status_code", None),
            )
        return batch_id

    def poll_batch(
        self,
        batch_id: str,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Tuple[str, Optional[Dict[str, BatchResultItem]]]:
        url = f"{self.get_batches_endpoint(base_url)}/{batch_id}"
        resp = requests.get(url, headers=self.get_headers(api_key), timeout=timeout)
        if getattr(resp, "status_code", 200) >= 400:
            self._raise_batch_http_error(resp)
        data = resp.json()
        if isinstance(data.get("data"), dict) and "status" not in data:
            data = data["data"]
        status = str(data.get("status") or "").lower().strip()
        if status != "completed":
            return status, None

        parsed: Dict[str, BatchResultItem] = {}
        batch_model_name = str(data.get("model") or "")
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("custom_id") or "")
            if not cid:
                continue
            item_err = item.get("error")
            if item_err:
                if isinstance(item_err, dict):
                    msg = str(item_err.get("message") or json.dumps(item_err, ensure_ascii=False))
                    sc = item_err.get("code") or item_err.get("status_code")
                    http_sc = int(sc) if isinstance(sc, int) else None
                else:
                    msg = str(item_err)
                    http_sc = None
                parsed[cid] = BatchResultItem(custom_id=cid, error=msg, http_status=http_sc)
                continue

            resp_obj = item.get("response")
            if not isinstance(resp_obj, dict):
                parsed[cid] = BatchResultItem(custom_id=cid, error="Risposta batch mancante")
                continue

            if isinstance(resp_obj.get("body"), dict):
                sc = resp_obj.get("status_code", 200)
                raw_body = resp_obj["body"]
            else:
                sc = resp_obj.get("status_code", 200)
                raw_body = resp_obj

            if (isinstance(sc, int) and sc >= 400) or (isinstance(raw_body, dict) and raw_body.get("error")):
                raw_err = raw_body.get("error") if isinstance(raw_body, dict) else raw_body
                if isinstance(raw_err, dict):
                    msg = str(raw_err.get("message") or json.dumps(raw_err, ensure_ascii=False))
                else:
                    msg = str(raw_err or f"Errore HTTP {sc}")
                parsed[cid] = BatchResultItem(
                    custom_id=cid,
                    error=msg,
                    http_status=int(sc) if isinstance(sc, int) else None,
                )
                continue

            norm = self.normalize_response(
                raw_body,
                model_name=str(raw_body.get("model") or batch_model_name),
                request_id=raw_body.get("id"),
            )
            parsed[cid] = BatchResultItem(custom_id=cid, response=norm)

        return "completed", parsed

    def cleanup_batch(
        self,
        batch_id: str,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        url = f"{self.get_batches_endpoint(base_url)}/{batch_id}"
        requests.delete(url, headers=self.get_headers(api_key), timeout=timeout)
