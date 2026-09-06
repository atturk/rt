"""
rt.llm.client
Gateway unificato per orchestrazione LLM, routing engine multi-provider,
telemetry centralizzata, live monitor e streaming.
Disaccoppia la pipeline RT da DeepSeek direct, OpenRouter, Google e qualsiasi altro provider supportato.
RISPETTO RIGOROSO DEI VINCOLI DI SICUREZZA:
- Credenziali caricate ESCLUSIVAMENTE da environment variables o file .env locale.
- Nessuna chiave API letta da file sul Desktop, né scritta nei log.
- Supporto nativo per mock deterministico offline.
"""

import json
import re
import time
import datetime
from typing import Type, TypeVar, Optional, Dict, Any, List, Set
import requests
from pydantic import BaseModel

from rt.core.config import load_config, get_api_key, LLMModelConfig, RouteConfig, JobRoutingConfig
from rt.core.encoding import fix_mojibake, sanitize_object_encoding
from rt.llm.providers import get_provider
from rt.llm.pricing import calculate_cost
from rt.llm.telemetry import LLMTelemetryRecord, GLOBAL_TELEMETRY
from rt.llm.monitor import LiveTerminalMonitor
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.llm.errors import (
    LLMFailure,
    TimeoutFailure,
    RateLimitFailure,
    SafetyFailure,
    AuthenticationFailure,
    NetworkFailure,
    ProviderServerFailure,
    SchemaFailure,
    OutputLimitFailure,
    UnknownProviderFailure,
    classify_failure,
    LLMError,
    LLMTimeoutError,
)
from rt.llm.router import RoutingEngine, ExecutionRoute

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, config_path: Optional[str] = None, force_mock: bool = False):
        self.config = load_config(config_path)
        self.force_mock = force_mock or self.config.mock_llm
        self.router = RoutingEngine(self.config)

    def _get_job_routing_config(self, job_name: str) -> JobRoutingConfig:
        clean = job_name.lower().strip()
        cfg = self.config.jobs.get(clean) or self.config.llm.get(clean)
        if cfg:
            return cfg
        default_cfg = self.config.jobs.get("default") or self.config.llm.get("default")
        if default_cfg:
            return default_cfg
        return JobRoutingConfig(
            primary=RouteConfig(
                provider="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                thinking=True,
                reasoning_effort="low",
                max_tokens=8192,
                timeout_seconds=180
            )
        )

    def _get_model_config(self, job_name: str) -> RouteConfig:
        """Restituisce la configurazione della route primaria (retrocompatibilità con test e codice esistente)."""
        job_cfg = self._get_job_routing_config(job_name)
        return job_cfg.primary

    def call_structured(
        self,
        prompt: str,
        system_prompt: str,
        response_model: Type[T],
        job_name: str = "general",
        max_retries: int = 2,
        unit_id: Optional[str] = None,
        override_provider: Optional[str] = None,
        override_model: Optional[str] = None,
        override_base_url: Optional[str] = None,
        override_credential: Optional[str] = None,
        stream: Optional[bool] = None,
        show_monitor: Optional[bool] = None,
        max_timeout_retries: Optional[int] = None,
        timeout_backoff_seconds: Optional[float] = None
    ) -> T:
        """
        Invia una richiesta strutturata orchestrata dal Routing Engine:
        - Supporto Multi-Provider (DeepSeek, OpenRouter, Google Gemini Dual-Key, Mock);
        - Failover su classi di errore mirate (auth, rate_limit, timeout, safety, generic);
        - Retry bounded configurabili per timeout di rete sulla stessa route;
        - Monitor a terminale con streaming live, costi stimati e redazione automatica dei secret;
        - Validazione Pydantic con meccanismo di auto-repair.
        """
        job_routing_cfg = self._get_job_routing_config(job_name)
        primary_cfg = job_routing_cfg.primary

        # execution_id univoco che lega tutti i tentativi e fallback di questa specifica unità/chiamata
        clean_unit = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", unit_id) if unit_id else "direct"
        execution_id = f"exec_{job_name}_{clean_unit}_{int(time.time() * 1000)}"

        # Se force_mock o configurazione mock esplicita, usa il mock deterministico
        if self.force_mock:
            mock_rec = LLMTelemetryRecord(
                request_id=f"mock_req_{int(time.time() * 1000)}",
                execution_id=execution_id,
                job=job_name,
                unit_id=unit_id,
                provider="mock",
                model="mock-deterministic",
                route_id="mock|mock-deterministic|mock",
                route_role="primary",
                credential_ref="mock",
                attempt=1,
                started_at=datetime.datetime.now().isoformat(),
                ended_at=datetime.datetime.now().isoformat(),
                elapsed_seconds=0.0,
                status="success",
                error_class="success",
                input_tokens=0,
                reasoning_tokens=0,
                output_tokens=0,
                total_tokens=0,
                output_chars=100,
                latency_ms=0.0,
                finish_reason="stop",
                estimated_cost=0.0,
                streaming=False,
                timeout_seconds_configured=primary_cfg.timeout_seconds
            )
            GLOBAL_TELEMETRY.add(mock_rec)
            return self._generate_mock_response(job_name, prompt, response_model)

        # Risoluzione route iniziale (con supporto a eventuali override manuali)
        if override_provider or override_model or override_credential:
            prov = (override_provider or primary_cfg.provider).lower().strip()
            mod = override_model or (primary_cfg.model if prov == primary_cfg.provider else ("gemini-2.5-flash" if prov == "google" else "deepseek-v4-flash"))
            b_url = override_base_url
            if not b_url:
                if prov == primary_cfg.provider:
                    b_url = primary_cfg.base_url
                elif prov == "google":
                    b_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                elif prov == "openrouter":
                    b_url = "https://openrouter.ai/api/v1"
                elif prov == "deepseek":
                    b_url = "https://api.deepseek.com"
                else:
                    b_url = None
            if prov == "openrouter" and (not b_url or b_url == "https://api.deepseek.com"):
                b_url = "https://openrouter.ai/api/v1"

            cred = override_credential or (primary_cfg.credential if prov == primary_cfg.provider else None)
            try:
                override_route = RouteConfig(
                    provider=prov,
                    model=mod,
                    credential=cred,
                    base_url=b_url,
                    thinking=primary_cfg.thinking,
                    reasoning_effort=primary_cfg.reasoning_effort,
                    max_thinking_tokens=primary_cfg.max_thinking_tokens,
                    temperature=primary_cfg.temperature,
                    max_tokens=primary_cfg.max_tokens,
                    timeout_seconds=primary_cfg.timeout_seconds
                )
            except Exception as ve:
                raise LLMError(f"Provider LLM non configurato o non supportato: {ve}") from ve
            current_exec_route = ExecutionRoute(route=override_route, route_role="primary")
        else:
            current_exec_route = self.router.select_initial_route(job_name)


        # Parametri globali di catena
        visited_route_ids: Set[str] = set()
        max_global_attempts = 1 if (override_provider or override_credential) else job_routing_cfg.max_attempts
        max_output_chars = job_routing_cfg.max_output_chars or 45000

        route_attempt = 1
        call_attempt = 1
        parent_attempt: Optional[int] = None
        current_fallback_reason: Optional[str] = None
        last_failure: Optional[LLMFailure] = None

        # Schema JSON per prompt strutturato
        json_schema_str = json.dumps(response_model.model_json_schema(), ensure_ascii=False, indent=2)
        full_system = (
            f"{system_prompt}\n\n"
            f"DEVI restituire ESCLUSIVAMENTE un oggetto JSON valido conforme a questo JSON Schema:\n"
            f"{json_schema_str}\n"
            f"Nessun commento prima o dopo il JSON."
        )
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": prompt}
        ]
        approx_in_tok = max(1, (len(full_system) + len(prompt)) // 4)
        prev_session_cost = GLOBAL_TELEMETRY.get_summary().get("total_estimated_cost_usd", 0.0)

        # Retry config locale per timeout sulla stessa route
        cfg_retry = getattr(self.config, "retry", None)
        default_max_timeout_retries = getattr(cfg_retry, "max_timeout_retries", 1) if cfg_retry else 1
        default_backoff_sec = getattr(cfg_retry, "timeout_backoff_seconds", 2.0) if cfg_retry else 2.0
        route_max_timeout_retries = max_timeout_retries if max_timeout_retries is not None else default_max_timeout_retries
        effective_backoff_sec = timeout_backoff_seconds if timeout_backoff_seconds is not None else default_backoff_sec

        # --------------------------------------------------------------------------
        # LOOP PRINCIPALE DI ROUTING (TRANSIZIONE TRA ROUTES E FAILOVER)
        # --------------------------------------------------------------------------
        while route_attempt <= max_global_attempts:
            route = current_exec_route.route
            route_id = route.route_id
            visited_route_ids.add(route_id)

            provider_name = route.provider.lower().strip()
            model_name = route.model.strip()
            credential_ref = route.credential or GLOBAL_CREDENTIALS.get_default_credential_for_provider(provider_name) or provider_name
            base_url = route.base_url

            if provider_name == "openrouter" and (not base_url or base_url == "https://api.deepseek.com"):
                base_url = "https://openrouter.ai/api/v1"

            # Risoluzione provider adapter
            try:
                provider = get_provider(provider_name)
            except ValueError as ve:
                raise LLMError(f"Provider LLM non riconosciuto: {ve}")

            # Risoluzione credenziali da Registry
            api_key = GLOBAL_CREDENTIALS.get_api_key(credential_ref)
            if not api_key and provider_name != "mock":

                env_var = "OPENROUTER_API_KEY" if provider_name == "openrouter" else (
                    "GOOGLE_API_KEY_1" if credential_ref == "google_1" else (
                        "GOOGLE_API_KEY_2" if credential_ref == "google_2" else f"{provider_name.upper()}_API_KEY"
                    )
                )
                auth_fail = AuthenticationFailure(
                    f"API key mancante per il provider '{provider_name}'. "
                    f"Imposta la variabile d'ambiente {env_var} (oppure definiscila nel file .env locale). "
                    f"Nessun fallback silenzioso consentito in modalità reale.",
                    provider=provider_name,
                    model=model_name
                )
                last_failure = auth_fail
                # Failover esplicito se configurato fallback.auth
                next_exec_route = self.router.select_fallback_route(
                    job_name=job_name,
                    failure=auth_fail,
                    visited_route_ids=visited_route_ids,
                    current_attempt=route_attempt
                )
                if next_exec_route:
                    parent_attempt = call_attempt
                    route_attempt += 1
                    call_attempt += 1
                    current_fallback_reason = next_exec_route.fallback_reason
                    current_exec_route = next_exec_route
                    continue
                else:
                    raise auth_fail


            headers = provider.get_headers(api_key or "mock-key")
            endpoint = provider.get_endpoint(base_url)

            use_stream = stream if stream is not None else getattr(self.config, "streaming", True)
            use_monitor = show_monitor if show_monitor is not None else getattr(self.config, "show_monitor", True)
            timeout_seconds = route.timeout_seconds

            monitor = LiveTerminalMonitor(
                job=job_name,
                provider=provider_name,
                model=model_name,
                unit_id=unit_id,
                enabled=use_monitor,
                pricing=self.config.pricing,
                approx_input_tokens=approx_in_tok,
                prev_session_cost=prev_session_cost,
                attempt=call_attempt,
                max_attempts=max_global_attempts,
                timeout_seconds=timeout_seconds,
            )

            # Sub-loop per same-route retry (unificata esclusivamente per timeout di rete sulla stessa route)
            route_timeout_attempt = 0
            total_route_timeout_attempts = 1 + max(0, route_max_timeout_retries)

            while route_timeout_attempt < total_route_timeout_attempts:
                route_timeout_attempt += 1
                t_attempt_start = time.time()
                t_attempt_monotonic = time.monotonic()
                deadline = (t_attempt_monotonic + timeout_seconds) if (timeout_seconds and timeout_seconds > 0) else None

                if route_timeout_attempt > 1:
                    monitor.reset_for_attempt(call_attempt)

                payload = provider.build_payload(
                    model=model_name,
                    messages=list(messages),
                    max_tokens=route.max_tokens,
                    thinking=route.thinking,
                    reasoning_effort=route.reasoning_effort,
                    temperature=route.temperature,
                    response_format={"type": "json_object"},
                    stream=use_stream,
                    max_thinking_tokens=route.max_thinking_tokens
                )

                raw_content = ""
                reasoning_content = ""
                final_usage = None
                finish_reason = None
                req_id = None
                t_first_chunk = None
                t_last_chunk = None
                http_status = None
                attempt_exception: Optional[Exception] = None

                # Sotto-ciclo per riparazione schema (max_retries riparazioni)
                for repair_turn in range(max_retries + 1):
                    monitor.set_step(1, "Preparing request", status="preparing")
                    monitor.set_step(2, "Sending request", status="sending")

                    raw_content = ""
                    reasoning_content = ""
                    final_usage = None
                    finish_reason = None
                    req_id = None

                    if deadline is not None:
                        rem_sec = deadline - time.monotonic()
                        if rem_sec <= 0:
                            attempt_exception = TimeoutFailure(
                                f"Deadline wall-clock superata prima dell'invio della richiesta "
                                f"({time.time() - t_attempt_start:.2f}s >= {timeout_seconds}s)",
                                provider=provider_name,
                                model=model_name
                            )
                            break
                        req_timeout = max(0.1, rem_sec)
                    else:
                        req_timeout = None

                    try:
                        if use_stream:
                            post_kwargs = {
                                "headers": headers,
                                "json": payload,
                                "timeout": req_timeout,
                                "stream": True,
                            }
                            try:
                                response = requests.post(endpoint, **post_kwargs)
                            except TypeError as te:
                                if "unexpected keyword argument 'stream'" in str(te):
                                    del post_kwargs["stream"]
                                    response = requests.post(endpoint, **post_kwargs)
                                else:
                                    raise

                            if hasattr(response, "status_code"):
                                http_status = response.status_code

                            if hasattr(response, "encoding"):
                                response.encoding = "utf-8"

                            if response.status_code != 200:
                                try:
                                    content_str = response.content.decode("utf-8", errors="replace") if hasattr(response, "content") else response.text
                                except Exception:
                                    content_str = str(getattr(response, "text", ""))
                                classified_err = classify_failure(
                                    http_status=response.status_code,
                                    raw_response=content_str,
                                    provider=provider_name,
                                    model=model_name,
                                    headers=getattr(response, "headers", None)
                                )
                                raise classified_err

                            monitor.set_step(3, "Streaming response", status="streaming")
                            content_parts: List[str] = []
                            reasoning_parts: List[str] = []
                            streamed_any_chunk = False

                            if hasattr(response, "iter_lines") and callable(response.iter_lines):
                                for line_raw in response.iter_lines(decode_unicode=False):
                                    now_mono = time.monotonic()
                                    if deadline is not None and now_mono >= deadline:
                                        try:
                                            response.close()
                                        except Exception:
                                            pass
                                        elapsed_att = time.time() - t_attempt_start
                                        raise TimeoutFailure(
                                            f"Deadline wall-clock superata durante lo streaming "
                                            f"({elapsed_att:.2f}s > {timeout_seconds}s)",
                                            provider=provider_name,
                                            model=model_name
                                        )

                                    if not line_raw:
                                        continue
                                    if isinstance(line_raw, bytes):
                                        line = line_raw.decode("utf-8", errors="replace")
                                    else:
                                        line = str(line_raw)

                                    chunk = provider.parse_stream_line(line)
                                    if chunk is None:
                                        continue

                                    now_t = time.time()
                                    if t_first_chunk is None and (chunk.content_delta or chunk.reasoning_delta):
                                        t_first_chunk = now_t
                                    t_last_chunk = now_t

                                    streamed_any_chunk = True
                                    if chunk.request_id and not req_id:
                                        req_id = chunk.request_id
                                    if chunk.content_delta:
                                        content_parts.append(chunk.content_delta)
                                    if chunk.reasoning_delta:
                                        reasoning_parts.append(chunk.reasoning_delta)
                                    if chunk.finish_reason:
                                        finish_reason = chunk.finish_reason

                                    # ------------------------------------------------------------------
                                    # OUTPUT EXPLOSION GUARD (Sezione 23 & Revisione Specifica)
                                    # ------------------------------------------------------------------
                                    accumulated_chars = sum(len(p) for p in content_parts) + sum(len(r) for r in reasoning_parts)
                                    if max_output_chars and accumulated_chars > max_output_chars:
                                        try:
                                            response.close()
                                        except Exception:
                                            pass
                                        raise OutputLimitFailure(
                                            f"Output explosion guard attivata: ricevuti {accumulated_chars} caratteri, "
                                            f"superando il limite rigido di {max_output_chars} caratteri configurato per '{job_name}'.",
                                            provider=provider_name,
                                            model=model_name
                                        )

                                    # Rilevamento immediato blocco safety in streaming
                                    if finish_reason in ("content_filter", "safety", "blocked"):
                                        try:
                                            response.close()
                                        except Exception:
                                            pass
                                        raise SafetyFailure(
                                            f"Blocco safety/content_filter durante lo streaming dal provider '{provider_name}'",
                                            finish_reason=finish_reason,
                                            provider=provider_name,
                                            model=model_name
                                        )

                                    if chunk.usage:
                                        final_usage = chunk.usage
                                        in_t = final_usage.get("prompt_tokens")
                                        out_t = final_usage.get("completion_tokens")
                                        det = final_usage.get("completion_tokens_details") or {}
                                        reas_t = det.get("reasoning_tokens")
                                        cost_est = calculate_cost(
                                            provider=provider_name,
                                            model=model_name,
                                            input_tokens=in_t,
                                            output_tokens=out_t,
                                            reasoning_tokens=reas_t,
                                            custom_pricing=self.config.pricing
                                        )
                                        monitor.on_usage(final_usage, cost_est)

                                    monitor.on_chunk(chunk.content_delta, chunk.reasoning_delta)

                                    if deadline is not None and time.monotonic() >= deadline:
                                        try:
                                            response.close()
                                        except Exception:
                                            pass
                                        elapsed_att = time.time() - t_attempt_start
                                        raise TimeoutFailure(
                                            f"Deadline wall-clock superata durante lo streaming "
                                            f"({elapsed_att:.2f}s > {timeout_seconds}s)",
                                            provider=provider_name,
                                            model=model_name
                                        )

                            # Fallback per risposte non in streaming o mock in memoria
                            if not streamed_any_chunk and hasattr(response, "json"):
                                try:
                                    res_json = response.json()
                                    if res_json and "choices" in res_json:
                                        norm = provider.normalize_response(res_json, model_name=model_name)
                                        content_parts.append(norm.content)
                                        if norm.reasoning:
                                            reasoning_parts.append(norm.reasoning)
                                        final_usage = norm.usage
                                        finish_reason = norm.finish_reason
                                        req_id = norm.request_id
                                except Exception:
                                    pass

                            raw_content = "".join(content_parts)
                            reasoning_content = "".join(reasoning_parts)

                        else:
                            # Chiamata non-streaming standard
                            post_kwargs = {
                                "headers": headers,
                                "json": payload,
                                "timeout": req_timeout,
                            }
                            response = requests.post(endpoint, **post_kwargs)

                            if hasattr(response, "status_code"):
                                http_status = response.status_code

                            if hasattr(response, "encoding"):
                                response.encoding = "utf-8"

                            if hasattr(response, "status_code") and response.status_code != 200:
                                try:
                                    content_str = response.content.decode("utf-8", errors="replace") if hasattr(response, "content") else response.text
                                except Exception:
                                    content_str = str(getattr(response, "text", ""))
                                classified_err = classify_failure(
                                    http_status=response.status_code,
                                    raw_response=content_str,
                                    provider=provider_name,
                                    model=model_name,
                                    headers=getattr(response, "headers", None)
                                )
                                raise classified_err

                            try:
                                content_str = response.content.decode("utf-8", errors="replace") if hasattr(response, "content") else response.text
                                res_json = json.loads(content_str)
                            except Exception:
                                res_json = response.json()

                            norm = provider.normalize_response(res_json, model_name=model_name)
                            raw_content = fix_mojibake(norm.content)
                            reasoning_content = fix_mojibake(norm.reasoning or "")
                            final_usage = norm.usage
                            finish_reason = norm.finish_reason
                            req_id = norm.request_id

                        # Output explosion check per risposta intera
                        if max_output_chars and len(raw_content) > max_output_chars:
                            raise OutputLimitFailure(
                                f"Output explosion guard attivata: ricevuti {len(raw_content)} caratteri "
                                f"(massimo consentito: {max_output_chars})",
                                provider=provider_name,
                                model=model_name
                            )

                        # Verifica deadline post ricezione
                        if deadline is not None and time.monotonic() >= deadline:
                            elapsed_att = time.time() - t_attempt_start
                            raise TimeoutFailure(
                                f"Deadline wall-clock superata prima della validazione "
                                f"({elapsed_att:.2f}s > {timeout_seconds}s)",
                                provider=provider_name,
                                model=model_name
                            )

                        # Controllo safety finish reason
                        if finish_reason in ("content_filter", "safety", "blocked"):
                            raise SafetyFailure(
                                f"Blocco safety/content_filter rilevato dal provider '{provider_name}'",
                                finish_reason=finish_reason,
                                provider=provider_name,
                                model=model_name
                            )

                        monitor.set_step(4, "Validating response", status="validating")

                        # Diagnostica content vuoto
                        if not raw_content.strip():
                            has_reasoning = bool((reasoning_content or "").strip())
                            diag = (
                                f"[Tentativo {repair_turn + 1}/{max_retries + 1}] Content vuoto ricevuto dal modello. "
                                f"finish_reason='{finish_reason}', reasoning_length={len(reasoning_content or '')}, "
                                f"reasoning_present={has_reasoning}"
                            )
                            if finish_reason == "length":
                                detail = (
                                    f"Il modello ha esaurito il budget token durante la fase di reasoning "
                                    f"({len(reasoning_content or '')} caratteri generati) prima di emettere il JSON finale. "
                                    f"(finish_reason='length')"
                                )
                            else:
                                detail = f"Il modello ha restituito content vuoto con finish_reason='{finish_reason}'."

                            err = SchemaFailure(
                                f"{detail} Diagnostica: {diag}",
                                provider=provider_name,
                                model=model_name,
                                http_status=http_status
                            )
                            if repair_turn < max_retries:
                                time.sleep(1.0)
                                payload["messages"].append({
                                    "role": "assistant",
                                    "content": ""
                                })
                                payload["messages"].append({
                                    "role": "user",
                                    "content": (
                                        f"La risposta precedente era vuota. DEVI restituire un oggetto JSON conforme "
                                        f"al seguente schema:\n{json_schema_str}"
                                    )
                                })
                                continue
                            else:
                                raise err

                        # Pulizia markdown fences
                        clean_content = raw_content.strip()
                        if clean_content.startswith("```"):
                            clean_content = re.sub(r"^\s*```(?:json)?\s*", "", clean_content, flags=re.IGNORECASE)
                            clean_content = re.sub(r"\s*```\s*$", "", clean_content).strip()

                        if not (clean_content.startswith("{") or clean_content.startswith("[")):
                            json_match = re.search(r"(\{.*\})", clean_content, re.DOTALL)
                            if json_match:
                                clean_content = json_match.group(1).strip()

                        try:
                            parsed_data = json.loads(clean_content)
                        except json.JSONDecodeError as jde:
                            raise SchemaFailure(
                                f"JSON non valido in 'content': {jde}. Primi 150 caratteri: {clean_content[:150]}",
                                provider=provider_name,
                                model=model_name
                            )

                        parsed_data = sanitize_object_encoding(parsed_data)

                        try:
                            validated_obj = response_model.model_validate(parsed_data)
                        except Exception as ve:
                            raise SchemaFailure(
                                f"Validazione schema Pydantic fallita: {ve}",
                                provider=provider_name,
                                model=model_name
                            )

                        if deadline is not None and time.monotonic() >= deadline:
                            elapsed_att = time.time() - t_attempt_start
                            raise TimeoutFailure(
                                f"Deadline wall-clock superata dopo la validazione "
                                f"({elapsed_att:.2f}s > {timeout_seconds}s)",
                                provider=provider_name,
                                model=model_name
                            )

                        # SUCCESSO PIENO!
                        t_attempt_end = time.time()
                        elapsed_att = t_attempt_end - t_attempt_start

                        in_t = final_usage.get("prompt_tokens") if final_usage else None
                        out_t = final_usage.get("completion_tokens") if final_usage else None
                        det = final_usage.get("completion_tokens_details") or {} if final_usage else {}
                        reas_t = det.get("reasoning_tokens")
                        tot_t = final_usage.get("total_tokens") if final_usage else None
                        if tot_t is None and (in_t is not None or out_t is not None):
                            tot_t = (in_t or 0) + (out_t or 0)

                        cost_est = calculate_cost(
                            provider=provider_name,
                            model=model_name,
                            input_tokens=in_t,
                            output_tokens=out_t,
                            reasoning_tokens=reas_t,
                            custom_pricing=self.config.pricing
                        )

                        ttft = round(t_first_chunk - t_attempt_start, 4) if t_first_chunk else None
                        stream_dur = round(t_attempt_end - (t_first_chunk or t_attempt_start), 4) if use_stream else None
                        last_chk_iso = datetime.datetime.fromtimestamp(t_last_chunk).isoformat() if t_last_chunk else None

                        telemetry_rec = LLMTelemetryRecord(
                            request_id=req_id or f"req_{int(time.time() * 1000)}",
                            execution_id=execution_id,
                            job=job_name,
                            unit_id=unit_id,
                            provider=provider_name,
                            model=model_name,
                            route_id=route_id,
                            route_role=current_exec_route.route_role,
                            credential_ref=credential_ref,
                            attempt=call_attempt,
                            parent_attempt=parent_attempt,
                            started_at=datetime.datetime.fromtimestamp(t_attempt_start).isoformat(),
                            ended_at=datetime.datetime.fromtimestamp(t_attempt_end).isoformat(),
                            elapsed_seconds=round(elapsed_att, 4),
                            timeout_seconds_configured=timeout_seconds,
                            retry_count=route_timeout_attempt - 1,
                            fallback_reason=current_fallback_reason,
                            input_tokens=in_t,
                            reasoning_tokens=reas_t,
                            output_tokens=out_t,
                            total_tokens=tot_t,
                            output_chars=len(raw_content),
                            time_to_first_token=ttft,
                            stream_duration=stream_dur,
                            last_chunk_at=last_chk_iso,
                            latency_ms=round(elapsed_att * 1000.0, 2),
                            finish_reason=finish_reason,
                            status="success",
                            error_class="success",
                            http_status=http_status or 200,
                            estimated_cost=cost_est,
                            streaming=use_stream
                        )
                        GLOBAL_TELEMETRY.add(telemetry_rec)

                        if final_usage:
                            monitor.on_usage(final_usage, cost_est)
                        monitor.finish(success=True)

                        return validated_obj

                    except Exception as e:
                        attempt_exception = e
                        if 'content_parts' in locals() and content_parts and not raw_content:
                            raw_content = "".join(content_parts)

                        # Solo anomalie di schema/validazione JSON o risposte sintatticamente corrotte possono tentare il repair turn
                        is_infra_error = isinstance(e, (
                            TimeoutFailure,
                            RateLimitFailure,
                            SafetyFailure,
                            AuthenticationFailure,
                            OutputLimitFailure,
                            ProviderServerFailure,
                            NetworkFailure,
                            requests.exceptions.RequestException
                        )) or "timeout" in type(e).__name__.lower()

                        if not is_infra_error and repair_turn < max_retries:
                            time.sleep(1.0)
                            payload["messages"].append({
                                "role": "assistant",
                                "content": raw_content if raw_content else ""
                            })
                            payload["messages"].append({
                                "role": "user",
                                "content": (
                                    f"La risposta fornita ha generato il seguente errore: {e}.\n"
                                    f"DEVI correggere l'errore e restituire ESCLUSIVAMENTE l'oggetto JSON valido "
                                    f"conforme a questo JSON Schema:\n{json_schema_str}\n"
                                    f"Nessun testo o commento aggiuntivo prima o dopo il JSON."
                                )
                            })
                            continue
                        else:
                            break

                # Attempt fallita: classificazione formale
                t_attempt_end = time.time()
                elapsed_att = t_attempt_end - t_attempt_start
                classified_failure = classify_failure(
                    exception=attempt_exception,
                    http_status=http_status,
                    finish_reason=finish_reason,
                    raw_response=raw_content,
                    provider=provider_name,
                    model=model_name
                )
                last_failure = classified_failure

                err_status = "timeout" if isinstance(classified_failure, TimeoutFailure) else "error"

                # Tracciamento telemetrico del fallimento
                err_rec = LLMTelemetryRecord(
                    request_id=req_id or f"req_{int(time.time() * 1000)}",
                    execution_id=execution_id,
                    job=job_name,
                    unit_id=unit_id,
                    provider=provider_name,
                    model=model_name,
                    route_id=route_id,
                    route_role=current_exec_route.route_role,
                    credential_ref=credential_ref,
                    attempt=call_attempt,
                    parent_attempt=parent_attempt,
                    started_at=datetime.datetime.fromtimestamp(t_attempt_start).isoformat(),
                    ended_at=datetime.datetime.fromtimestamp(t_attempt_end).isoformat(),
                    elapsed_seconds=round(elapsed_att, 4),
                    timeout_seconds_configured=timeout_seconds,
                    retry_count=route_timeout_attempt - 1,
                    output_chars=len(raw_content),
                    latency_ms=round(elapsed_att * 1000.0, 2),
                    finish_reason=finish_reason,
                    status=err_status,
                    error_class=classified_failure.failure_class,
                    failure_class=classified_failure.failure_class,
                    http_status=http_status,
                    error_message=classified_failure.message,
                    streaming=use_stream,
                    fallback_reason=current_fallback_reason
                )
                GLOBAL_TELEMETRY.add(err_rec)

                # Controllo Same-Route Retry (esclusivo per Timeout se configurato e bounded)
                if isinstance(classified_failure, TimeoutFailure) and route_timeout_attempt < total_route_timeout_attempts:
                    call_attempt += 1
                    monitor.log_timeout(elapsed_att, next_attempt=call_attempt)
                    backoff = min(30.0, effective_backoff_sec * (2 ** (route_timeout_attempt - 1)))
                    time.sleep(backoff)
                    continue
                else:
                    # Same-route retries esauriti o errore non soggetto a same-route retry
                    break

            # ----------------------------------------------------------------------
            # FAILOVER: Selezione della route successiva tramite il Routing Engine
            # ----------------------------------------------------------------------
            if route_attempt < max_global_attempts:
                next_exec_route = self.router.select_fallback_route(
                    job_name=job_name,
                    failure=last_failure,
                    visited_route_ids=visited_route_ids,
                    current_attempt=route_attempt
                )
                if next_exec_route:
                    # Aggiorna telemetria precedente con metadata del fallback
                    if GLOBAL_TELEMETRY.get_last():
                        last_t = GLOBAL_TELEMETRY.get_last()
                        last_t.fallback_to_provider = next_exec_route.provider
                        last_t.fallback_to_model = next_exec_route.model
                        last_t.fallback_to_credential = next_exec_route.credential

                    parent_attempt = call_attempt
                    route_attempt += 1
                    call_attempt += 1
                    current_fallback_reason = next_exec_route.fallback_reason
                    current_exec_route = next_exec_route
                    continue

            # Se siamo qui, la catena di fallback è esaurita
            monitor.finish(success=False, error_msg=last_failure.message if last_failure else "Execution exhausted")
            if isinstance(last_failure, TimeoutFailure):
                raise LLMTimeoutError(f"Operazione LLM terminata per timeout dopo {call_attempt} tentativi: {last_failure.message}") from last_failure
            raise last_failure if last_failure else LLMError("Esecuzione LLM fallita: nessuna route residua disponibile.")

        raise LLMError(f"Catena di routing esaurita per il job '{job_name}' dopo {call_attempt - 1} tentativi senza successo: {last_failure}")


    def _generate_mock_response(self, job_name: str, prompt: str, response_model: Type[T]) -> T:

        """Generatore deterministico di risposte mock per test offline e fallback."""
        from rt.core.models import (
            Outline, OutlineMacro, OutlineUnit,
            Draft, DraftUnit,
            ASRIssue, ASRLevel,
            ScienceIssue, ScienceType, ScienceSeverity
        )

        model_name = response_model.__name__

        if model_name == "Outline":
            seg_matches = re.findall(r"seg_\d{6}", prompt)
            first_seg = seg_matches[0] if seg_matches else "seg_000001"
            last_seg = seg_matches[-1] if len(seg_matches) > 1 else first_seg

            outline_data = Outline(
                schema_version="1.0",
                lesson_title="Lezione Accademica Rielaborata",
                macro_sections=[
                    OutlineMacro(
                        id="1",
                        title="Introduzione e concetti fondamentali",
                        units=[
                            OutlineUnit(
                                id="1.1",
                                title="Panoramica generale e prima unità",
                                start_segment_id=first_seg,
                                end_segment_id=last_seg,
                                key_concepts=["Concetto chiave 1", "Concetto chiave 2"]
                            )
                        ]
                    )
                ]
            )
            return outline_data  # type: ignore

        elif model_name == "Draft":
            seg_matches = re.findall(r"seg_\d{6}", prompt)
            first_seg = seg_matches[0] if seg_matches else "seg_000001"
            last_seg = seg_matches[-1] if len(seg_matches) > 1 else first_seg

            draft_data = Draft(
                schema_version="1.0",
                units=[
                    DraftUnit(
                        unit_id="1.1",
                        title="Panoramica generale e prima unità",
                        start_segment_id=first_seg,
                        end_segment_id=last_seg,
                        source_segment_ids=seg_matches if seg_matches else [first_seg],
                        content="La trattazione scientifica si apre con l'analisi sistematica dei meccanismi biochimici fondamentali."
                    )
                ]
            )
            return draft_data  # type: ignore

        elif model_name == "DraftUnit":
            seg_matches = re.findall(r"seg_\d{6}", prompt)
            first_seg = seg_matches[0] if seg_matches else "seg_000001"
            last_seg = seg_matches[-1] if len(seg_matches) > 1 else first_seg

            u_match = re.search(r"ID:\s*([0-9.]+)", prompt)
            unit_id = u_match.group(1) if u_match else "1.1"

            unit_data = DraftUnit(
                unit_id=unit_id,
                title="Unità Didattica Rielaborata",
                start_segment_id=first_seg,
                end_segment_id=last_seg,
                source_segment_ids=seg_matches if seg_matches else [first_seg],
                content="La trattazione scientifica si apre con l'analisi sistematica dei meccanismi biochimici fondamentali."
            )
            return unit_data  # type: ignore

        elif model_name == "ASRIssueList" or "ASRIssue" in model_name:
            class ASRIssueList(BaseModel):
                issues: list[ASRIssue] = []
            seg_matches = re.findall(r"seg_\d{6}", prompt)
            first_seg = seg_matches[0] if seg_matches else "seg_000001"
            mock_iss = ASRIssue(
                id="asr_000001",
                segment_id=first_seg,
                source_text="introduzione",
                candidate="Introduzione",
                confidence=0.98,
                level=ASRLevel.GREEN,
                reason="Correzione maiuscola iniziale fonetica",
                status="accepted"
            )
            return ASRIssueList(issues=[mock_iss])  # type: ignore

        elif model_name == "ScienceIssueList" or "ScienceIssue" in model_name:
            class ScienceIssueList(BaseModel):
                issues: list[ScienceIssue] = []
            return ScienceIssueList(issues=[])  # type: ignore

        # Fallback generico per qualsiasi altro modello
        try:
            return response_model.model_validate({})
        except Exception as e:
            raise LLMError(f"Impossibile generare mock per il modello {model_name}: {e}")
