"""
rt.llm.router
Routing Engine centralizzato per il substrato LLM di RT 2.0.

Responsabilità:
- Selezione deterministica della route iniziale (Scheduling Policy: primary vs round-robin);
- Selezione deterministica della route di failover (Failure Policy: mapping puntuale error_class -> fallback);
- Loop Protection rigida: rilevamento route già visitate ({provider}|{model}|{credential});
- Bounded attempts per catena di esecuzione;
- Disaccoppiamento totale dalla logica interna dei job cognitivi (outline, rewrite, asr, science).
"""

import threading
from typing import Dict, Optional, Set
from pydantic import BaseModel

from rt.core.config import RTConfig, JobRoutingConfig, RouteConfig
from rt.llm.errors import (
    LLMFailure,
    TimeoutFailure,
    RateLimitFailure,
    SafetyFailure,
    AuthenticationFailure,
    ProviderServerFailure,
    NetworkFailure,
    SchemaFailure,
    OutputLimitFailure
)


class ExecutionRoute(BaseModel):
    """Rappresentazione immutabile della route scelta per uno specifico attempt."""
    route: RouteConfig
    route_role: str  # "primary" | "secondary" | "fallback_timeout" | "fallback_rate_limit" | "fallback_safety" | "fallback_auth" | "fallback_generic"
    fallback_reason: Optional[str] = None

    @property
    def route_id(self) -> str:
        return self.route.route_id

    @property
    def provider(self) -> str:
        return self.route.provider

    @property
    def model(self) -> str:
        return self.route.model

    @property
    def credential(self) -> Optional[str]:
        return self.route.credential


class RoutingEngine:
    """Motore di instradamento multi-provider con round-robin e failover error-aware."""

    def __init__(self, config: RTConfig):
        self.config = config
        self._rr_counters: Dict[str, int] = {}
        self._lock = threading.Lock()

    def _get_job_config(self, job_name: str) -> JobRoutingConfig:
        clean_name = job_name.lower().strip()
        job_cfg = self.config.jobs.get(clean_name) or self.config.llm.get(clean_name)
        if job_cfg:
            return job_cfg
        default_job = self.config.jobs.get("default") or self.config.llm.get("default")
        if default_job:
            return default_job
        # Fallback di sicurezza: route standard deepseek
        return JobRoutingConfig(
            primary=RouteConfig(provider="deepseek", model="deepseek-v4-flash")
        )

    def is_route_available(self, route: RouteConfig) -> bool:
        """
        Hook per future estensioni QuotaManager / HealthManager / CircuitBreaker.
        Restituisce True se la risorsa è attualmente sana e disponibile.
        """
        return True

    def select_initial_route(self, job_name: str) -> ExecutionRoute:
        """
        Policy di Scheduling a condizioni normali:
        - Se round_robin è True e secondary è presente, alterna primary e secondary.
        - Se round_robin è False, seleziona sempre primary.
        """
        job_cfg = self._get_job_config(job_name)

        if job_cfg.round_robin and job_cfg.secondary:
            with self._lock:
                count = self._rr_counters.get(job_name, 0)
                self._rr_counters[job_name] = count + 1

            if count % 2 == 0:
                return ExecutionRoute(route=job_cfg.primary, route_role="primary")
            else:
                return ExecutionRoute(route=job_cfg.secondary, route_role="secondary")

        return ExecutionRoute(route=job_cfg.primary, route_role="primary")

    def get_primary_route(self, job_name: str) -> ExecutionRoute:
        """Alias retrocompatibile per select_initial_route."""
        return self.select_initial_route(job_name)

    def select_fallback_route(
        self,
        job_name: str,
        failure: LLMFailure,
        visited_route_ids: Set[str],
        current_attempt: int
    ) -> Optional[ExecutionRoute]:
        """
        Policy di Failover dopo un'anomalia:
        - Verifica il cap globale max_attempts;
        - Mappa la classe di errore sullo slot di fallback configurato;
        - Applica loop protection impedendo la selezione di route già visitate.
        """
        job_cfg = self._get_job_config(job_name)

        # 1. Bounded execution cap
        if current_attempt >= job_cfg.max_attempts:
            return None

        fallback_map = job_cfg.fallback
        candidate_route: Optional[RouteConfig] = None
        role_tag: str = "fallback_generic"
        reason_tag: str = "generic"

        # 2. Selezione route in base alla classe di errore
        if isinstance(failure, TimeoutFailure):
            reason_tag = "timeout"
            role_tag = "fallback_timeout"
            candidate_route = fallback_map.timeout or fallback_map.generic

        elif isinstance(failure, RateLimitFailure):
            reason_tag = "rate_limit"
            role_tag = "fallback_rate_limit"
            candidate_route = fallback_map.rate_limit or fallback_map.generic

        elif isinstance(failure, SafetyFailure):
            reason_tag = "safety"
            role_tag = "fallback_safety"
            candidate_route = fallback_map.safety or fallback_map.generic

        elif isinstance(failure, AuthenticationFailure):
            reason_tag = "auth"
            role_tag = "fallback_auth"
            # Per auth error si usa esclusivamente fallback.auth (cambio credenziale/provider esplicito)
            candidate_route = fallback_map.auth

        elif isinstance(failure, (ProviderServerFailure, NetworkFailure, SchemaFailure, OutputLimitFailure)):
            reason_tag = failure.failure_class
            role_tag = "fallback_generic"
            candidate_route = fallback_map.generic

        else:
            reason_tag = "generic"
            role_tag = "fallback_generic"
            candidate_route = fallback_map.generic

        # 3. Loop Protection con fallback a cascata generalizzata:
        # Se la route candidata non esiste o è già stata visitata o non disponibile:
        # cerca una route alternativa configurata -> quindi generic -> quindi termina.
        if not candidate_route or candidate_route.route_id in visited_route_ids or not self.is_route_available(candidate_route):
            alternative_route: Optional[RouteConfig] = None
            alt_role: str = role_tag
            alt_reason: str = reason_tag

            # 3a. Cerca una route alternativa configurata non ancora visitata
            configured_candidates = []
            if job_cfg.primary:
                configured_candidates.append(job_cfg.primary)
            if job_cfg.secondary:
                configured_candidates.append(job_cfg.secondary)
            if job_cfg.primary_routes:
                for r in job_cfg.primary_routes:
                    if r not in configured_candidates:
                        configured_candidates.append(r)

            for cand in configured_candidates:
                if cand.route_id in visited_route_ids:
                    continue
                if not self.is_route_available(cand):
                    continue
                # Se è un errore di Safety, non selezionare route dello stesso provider
                if isinstance(failure, SafetyFailure):
                    failed_prov = getattr(failure, "provider", None) or (candidate_route.provider if candidate_route else None)
                    if failed_prov and cand.provider == failed_prov:
                        continue
                # Se è un errore di Auth, non selezionare route con la stessa credenziale
                if isinstance(failure, AuthenticationFailure):
                    failed_cred = getattr(candidate_route, "credential", None)
                    if failed_cred and cand.credential == failed_cred:
                        continue

                alternative_route = cand
                alt_role = "fallback_alternative_configured"
                alt_reason = f"{reason_tag}_alternative_configured"
                break

            # 3b. Se non trovata o non applicabile, cerca in fallback.generic
            if not alternative_route and fallback_map.generic:
                if fallback_map.generic.route_id not in visited_route_ids and self.is_route_available(fallback_map.generic):
                    safe_for_safety = True
                    if isinstance(failure, SafetyFailure):
                        failed_prov = getattr(failure, "provider", None) or (candidate_route.provider if candidate_route else None)
                        if failed_prov and fallback_map.generic.provider == failed_prov:
                            safe_for_safety = False
                    if safe_for_safety:
                        alternative_route = fallback_map.generic
                        alt_role = "fallback_generic"
                        alt_reason = f"{reason_tag}_fallback_generic"

            # 3c. Se nessuna alternativa valida e non visitata è disponibile, termina la catena
            if not alternative_route:
                return None

            candidate_route = alternative_route
            role_tag = alt_role
            reason_tag = alt_reason

        # 4. Verifica disponibilità finale
        if not self.is_route_available(candidate_route):
            return None

        return ExecutionRoute(
            route=candidate_route,
            route_role=role_tag,
            fallback_reason=reason_tag
        )
