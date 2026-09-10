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
import os
import re
import time
import datetime
from typing import Type, TypeVar, Optional, List, Set, Dict, Any
import requests
from pydantic import BaseModel

from rt.core.config import load_config, RouteConfig, JobRoutingConfig
from rt.core.encoding import fix_mojibake, sanitize_object_encoding
from rt.llm.providers import get_provider
from rt.llm.pricing import calculate_cost
from rt.llm.telemetry import LLMTelemetryRecord, GLOBAL_TELEMETRY
from rt.llm.monitor import LiveTerminalMonitor
from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.llm.errors import (
    LLMFailure,
    UserAbortedFailure,
    TimeoutFailure,
    RateLimitFailure,
    SafetyFailure,
    AuthenticationFailure,
    NetworkFailure,
    ProviderServerFailure,
    SchemaFailure,
    OutputLimitFailure,
    ReasoningRequiredFailure,
    SuspiciousFastResponseFailure,
    classify_failure,
    LLMError,
    LLMTimeoutError,
)
from rt.llm.router import RoutingEngine, ExecutionRoute
from rt.core.lesson_paths import lesson_path

T = TypeVar("T", bound=BaseModel)


def _append_debug_log(lesson_dir: Optional[str], entry: Dict[str, Any]) -> None:
    """Scrive una riga di telemetria e contesto in formato JSON Lines su llm_debug.log."""
    if not lesson_dir:
        return
    log_path = lesson_path(lesson_dir, "llm_debug.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Il log di debug non deve mai far fallire la pipeline


def _is_openrouter_free_tier(provider: str, model: str) -> bool:
    p = (provider or "").lower().strip()
    m = (model or "").strip()
    return p == "openrouter" and (m == "openrouter/free" or m.endswith(":free"))


class LLMClient:
    def __init__(self, config_path: Optional[str] = None, force_mock: bool = False):
        self.config = load_config(config_path)
        self.force_mock = force_mock or self.config.mock_llm
        self.router = RoutingEngine(self.config)
        # review_science chiama l'LLM una volta per unità didattica, review_asr una
        # volta per batch di segmenti: senza questo contatore, il mock inietterebbe
        # lo stesso set di ~10 issue di test ad OGNI chiamata, moltiplicandosi per il
        # numero di unità/batch (es. 24 unità -> 240 issue mock). Le issue di test
        # vanno iniettate solo alla prima chiamata per job_name in questa istanza.
        self._mock_issue_calls: Dict[str, int] = {}

    def _get_job_routing_config(self, job_name: str) -> JobRoutingConfig:
        clean = job_name.lower().strip()
        cfg = self.config.jobs.get(clean) or self.config.llm.get(clean)
        if cfg:
            return cfg
        default_cfg = self.config.jobs.get("default") or self.config.llm.get("default")
        if default_cfg:
            return default_cfg
        raise ValueError(
            f"Nessuna configurazione di routing trovata per il job '{job_name}' "
            f"(né una voce dedicata né un job 'default'). Dichiara esplicitamente "
            f"provider e modello in config/{job_name}.yaml sotto 'primary:'. "
            f"Vedi docs/CONFIGURATION_REFERENCE.md."
        )


    def _resolve_custom_pricing(self, route: RouteConfig, provider_name: str, model_name: str) -> Optional[Dict[str, Any]]:
        """Se la route ha un pricing specifico, lo inietta come override esatto per
        (provider_name, model_name) sopra il pricing custom globale — priorità massima,
        nessuna ambiguità di matching perché la chiave è esattamente quella usata."""
        base = dict(self.config.pricing or {})
        if getattr(route, "pricing", None) is not None:
            prov_dict = dict(base.get(provider_name, {}))
            prov_dict[model_name] = route.pricing.model_dump()
            base[provider_name] = prov_dict
        return base or None

    def _resolve_provider_routing(self, route: RouteConfig, provider_name: str) -> Optional[Dict[str, Any]]:
        """Restituisce l'oggetto 'provider' da inviare a OpenRouter per questa route, se impostato.
        Non esiste un default globale: la scelta dei backend affidabili dipende dal modello specifico,
        quindi vive esclusivamente sulla singola route, insieme a provider/model. Si applica solo per
        provider_name == 'openrouter'; per qualunque altro provider restituisce sempre None."""
        if provider_name != "openrouter":
            return None
        return route.provider_routing

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
        timeout_backoff_seconds: Optional[float] = None,
        idle_read_timeout_seconds: Optional[float] = None,
        min_elapsed_seconds: Optional[float] = None,
        lesson_dir: Optional[str] = None
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
            mock_resp = self._generate_mock_response(job_name, prompt, response_model)
            if lesson_dir:
                _append_debug_log(lesson_dir, {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "execution_id": execution_id,
                    "job": job_name,
                    "unit_id": unit_id,
                    "provider": "mock",
                    "model": "mock-deterministic",
                    "resolved_model": "mock-deterministic",
                    "attempt": 1,
                    "route_role": "primary",
                    "status": "success",
                    "elapsed_seconds": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "estimated_cost": 0.0,
                    "finish_reason": "stop",
                    "content_text": getattr(mock_resp, "model_dump_json", lambda: str(mock_resp))()
                })
            return mock_resp

        # Risoluzione route iniziale (con supporto a eventuali override manuali)
        if override_provider or override_model or override_credential:
            prov = (override_provider or (primary_cfg.provider if primary_cfg else None))
            clean_prov = prov.lower().strip() if prov else None
            mod = override_model or (primary_cfg.model if primary_cfg and clean_prov == (primary_cfg.provider or "").lower().strip() else ("gemini-2.5-flash" if clean_prov == "google" else "deepseek-v4-flash"))
            b_url = override_base_url
            if not b_url and clean_prov:
                if primary_cfg and clean_prov == (primary_cfg.provider or "").lower().strip():
                    b_url = primary_cfg.base_url
                elif clean_prov == "google":
                    b_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                elif clean_prov == "openrouter":
                    b_url = "https://openrouter.ai/api/v1"
                elif clean_prov == "deepseek":
                    b_url = "https://api.deepseek.com"
                else:
                    b_url = None

            cred = override_credential or (primary_cfg.credential if primary_cfg and clean_prov == (primary_cfg.provider or "").lower().strip() else None)
            try:
                override_route = RouteConfig(
                    provider=clean_prov,
                    model=mod,
                    credential=cred,
                    base_url=b_url,
                    thinking=primary_cfg.thinking if primary_cfg else True,
                    reasoning_effort=primary_cfg.reasoning_effort if primary_cfg else None,
                    max_thinking_tokens=primary_cfg.max_thinking_tokens if primary_cfg else None,
                    temperature=primary_cfg.temperature if primary_cfg else None,
                    max_tokens=primary_cfg.max_tokens if primary_cfg else None,
                    timeout_seconds=primary_cfg.timeout_seconds if primary_cfg else 180
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
        default_idle_read_timeout = getattr(cfg_retry, "idle_read_timeout_seconds", 45.0) if cfg_retry else 45.0
        route_max_timeout_retries = max_timeout_retries if max_timeout_retries is not None else default_max_timeout_retries
        effective_backoff_sec = timeout_backoff_seconds if timeout_backoff_seconds is not None else default_backoff_sec
        effective_idle_read_timeout = idle_read_timeout_seconds if idle_read_timeout_seconds is not None else default_idle_read_timeout

        # --------------------------------------------------------------------------
        # LOOP PRINCIPALE DI ROUTING (TRANSIZIONE TRA ROUTES E FAILOVER)
        # --------------------------------------------------------------------------
        while route_attempt <= max_global_attempts:
            route = current_exec_route.route
            if not route or not route.is_configured or not route.provider:
                raise LLMError(f"La route per il job '{job_name}' non è configurata (provider o model mancante).")
            route_id = route.route_id
            visited_route_ids.add(route_id)

            provider_name = route.provider.lower().strip()
            model_name = route.model.strip()
            credential_ref = route.credential or GLOBAL_CREDENTIALS.get_default_credential_for_provider(provider_name) or provider_name
            base_url = route.base_url

            # Risoluzione provider adapter
            try:
                provider = get_provider(provider_name)
            except ValueError as ve:
                raise LLMError(f"Provider LLM non riconosciuto: {ve}")

            # Risoluzione credenziali da Registry
            api_key = GLOBAL_CREDENTIALS.get_api_key(credential_ref)
            if not api_key and provider_name != "mock":

                env_var = GLOBAL_CREDENTIALS.get_env_var_name(credential_ref) or f"{provider_name.upper()}_API_KEY"
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
                verbose=getattr(self.config, "show_monitor_verbose", False),
            )

            # Sub-loop per same-route retry (timeout di rete, low-effort reasoning/fast response, output-limit)
            route_timeout_attempt = 0
            total_route_timeout_attempts = 1 + max(0, route_max_timeout_retries)
            route_timeout_retries = 0
            low_effort_strikes = 0
            MAX_LOW_EFFORT_RETRIES = 2  # 1 retry a config invariata + 1 tentativo di escalation con thinking forzato
            output_limit_retries = 0
            MAX_OUTPUT_LIMIT_RETRIES = 2  # fino a 2 retry aggiuntivi sulla stessa route, nessuna modifica ai parametri della richiesta
            force_thinking_override = False

            while route_timeout_attempt < (total_route_timeout_attempts + MAX_LOW_EFFORT_RETRIES + MAX_OUTPUT_LIMIT_RETRIES):
                route_timeout_attempt += 1
                resolved_model = None
                t_attempt_start = time.time()
                t_attempt_monotonic = time.monotonic()
                deadline = (t_attempt_monotonic + timeout_seconds) if (timeout_seconds and timeout_seconds > 0) else None

                if route_timeout_attempt > 1:
                    monitor.reset_for_attempt(call_attempt)

                payload = provider.build_payload(
                    model=model_name,
                    messages=list(messages),
                    max_tokens=route.max_tokens,
                    thinking=(True if force_thinking_override else route.thinking),
                    reasoning_effort=route.reasoning_effort,
                    temperature=route.temperature,
                    response_format={"type": "json_object"},
                    stream=use_stream,
                    max_thinking_tokens=route.max_thinking_tokens,
                    provider_routing=self._resolve_provider_routing(route, provider_name),
                    response_json_schema=response_model.model_json_schema()
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
                        stream_req_timeout = max(0.1, min(rem_sec, effective_idle_read_timeout))
                    else:
                        req_timeout = None
                        stream_req_timeout = None

                    try:
                        if use_stream:
                            post_kwargs = {
                                "headers": headers,
                                "json": payload,
                                "timeout": stream_req_timeout,
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
                            t_last_progress = time.monotonic()

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

                                    if now_mono - t_last_progress > effective_idle_read_timeout:
                                        try:
                                            response.close()
                                        except Exception:
                                            pass
                                        raise TimeoutFailure(
                                            f"Nessun contenuto o reasoning reale ricevuto da oltre {effective_idle_read_timeout:.0f}s, "
                                            f"nonostante il socket resti attivo (probabili keep-alive silenziosi del provider). "
                                            f"Streaming interrotto precauzionalmente.",
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
                                    if chunk.resolved_model:
                                        resolved_model = chunk.resolved_model
                                        monitor.set_resolved_model(resolved_model)
                                    if chunk.content_delta:
                                        content_parts.append(chunk.content_delta)
                                    if chunk.reasoning_delta:
                                        reasoning_parts.append(chunk.reasoning_delta)
                                    if chunk.content_delta or chunk.reasoning_delta:
                                        t_last_progress = now_mono
                                    if chunk.finish_reason:
                                        finish_reason = chunk.finish_reason

                                    # ------------------------------------------------------------------
                                    # OUTPUT EXPLOSION GUARD (Sezione 23 & Revisione Specifica)
                                    # ------------------------------------------------------------------
                                    accumulated_content_chars = sum(len(p) for p in content_parts)
                                    if max_output_chars and accumulated_content_chars > max_output_chars:
                                        try:
                                            response.close()
                                        except Exception:
                                            pass
                                        raise OutputLimitFailure(
                                            f"Output explosion guard attivata: ricevuti {accumulated_content_chars} caratteri, "
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
                                            custom_pricing=self._resolve_custom_pricing(route, provider_name, model_name)
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
                                        if norm.resolved_model:
                                            resolved_model = norm.resolved_model
                                            monitor.set_resolved_model(resolved_model)
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
                            if norm.resolved_model:
                                resolved_model = norm.resolved_model
                                monitor.set_resolved_model(resolved_model)

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

                        elapsed_att = time.time() - t_attempt_start
                        if (
                            min_elapsed_seconds is not None
                            and elapsed_att < min_elapsed_seconds
                            and _is_openrouter_free_tier(provider_name, model_name)
                        ):
                            raise SuspiciousFastResponseFailure(
                                f"Risposta ricevuta in soli {elapsed_att:.2f}s da un modello free-tier ('{model_name}') "
                                f"per il job '{job_name}' (soglia minima: {min_elapsed_seconds}s). "
                                f"Probabile risposta a basso sforzo senza reasoning effettivo, scartata precauzionalmente.",
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
                            custom_pricing=self._resolve_custom_pricing(route, provider_name, model_name)
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
                            resolved_model=resolved_model,
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

                        if lesson_dir:
                            reas_full_text = "".join(reasoning_parts) if ('reasoning_parts' in locals() and reasoning_parts) else (reasoning_content if ('reasoning_content' in locals() and reasoning_content) else None)
                            debug_entry = {
                                "timestamp": datetime.datetime.fromtimestamp(t_attempt_end).isoformat(),
                                "execution_id": execution_id,
                                "job": job_name,
                                "unit_id": unit_id,
                                "provider": provider_name,
                                "model": model_name,
                                "resolved_model": resolved_model,
                                "attempt": call_attempt,
                                "route_role": current_exec_route.route_role,
                                "status": "success",
                                "elapsed_seconds": round(elapsed_att, 4),
                                "input_tokens": in_t,
                                "output_tokens": out_t,
                                "reasoning_tokens": reas_t,
                                "estimated_cost": cost_est,
                                "finish_reason": finish_reason,
                                "reasoning_text": reas_full_text,
                                "content_text": raw_content
                            }
                            _append_debug_log(lesson_dir, debug_entry)

                        if final_usage:
                            monitor.on_usage(final_usage, cost_est)
                        monitor.finish(success=True)

                        return validated_obj

                    except KeyboardInterrupt:
                        if 'response' in locals() and hasattr(response, "close"):
                            try:
                                response.close()
                            except Exception:
                                pass
                        print("\n⚠ Interrotto dall'utente durante lo streaming — passo alla route di fallback (se disponibile)...")
                        attempt_exception = UserAbortedFailure(
                            "Tentativo interrotto manualmente dall'utente (Ctrl+C) durante lo streaming.",
                            provider=provider_name,
                            model=model_name
                        )
                        break
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
                            ReasoningRequiredFailure,
                            SuspiciousFastResponseFailure,
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
                    resolved_model=resolved_model,
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

                if lesson_dir:
                    reas_full_text = "".join(reasoning_parts) if ('reasoning_parts' in locals() and reasoning_parts) else (reasoning_content if ('reasoning_content' in locals() and reasoning_content) else None)
                    err_debug_entry = {
                        "timestamp": datetime.datetime.fromtimestamp(t_attempt_end).isoformat(),
                        "execution_id": execution_id,
                        "job": job_name,
                        "unit_id": unit_id,
                        "provider": provider_name,
                        "model": model_name,
                        "resolved_model": resolved_model,
                        "attempt": call_attempt,
                        "route_role": current_exec_route.route_role,
                        "status": err_status,
                        "elapsed_seconds": round(elapsed_att, 4),
                        "input_tokens": in_t if ('in_t' in locals()) else None,
                        "output_tokens": out_t if ('out_t' in locals()) else None,
                        "reasoning_tokens": reas_t if ('reas_t' in locals()) else None,
                        "estimated_cost": cost_est if ('cost_est' in locals()) else None,
                        "finish_reason": finish_reason,
                        "error_message": classified_failure.message,
                        "reasoning_text": reas_full_text
                    }
                    _append_debug_log(lesson_dir, err_debug_entry)

                # Controllo Same-Route Retry (Timeout, Low-Effort, Output-Limit totalmente indipendenti)
                if isinstance(classified_failure, TimeoutFailure) and route_timeout_retries < max(0, route_max_timeout_retries):
                    route_timeout_retries += 1
                    call_attempt += 1
                    monitor.set_retry_reason("timeout")
                    monitor.log_timeout(elapsed_att, next_attempt=call_attempt)
                    backoff = min(30.0, effective_backoff_sec * (2 ** (route_timeout_retries - 1)))
                    time.sleep(backoff)
                    continue
                elif (
                    isinstance(classified_failure, (ReasoningRequiredFailure, SuspiciousFastResponseFailure))
                    and low_effort_strikes < MAX_LOW_EFFORT_RETRIES
                ):
                    low_effort_strikes += 1
                    escalate_now = low_effort_strikes >= MAX_LOW_EFFORT_RETRIES and not force_thinking_override
                    if escalate_now:
                        force_thinking_override = True
                    call_attempt += 1
                    fail_label = "suspicious_fast_response" if isinstance(classified_failure, SuspiciousFastResponseFailure) else "reasoning_required"
                    reason_label = f"{fail_label}_escalation" if force_thinking_override else fail_label
                    monitor.set_retry_reason(fail_label)
                    monitor.log_retry(
                        reason=reason_label,
                        elapsed=elapsed_att,
                        next_attempt=call_attempt
                    )
                    time.sleep(1.5)
                    continue
                elif isinstance(classified_failure, OutputLimitFailure) and output_limit_retries < MAX_OUTPUT_LIMIT_RETRIES:
                    output_limit_retries += 1
                    call_attempt += 1
                    monitor.set_retry_reason("output_limit")
                    monitor.log_retry(reason="output_limit_retry", elapsed=elapsed_att, next_attempt=call_attempt)
                    time.sleep(1.5)
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
            ScienceIssue,
            RecallQuestion,
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
            self._mock_issue_calls["review_asr"] = self._mock_issue_calls.get("review_asr", 0) + 1
            if self._mock_issue_calls["review_asr"] > 1:
                return ASRIssueList(issues=[])  # type: ignore

            seg_matches = re.findall(r"seg_\d{6}", prompt)
            if not seg_matches:
                seg_matches = ["seg_000001"]

            # Mix di GREEN (auto-applicate), YELLOW e RED (10 issue totali, solo alla prima chiamata)
            asr_specs = [
                (ASRLevel.GREEN, 0.98, "accepted"),
                (ASRLevel.YELLOW, 0.85, "pending"),
                (ASRLevel.RED, 0.65, "pending"),
                (ASRLevel.GREEN, 0.95, "accepted"),
                (ASRLevel.YELLOW, 0.82, "pending"),
                (ASRLevel.RED, 0.60, "pending"),
                (ASRLevel.GREEN, 0.92, "accepted"),
                (ASRLevel.YELLOW, 0.78, "pending"),
                (ASRLevel.RED, 0.55, "pending"),
                (ASRLevel.YELLOW, 0.80, "pending"),
            ]
            mock_issues = []
            for i, (lvl, conf, st) in enumerate(asr_specs, start=1):
                seg_id = seg_matches[(i - 1) % len(seg_matches)]
                mock_issues.append(
                    ASRIssue(
                        id=f"asr_{i:06d}",
                        segment_id=seg_id,
                        source_text=f"[MOCK] trascrizione_errata_{i}",
                        candidate=f"[MOCK] Correzione Trascrizione {i}",
                        confidence=conf,
                        level=lvl,
                        reason=f"[MOCK] Motivazione fonetica per anomalia ASR #{i} ({lvl.value})",
                        status=st
                    )
                )
            return ASRIssueList(issues=mock_issues)  # type: ignore

        elif model_name == "ScienceIssueList" or "ScienceIssue" in model_name:
            from rt.core.models import ScienceType, ScienceSeverity
            class ScienceIssueList(BaseModel):
                issues: list[ScienceIssue] = []

            self._mock_issue_calls["review_science"] = self._mock_issue_calls.get("review_science", 0) + 1
            if self._mock_issue_calls["review_science"] > 1:
                return ScienceIssueList(issues=[])  # type: ignore

            u_match = re.search(r"UNITÀ:\s*([0-9.]+)", prompt)
            unit_id = u_match.group(1) if u_match else "1.1"

            seg_matches = re.findall(r"seg_\d{6}", prompt)
            if not seg_matches:
                seg_matches = ["seg_000001"]

            src_match = re.search(r"TRASCRIZIONE SORGENTE.*:\s*\n(.*)", prompt, re.DOTALL)
            src_snippet = ""
            if src_match:
                clean_lines = [re.sub(r"^\[seg_\d+\]\s*", "", l).strip() for l in src_match.group(1).split("\n") if l.strip()]
                if clean_lines:
                    src_snippet = clean_lines[0]
            if not src_snippet:
                src_snippet = "[MOCK] Citazione sorgente docente"

            # Mix dei 3 tipi: ERR_DOCENTE, ERR_RECONSTRUCTION, SCIENCE_CHECK (10 issue totali)
            sci_specs = [
                (ScienceType.ERR_DOCENTE, ScienceSeverity.HIGH, src_snippet, "Professore, intendeva confermare questo passaggio?"),
                (ScienceType.ERR_RECONSTRUCTION, ScienceSeverity.MEDIUM, None, None),
                (ScienceType.SCIENCE_CHECK, ScienceSeverity.LOW, None, None),
                (ScienceType.ERR_DOCENTE, ScienceSeverity.MEDIUM, src_snippet, "Professore, nel passaggio si riferiva al cofattore indicato?"),
                (ScienceType.ERR_RECONSTRUCTION, ScienceSeverity.HIGH, None, None),
                (ScienceType.SCIENCE_CHECK, ScienceSeverity.MEDIUM, None, None),
                (ScienceType.ERR_DOCENTE, ScienceSeverity.LOW, src_snippet, "Professore, si intendeva il valore di riferimento citato?"),
                (ScienceType.ERR_RECONSTRUCTION, ScienceSeverity.LOW, None, None),
                (ScienceType.SCIENCE_CHECK, ScienceSeverity.HIGH, None, None),
                (ScienceType.ERR_RECONSTRUCTION, ScienceSeverity.MEDIUM, None, None),
            ]

            mock_issues = []
            for i, (sci_type, sev, quote, dq) in enumerate(sci_specs, start=1):
                seg_id = seg_matches[(i - 1) % len(seg_matches)]
                mock_issues.append(
                    ScienceIssue(
                        id=f"sci_{i:06d}",
                        type=sci_type,
                        severity=sev,
                        unit_id=unit_id,
                        segment_id=seg_id,
                        claim=f"[MOCK] Affermazione scientifica analizzata #{i}",
                        source_quote=quote,
                        reason=f"[MOCK] Critica scientifica #{i} di tipo {sci_type.value}",
                        suggested_fix=f"[MOCK] Correzione scientifica proposta #{i}",
                        diplomatic_question=dq,
                        status="pending"
                    )
                )
            return ScienceIssueList(issues=mock_issues)  # type: ignore

        elif model_name == "RecallQuestion":
            from rt.core.models import RecallQuestionType

            u_match = re.search(r"UNIT[ÀA]:\s*([\w.]+)", prompt)
            unit_id = u_match.group(1) if u_match else "1.1"
            jn = job_name or ""

            if "quiz" in jn:
                qtype = RecallQuestionType.QUIZ
                options = ["[MOCK] Opzione A (corretta)", "[MOCK] Opzione B", "[MOCK] Opzione C", "[MOCK] Opzione D"]
                correct_index = 0
                pregenerated = "[MOCK] L'opzione A e' corretta perche'... Le altre tre sono sbagliate perche'..."
            elif "vasta" in jn:
                qtype = RecallQuestionType.VASTA
                options = None
                correct_index = None
                pregenerated = "[MOCK] Scaletta ideale: 1) Punto essenziale; 2) Punto essenziale; 3) Punto essenziale."
            else:
                qtype = RecallQuestionType.MIRATA
                options = None
                correct_index = None
                pregenerated = None

            return RecallQuestion(  # type: ignore
                id="recall_mock",
                type=qtype,
                unit_ids=[unit_id],
                question_text="[MOCK] Domanda generata automaticamente per test offline.",
                options=options,
                correct_index=correct_index,
                pregenerated_material=pregenerated,
            )

        elif model_name == "RecallEvalMirataResult":
            return response_model(  # type: ignore
                correttezza=75, completezza=70,
                commento="[MOCK] Risposta plausibile ma incompleta rispetto al riferimento.",
            )

        elif model_name == "RecallEvalVastaResult":
            return response_model(  # type: ignore
                commento="[MOCK] Risposta concettualmente corretta, ma non copre tutti i punti della scaletta ideale.",
            )

        # Fallback generico per qualsiasi altro modello
        try:
            return response_model.model_validate({})
        except Exception as e:
            raise LLMError(f"Impossibile generare mock per il modello {model_name}: {e}")
