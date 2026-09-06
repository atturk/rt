"""
rt.llm.credentials
Registro centralizzato delle credenziali per l'infrastruttura multi-provider di RT 2.0.

Disaccoppia esplicitamente:
- provider (openrouter, deepseek, google, mock)
- credential (google_1, google_2, openrouter, deepseek, mock)
- model

RISPETTO RIGOROSO DEI VINCOLI DI SICUREZZA:
- Le chiavi provengono ESCLUSIVAMENTE da environment variables o file .env locale.
- google_1 e google_2 sono progetti Google indipendenti con quote e chiavi distinte.
- Nessun secret viene mai salvato o stampato in chiaro nei log, eccezioni o telemetria.
"""

import os
import re
from typing import Dict, Optional
from pydantic import BaseModel, Field


class CredentialRef(BaseModel):
    """Riferimento simbolico immutabile a una credenziale di accesso."""
    name: str = Field(description="Identificativo simbolico della credenziale (es. 'google_1', 'google_2')")
    provider: str = Field(description="Provider associato (es. 'google', 'openrouter', 'deepseek', 'mock')")
    env_var: Optional[str] = Field(default=None, description="Nome della variabile d'ambiente da cui attingere")


class CredentialRegistry:
    """Registry centralizzato per la risoluzione sicura e validata delle credenziali."""

    def __init__(self):
        self._credentials: Dict[str, CredentialRef] = {}
        self._provider_defaults: Dict[str, str] = {}
        self._register_default_credentials()

    def _register_default_credentials(self) -> None:
        """Registra i riferimenti standard supportati da RT 2.0."""
        defaults = [
            CredentialRef(name="openrouter", provider="openrouter", env_var="OPENROUTER_API_KEY"),
            CredentialRef(name="deepseek", provider="deepseek", env_var="DEEPSEEK_API_KEY"),
            CredentialRef(name="google_1", provider="google", env_var="GOOGLE_API_KEY_1"),
            CredentialRef(name="google_2", provider="google", env_var="GOOGLE_API_KEY_2"),
            CredentialRef(name="mock", provider="mock", env_var=None),
        ]
        for ref in defaults:
            self.register(ref)

        # Assegnazione credential di default per provider
        self._provider_defaults["openrouter"] = "openrouter"
        self._provider_defaults["deepseek"] = "deepseek"
        self._provider_defaults["google"] = "google_1"
        self._provider_defaults["mock"] = "mock"

    def register(self, ref: CredentialRef, set_default_for_provider: bool = False) -> None:
        """Registra o estende una credenziale configurata."""
        clean_name = ref.name.lower().strip()
        clean_provider = ref.provider.lower().strip()
        ref_normalized = CredentialRef(name=clean_name, provider=clean_provider, env_var=ref.env_var)
        self._credentials[clean_name] = ref_normalized
        if set_default_for_provider or clean_provider not in self._provider_defaults:
            self._provider_defaults[clean_provider] = clean_name

    def get_default_credential_for_provider(self, provider: str) -> Optional[str]:
        return self._provider_defaults.get(provider.lower().strip())

    def validate_credential(self, provider: str, credential_name: str) -> bool:
        """Valida a livello di configurazione che la credenziale esista e appartenga al provider specificato."""
        clean_p = provider.lower().strip()
        clean_c = credential_name.lower().strip()
        ref = self._credentials.get(clean_c)
        if not ref:
            return False
        return ref.provider == clean_p

    def reload_from_env(self) -> None:
        """Ricarica le variabili d'ambiente (idempotente)."""
        from rt.core.config import load_env_file
        load_env_file()

    def get_api_key(self, credential_name: str) -> Optional[str]:
        """
        Recupera il valore della chiave API esclusivamente dall'ambiente.
        Restituisce None se non impostata o non configurata.
        """
        from rt.core.config import load_env_file
        load_env_file()

        clean_c = credential_name.lower().strip()
        ref = self._credentials.get(clean_c)
        if not ref:
            # Fallback retrocompatibile: se clean_c è un provider registrato, prova la default
            if clean_c in self._provider_defaults:
                ref = self._credentials.get(self._provider_defaults[clean_c])
            elif f"{clean_c.upper()}_API_KEY" in os.environ:
                return os.environ.get(f"{clean_c.upper()}_API_KEY")

        if not ref or not ref.env_var:
            return None

        val = os.environ.get(ref.env_var)
        if val:
            return val.strip()

        # Compatibilità speciale Google: fallback su GEMINI_API_KEY o GOOGLE_API_KEY per google_1
        if ref.name == "google_1":
            if "GEMINI_API_KEY" in os.environ:
                return os.environ["GEMINI_API_KEY"].strip()
            if "GOOGLE_API_KEY" in os.environ:
                return os.environ["GOOGLE_API_KEY"].strip()

        return None

    def sanitize_secrets(self, text: str) -> str:
        """Sanitizza qualsiasi testo rimuovendo chiavi e token di autorizzazione."""
        if not text:
            return text

        sanitized = text

        # 1. Redazione valori specifici correnti caricati in memoria se presenti
        for ref in self._credentials.values():
            if ref.env_var and ref.env_var in os.environ:
                secret_val = os.environ[ref.env_var].strip()
                if len(secret_val) >= 8:
                    sanitized = sanitized.replace(secret_val, f"[REDACTED:{ref.name}]")

        # 2. Redazione Authorization Bearer (inclusi token precedentemente etichettati)
        sanitized = re.sub(r"Bearer\s+([^\s,;\"']+)", "Bearer [REDACTED]", sanitized)
        # 3. Redazione generica chiavi OpenAI / OpenRouter / DeepSeek sk-...
        sanitized = re.sub(r"(sk-[A-Za-z0-9_\-\.]{8,})", "[REDACTED_KEY]", sanitized)
        # 4. Redazione generica chiavi Google AI Studio / Cloud (AIzaSy...)
        sanitized = re.sub(r"(AIzaSy[A-Za-z0-9_\-]{30,})", "[REDACTED_GOOGLE_KEY]", sanitized)

        return sanitized


# Istanza singleton globale del registry
GLOBAL_CREDENTIALS = CredentialRegistry()
