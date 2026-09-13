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

import time
import threading
from typing import Dict, Optional, Set, List, Any
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
        self._consecutive_fallbacks: Dict[str, int] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._last_fallback_execution_id: Dict[str, str] = {}
        self._lock = threading.Lock()

    def _get_job_config(self, job_name: str) -> JobRoutingConfig:
        clean_name = job_name.lower().strip()
        job_cfg = self.config.jobs.get(clean_name) or self.config.llm.get(clean_name)
        if job_cfg:
            return job_cfg
        default_job = self.config.jobs.get("default") or self.config.llm.get("default")
        if default_job:
            return default_job
        raise ValueError(
            f"Nessuna configurazione di routing trovata per il job '{job_name}' "
            f"(né una voce dedicata né un job 'default'). Dichiara esplicitamente "
            f"provider e modello in config/{job_name}.yaml sotto 'primary:'. "
            f"Vedi docs/CONFIGURATION_REFERENCE.md."
        )

    def is_route_available(self, route: RouteConfig) -> bool:
        """
        Hook per future estensioni QuotaManager / HealthManager / CircuitBreaker.
        Restituisce True se la risorsa è attualmente sana e disponibile.
        """
        return True

    def record_success(self, job_name: str, used_fallback: bool = False) -> None:
        """
        Segnala a RoutingEngine che una catena si è conclusa con successo.
        Se risolta senza ricorrere al fallback dedicato (es. tramite il pool round-robin),
        resetta il contatore di fallback consecutivi per il job.
        """
        clean_name = job_name.lower().strip()
        with self._lock:
            if not used_fallback:
                self._consecutive_fallbacks[clean_name] = 0
                self._cooldown_until[clean_name] = 0.0

    def select_initial_route(self, job_name: str) -> ExecutionRoute:
        """
        Policy di Scheduling a condizioni normali:
        - Se round_robin è True, alterna tra le route in primary_routes o tra primary e secondary.
        - Se round_robin è False, seleziona sempre primary.
        """
        job_cfg = self._get_job_config(job_name)

        if job_cfg.round_robin:
            routes = job_cfg.effective_routes
            if len(routes) >= 2:
                with self._lock:
                    count = self._rr_counters.get(job_name, 0)
                    self._rr_counters[job_name] = count + 1
                idx = count % len(routes)
                role = "primary" if idx == 0 else f"round_robin_{idx + 1}"
                return ExecutionRoute(route=routes[idx], route_role=role)

        return ExecutionRoute(route=job_cfg.primary, route_role="primary")

    def select_fallback_route(
        self,
        job_name: str,
        failure: LLMFailure,
        visited_route_ids: Set[str],
        current_attempt: int,
        execution_id: Optional[str] = None
    ) -> Optional[ExecutionRoute]:
        """
        Policy di Failover dopo un'anomalia:
        1. Cap globale max_attempts;
        2. Esaurimento preliminare del pool round-robin (effective_routes non ancora visitate);
        3. Verifica cooldown per fallback consecutivi (se pool esaurito);
        4. Selezione slot di fallback dedicato in base alla classe di errore;
        5. Fallback a cascata (generic) o terminazione.
        """
        job_cfg = self._get_job_config(job_name)
        clean_name = job_name.lower().strip()

        # 1. Bounded execution cap
        if current_attempt >= job_cfg.effective_max_attempts:
            return None

        # Identifica classe e tag di errore
        if isinstance(failure, TimeoutFailure):
            reason_tag = "timeout"
            role_tag = "fallback_timeout"
        elif isinstance(failure, RateLimitFailure):
            reason_tag = "rate_limit"
            role_tag = "fallback_rate_limit"
        elif isinstance(failure, SafetyFailure):
            reason_tag = "safety"
            role_tag = "fallback_safety"
        elif isinstance(failure, AuthenticationFailure):
            reason_tag = "auth"
            role_tag = "fallback_auth"
        elif isinstance(failure, (ProviderServerFailure, NetworkFailure, SchemaFailure, OutputLimitFailure)):
            reason_tag = failure.failure_class
            role_tag = "fallback_generic"
        else:
            reason_tag = "generic"
            role_tag = "fallback_generic"

        # 2. Esaurisci prima il pool round-robin / configured effective routes
        configured_candidates = list(job_cfg.effective_routes)
        for cand in configured_candidates:
            if cand.route_id in visited_route_ids:
                continue
            if not self.is_route_available(cand):
                continue
            # Se è un errore di Safety, non selezionare route dello stesso provider
            if isinstance(failure, SafetyFailure):
                failed_prov = getattr(failure, "provider", None)
                if failed_prov and cand.provider == failed_prov:
                    continue
            # Se è un errore di Auth, non selezionare route con la stessa credenziale
            if isinstance(failure, AuthenticationFailure):
                failed_cred = getattr(failure, "credential", None)
                if failed_cred and cand.credential == failed_cred:
                    continue

            return ExecutionRoute(
                route=cand,
                route_role="fallback_alternative_configured",
                fallback_reason=f"{reason_tag}_alternative_configured"
            )

        # 3. Il pool round-robin è esaurito. Controllo Cooldown su fallback consecutivi
        now = time.monotonic()
        cooldown_sec = getattr(job_cfg.fallback, "cooldown_seconds", 30)

        with self._lock:
            cd_until = self._cooldown_until.get(clean_name, 0.0)
            if now < cd_until:
                # Cooldown attivo: rifiuta immediatamente l'uso del fallback
                return None
            elif cd_until > 0.0:
                # Cooldown precedentemente attivo ed ora scaduto: resetta contatore
                self._consecutive_fallbacks[clean_name] = 0
                self._cooldown_until[clean_name] = 0.0

        # 4. Selezione route dedicata da fallback_map
        fallback_map = job_cfg.fallback
        candidate_route: Optional[RouteConfig] = None

        if isinstance(failure, TimeoutFailure):
            candidate_route = fallback_map.timeout or fallback_map.generic
        elif isinstance(failure, RateLimitFailure):
            candidate_route = fallback_map.rate_limit or fallback_map.generic
        elif isinstance(failure, SafetyFailure):
            candidate_route = fallback_map.safety or fallback_map.generic
        elif isinstance(failure, AuthenticationFailure):
            candidate_route = fallback_map.auth
        elif isinstance(failure, (ProviderServerFailure, NetworkFailure, SchemaFailure, OutputLimitFailure)):
            candidate_route = fallback_map.generic
        else:
            candidate_route = fallback_map.generic

        # 5. Cascata a fallback.generic se la route dedicata non è valida/visitata
        if not candidate_route or candidate_route.route_id in visited_route_ids or not self.is_route_available(candidate_route):
            if fallback_map.generic and fallback_map.generic.route_id not in visited_route_ids and self.is_route_available(fallback_map.generic):
                safe_for_safety = True
                if isinstance(failure, SafetyFailure):
                    failed_prov = getattr(failure, "provider", None)
                    if failed_prov and fallback_map.generic.provider == failed_prov:
                        safe_for_safety = False
                if safe_for_safety:
                    candidate_route = fallback_map.generic
                    role_tag = "fallback_generic"
                    reason_tag = f"{reason_tag}_fallback_generic"
                else:
                    return None
            else:
                return None

        if not self.is_route_available(candidate_route):
            return None

        # 6. Registrazione fallback e eventuale attivazione del cooldown al 2° consecutivo
        with self._lock:
            last_exec = self._last_fallback_execution_id.get(clean_name)
            if execution_id is None or execution_id != last_exec:
                if execution_id:
                    self._last_fallback_execution_id[clean_name] = execution_id
                count = self._consecutive_fallbacks.get(clean_name, 0) + 1
                self._consecutive_fallbacks[clean_name] = count
                if count >= 2:
                    self._cooldown_until[clean_name] = now + cooldown_sec

        return ExecutionRoute(
            route=candidate_route,
            route_role=role_tag,
            fallback_reason=reason_tag
        )
