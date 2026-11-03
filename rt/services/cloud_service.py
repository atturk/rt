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
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CATALOG_TTL = 600  # secondi
# Stima di una lezione rielaborata, per il costo a lezione mostrato nell'app.
LESSON_INPUT_TOKENS = 250_000
LESSON_OUTPUT_TOKENS = 60_000
TIMEOUT = 15
# Fasi di testo, assegnate al primo modello del pool. La descrizione delle immagini va al
# modello con visione, se il backend ne indica uno; le infografiche restano manuali.
AUTO_PHASES = ("outline", "rewrite", "review", "recall",
               "enrichment_writer", "enrichment_visualizer")
VISION_PHASE = "image_description"


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


def topup(amount_cents: int) -> str:
    """Pagina di pagamento di una ricarica extra (importo in centesimi di euro)."""
    return _request("POST", "/v1/topup", {"amount_cents": amount_cents}, token=_require_token())["url"]


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


def _install_key(project_root: Path, key: str, models: list[str], assign_all: bool,
                 vision_model: Optional[str] = None) -> None:
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
    targets = [(job, models[0]) for job in AUTO_PHASES]
    if vision_model:
        targets.append((VISION_PHASE, vision_model))
    for job, model in targets:
        current, _ = conn.phase_selection(project_root, job, connections)
        if assign_all or current is None:
            conn.assign_phase(project_root, job, CONNECTION_NAME, model)


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
        _install_key(project_root, key, list(me.get("models") or []), assign_all, me.get("vision_model"))
    return status(project_root, me=me)


def status(project_root: Path, me: Optional[dict] = None) -> dict:
    """Stato per la web app. Non contiene mai la chiave OpenRouter né il token."""
    available = base_url() is not None
    token = _token() if available else None
    out: dict = {"available": available, "logged_in": False, "email": None,
                 "subscription": None, "topup": None, "balance": None,
                 "connection": _connection_exists(project_root)}
    if not token:
        return out
    if me is None:
        try:
            me = _request("GET", "/v1/me", token=token)
        except CloudError as exc:
            if exc.status == 401:
                return out
            raise
    out.update(logged_in=True, email=me.get("email"), subscription=me.get("subscription"), topup=me.get("topup"),
               pool=_pool(me), vision_model=me.get("vision_model"), current_model=_current_model(project_root))
    sub = me.get("subscription") or {}
    has_topup = ((me.get("topup") or {}).get("balance_usd") or 0) > 0
    if sub.get("status") in ("active", "canceled") or has_topup:
        key = _connection_key(project_root)
        out["balance"] = _balance(key) if key else None
    return out


def _pool(me: dict) -> list[dict]:
    """Modelli consigliati dal backend; con un backend vecchio solo gli id."""
    pool = me.get("model_pool")
    if isinstance(pool, list) and pool:
        return [{"id": str(m["id"]), "label": str(m.get("label") or m["id"]), "note": m.get("note"),
                 "recommended": bool(m.get("recommended"))} for m in pool if isinstance(m, dict) and m.get("id")]
    return [{"id": m, "label": m, "note": None, "recommended": i == 0} for i, m in enumerate(me.get("models") or [])]


def _current_model(project_root: Path) -> Optional[str]:
    """Il modello che RT Cloud usa per la rielaborazione, se la fase è su RT Cloud."""
    from rt.services.connections_service import phase_selection
    connection, model = phase_selection(project_root, "rewrite")
    return model if connection == CONNECTION_NAME else None


def choose_model(project_root: Path, model: str) -> dict:
    """Porta le fasi di testo su un modello (del pool o del catalogo) della connessione RT Cloud."""
    from rt.services import connections_service as conn
    if not _connection_exists(project_root):
        raise CloudError(409, "cloud_not_connected", "Prima collega RT Cloud con Aggiorna.")
    try:
        model = conn.add_model(project_root, CONNECTION_NAME, model)
        for job in AUTO_PHASES:
            conn.assign_phase(project_root, job, CONNECTION_NAME, model)
    except ValueError as exc:
        raise CloudError(400, "invalid_model", str(exc))
    return status(project_root)


_catalog_cache: dict = {"at": 0.0, "models": None}


def _per_million(value: Any) -> Optional[float]:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def catalog(capability: str = "text") -> list[dict]:
    """Catalogo pubblico di OpenRouter, filtrato per capacità: text, vision o image."""
    import time
    if capability not in ("text", "vision", "image"):
        raise CloudError(400, "invalid_capability", "Capacità non valida.")
    now = time.time()
    if _catalog_cache["models"] is None or now - _catalog_cache["at"] > CATALOG_TTL:
        try:
            resp = requests.get(OPENROUTER_MODELS_URL, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json().get("data") or []
        except (requests.RequestException, ValueError):
            raise CloudError(502, "catalog_unreachable", "Non riesco a leggere il catalogo di OpenRouter.")
        models = []
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            arch = item.get("architecture") or {}
            inputs = [str(x) for x in arch.get("input_modalities") or []]
            outputs = [str(x) for x in arch.get("output_modalities") or []]
            pricing = item.get("pricing") or {}
            p_in, p_out = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
            lesson = (round((p_in * LESSON_INPUT_TOKENS + p_out * LESSON_OUTPUT_TOKENS) / 1_000_000, 4)
                      if p_in is not None and p_out is not None and p_in >= 0 and p_out >= 0 else None)
            models.append({
                "id": str(item["id"]), "name": str(item.get("name") or item["id"]),
                "input_usd_per_m": p_in, "output_usd_per_m": p_out, "lesson_usd": lesson,
                "text": "text" in outputs, "vision": "image" in inputs, "image_output": "image" in outputs,
            })
        _catalog_cache.update(at=now, models=models)
    models = _catalog_cache["models"]
    if capability == "vision":
        selected = [m for m in models if m["vision"] and m["text"]]
    elif capability == "image":
        selected = [m for m in models if m["image_output"]]
    else:
        selected = [m for m in models if m["text"]]
    return sorted(selected, key=lambda m: (m["lesson_usd"] is None, m["lesson_usd"] or 0, m["id"]))


def plans() -> dict:
    return _request("GET", "/v1/plans")
