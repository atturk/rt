"""
rt.services.cloud_service
Modalità facilitata ("RT Cloud"): l'utente accede con un codice via email, si abbona su Polar e
riceve una chiave OpenRouter con un tetto di spesa mensile. Questa chiave diventa una normale
connessione OpenRouter chiamata "RT Cloud", quindi la pipeline non cambia.

Al backend (cartella cloud/ del repository) passano solo email e token di sessione: le lezioni
vanno direttamente da RT a OpenRouter. Il saldo si legge da OpenRouter con la chiave dell'utente.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import requests

# Indirizzo del backend pubblicato. Si può sostituire con RT_CLOUD_URL (test, sandbox).
DEFAULT_CLOUD_URL: Optional[str] = None
TOKEN_SECRET = "RT_CLOUD_TOKEN"
CONNECTION_NAME = "RT Cloud"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
TIMEOUT = 15
# La generazione di infografiche richiede modelli d'immagine: non si assegna in automatico.
AUTO_PHASES = ("outline", "rewrite", "review", "recall", "image_description",
               "enrichment_writer", "enrichment_visualizer")


class CloudError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def base_url() -> Optional[str]:
    url = (os.environ.get("RT_CLOUD_URL") or DEFAULT_CLOUD_URL or "").strip().rstrip("/")
    return url or None


def _token() -> Optional[str]:
    from rt.core.config import load_env_file
    load_env_file()
    value = os.environ.get(TOKEN_SECRET, "").strip()
    return value or None


def _request(method: str, path: str, body: Any = None, token: Optional[str] = None) -> dict:
    url = base_url()
    if not url:
        raise CloudError(503, "cloud_unavailable", "La modalità facilitata non è ancora disponibile.")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.request(method, f"{url}{path}", json=body, headers=headers, timeout=TIMEOUT)
    except requests.RequestException:
        raise CloudError(502, "cloud_unreachable", "RT Cloud non risponde: controlla la connessione.")
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        err = data.get("error") or {}
        status = resp.status_code if resp.status_code in (400, 401, 404, 409, 429) else 502
        raise CloudError(status, f"cloud_{err.get('code') or 'error'}", err.get("message") or "Errore di RT Cloud.")
    return data


def start_login(email: str) -> None:
    _request("POST", "/v1/auth/start", {"email": email})


def verify_login(project_root: Path, email: str, code: str) -> dict:
    from rt.services import config_service
    data = _request("POST", "/v1/auth/verify", {"email": email, "code": code})
    config_service.set_secret(TOKEN_SECRET, data["token"], project_root=project_root)
    os.environ[TOKEN_SECRET] = data["token"]
    return sync(project_root)


def logout(project_root: Path) -> dict:
    from rt.services import config_service
    token = _token()
    if token:
        try:
            _request("POST", "/v1/auth/logout", token=token)
        except CloudError:
            pass  # la sessione locale si chiude comunque
    config_service.unset_secret(TOKEN_SECRET, project_root=project_root)
    os.environ.pop(TOKEN_SECRET, None)
    return status(project_root)


def checkout(plan: Optional[str]) -> str:
    return _request("POST", "/v1/checkout", {"plan": plan} if plan else {}, token=_require_token())["url"]


def portal() -> str:
    return _request("POST", "/v1/portal", token=_require_token())["url"]


def _require_token() -> str:
    token = _token()
    if not token:
        raise CloudError(401, "cloud_login_required", "Accedi a RT Cloud con la tua email.")
    return token


def _connection_exists(project_root: Path) -> bool:
    from rt.services.connections_service import connection_names
    return CONNECTION_NAME in connection_names(project_root)


def _install_key(project_root: Path, key: str, models: list[str], assign_all: bool) -> None:
    """Crea o aggiorna la connessione "RT Cloud" e assegna le fasi.

    assign_all=True (l'utente ha scelto la modalità facilitata) porta tutte le fasi testuali su
    RT Cloud; altrimenti si riempiono solo le fasi ancora senza connessione."""
    from rt.services import connections_service as conn
    from rt.services.settings_service import save_credential
    if _connection_exists(project_root):
        credential = conn.find_connection(project_root, CONNECTION_NAME)["credentials"][0]
        if _connection_key(project_root) != key:
            save_credential(project_root, "openrouter", credential, key)
    else:
        conn.save_connection(project_root, CONNECTION_NAME, "openrouter", "", [key])
        credential = conn.find_connection(project_root, CONNECTION_NAME)["credentials"][0]
    from rt.llm.credentials import GLOBAL_CREDENTIALS
    env_var = GLOBAL_CREDENTIALS.get_env_var_name(credential)
    if env_var:
        os.environ[env_var] = key  # subito disponibile per i job di questo processo
    for model in models:
        conn.add_model(project_root, CONNECTION_NAME, model)
    if not models:
        return
    connections = conn.list_connections(project_root)
    for job in AUTO_PHASES:
        current, _ = conn.phase_selection(project_root, job, connections)
        if assign_all or current is None:
            conn.assign_phase(project_root, job, CONNECTION_NAME, models[0])


def _connection_key(project_root: Path) -> Optional[str]:
    from rt.core.config import get_api_key
    from rt.services.connections_service import find_connection
    try:
        credential = find_connection(project_root, CONNECTION_NAME)["credentials"][0]
    except (ValueError, IndexError, KeyError):
        return None
    return get_api_key(credential)


def _balance(key: str) -> Optional[dict]:
    """Uso e tetto della chiave, letti direttamente da OpenRouter (in USD)."""
    try:
        resp = requests.get(OPENROUTER_KEY_URL, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
    except (requests.RequestException, ValueError):
        return None
    limit = data.get("limit")
    usage = float(data.get("usage") or 0)
    remaining = data.get("limit_remaining")
    if remaining is None and limit is not None:
        remaining = max(0.0, float(limit) - usage)
    return {"limit_usd": limit, "usage_usd": usage, "remaining_usd": remaining}


def sync(project_root: Path, assign_all: bool = False) -> dict:
    """Legge il profilo dal backend e installa la chiave se l'abbonamento è attivo."""
    token = _require_token()
    me = _request("GET", "/v1/me", token=token)
    key = me.get("openrouter_key")
    if key:
        _install_key(project_root, key, list(me.get("models") or []), assign_all)
    return status(project_root, me=me)


def status(project_root: Path, me: Optional[dict] = None) -> dict:
    """Stato per la web app. Non contiene mai la chiave OpenRouter né il token."""
    available = base_url() is not None
    token = _token() if available else None
    out: dict = {"available": available, "logged_in": False, "email": None,
                 "subscription": None, "balance": None, "connection": _connection_exists(project_root)}
    if not token:
        return out
    if me is None:
        try:
            me = _request("GET", "/v1/me", token=token)
        except CloudError as exc:
            if exc.status == 401:
                return out
            raise
    out.update(logged_in=True, email=me.get("email"), subscription=me.get("subscription"))
    sub = me.get("subscription") or {}
    if sub.get("status") in ("active", "canceled"):
        key = _connection_key(project_root)
        out["balance"] = _balance(key) if key else None
    return out


def plans() -> dict:
    return _request("GET", "/v1/plans")
