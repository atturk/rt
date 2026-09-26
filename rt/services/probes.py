"""
rt.services.probes
Prove rapide dalla pagina Impostazioni (RT4-FA5): una chiamata minima a connessione e modello
scelti nel form, anche prima di salvarli, e una ricerca immagini di prova su SearXNG. Sono
sincrone e con timeout brevi; l'esito (anche l'errore) è il risultato, sempre sanificato.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

MODEL_TIMEOUT_SECONDS = 20.0
SEARXNG_TIMEOUT_SECONDS = 10.0
_PROMPT = "Rispondi solo: ok"
_MAX_OUTPUT_TOKENS = 16  # alcuni provider rifiutano limiti più bassi


def probes_mocked() -> bool:
    """RT_API_MOCK=1 (server dei test end-to-end): la prova dei modelli non chiama nessun LLM.
    La prova di SearXNG no: i test la fanno contro un SearXNG finto."""
    return os.environ.get("RT_API_MOCK", "").strip().lower() in {"1", "true", "yes"}


def _sanitize(text: str) -> str:
    from rt.services.context import _sanitize as sanitize
    return sanitize(text)


def _provider_error(resp: requests.Response) -> str:
    """Il messaggio d'errore del provider in forma leggibile (OpenAI, OpenRouter, Google)."""
    try:
        data: Any = resp.json()
    except ValueError:
        text = (resp.text or "").strip()
        return text[:300] or (resp.reason or "")
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict):
            message = err.get("message") or err.get("status") or ""
            raw = (err.get("metadata") or {}).get("raw") if isinstance(err.get("metadata"), dict) else None
            if raw and isinstance(raw, str) and raw not in message:
                message = f"{message} ({raw})" if message else raw
            if message:
                return str(message)
        elif isinstance(err, str) and err:
            return err
        if data.get("message"):
            return str(data["message"])
    return str(data)[:300]


def probe_model(project_root: Path | None, connection: str, model: str, mock: bool = False,
                timeout: float | None = None) -> dict[str, Any]:
    """Chiamata minima (prompt di poche parole, pochi token di uscita) alla connessione e al
    modello indicati. Restituisce ok, latenza in millisecondi, stato HTTP e messaggio."""
    from rt.services.connections_service import find_connection
    timeout = timeout or MODEL_TIMEOUT_SECONDS
    model = (model or "").strip()
    if not model:
        raise ValueError("Indica il modello da provare.")
    conn = find_connection(project_root, connection)
    provider_name = (conn.get("provider") or "").strip()
    base = {"connection": conn["name"], "provider": provider_name, "model": model,
            "latency_ms": None, "status_code": None, "reply": None}
    if mock or probes_mocked():
        return {**base, "ok": True, "latency_ms": 0, "message": "Mock: nessuna chiamata di rete."}

    from rt.core.config import load_config
    from rt.llm.credentials import GLOBAL_CREDENTIALS
    from rt.llm.providers import get_provider
    load_config()  # registra le credenziali dichiarate
    provider = get_provider(provider_name)
    keys = [k for k in (GLOBAL_CREDENTIALS.get_api_key(name) for name in conn.get("credentials") or []) if k]
    if not keys:
        return {**base, "ok": False, "message": "Nessuna chiave impostata per questa connessione."}
    payload = provider.build_payload(
        model=model, messages=[{"role": "user", "content": _PROMPT}], max_tokens=_MAX_OUTPUT_TOKENS,
        stream=False,  # niente thinking né temperatura: alcuni modelli rifiutano valori espliciti
    )
    endpoint = provider.get_endpoint(conn.get("base_url") or None)
    started = time.monotonic()
    try:
        resp = requests.post(endpoint, headers=provider.get_headers(keys[0]), json=payload, timeout=timeout)
    except requests.Timeout:
        return {**base, "ok": False, "message": f"Nessuna risposta entro {timeout:.0f} secondi."}
    except requests.RequestException as exc:
        return {**base, "ok": False, "message": _sanitize(f"Server non raggiungibile: {exc}")[:500]}
    latency = round((time.monotonic() - started) * 1000)
    base = {**base, "latency_ms": latency, "status_code": resp.status_code}
    if resp.status_code != 200:
        detail = _sanitize(_provider_error(resp))[:500]
        return {**base, "ok": False, "message": f"Errore del provider (HTTP {resp.status_code}): {detail}"}
    try:
        normalized = provider.normalize_response(resp.json(), model)
    except Exception as exc:  # noqa: BLE001 - risposta 200 ma non nel formato atteso
        return {**base, "ok": False, "message": _sanitize(f"Risposta non valida dal provider: {exc}")[:500]}
    reply = (normalized.content or "").strip()[:80] or None
    return {**base, "ok": True, "reply": reply, "message": "Modello raggiungibile."}


# ---------------------------------------------------------------- SearXNG

def normalize_searxng_url(raw: str) -> str:
    from urllib.parse import urlparse
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Inserisci un URL HTTP valido, per esempio http://localhost:8088.")
    return url


def probe_searxng(base_url: str, mock: bool = False, timeout: float | None = None) -> dict[str, Any]:
    """Ricerca immagini di prova: quanti risultati tornano, o perché non funziona."""
    timeout = timeout or SEARXNG_TIMEOUT_SECONDS
    from rt.core.searxng_client import search_images
    url = normalize_searxng_url(base_url)
    if not url:
        raise ValueError("Inserisci l'URL base di SearXNG.")
    if mock:
        return {"ok": True, "results": 0, "latency_ms": 0, "message": "Mock: nessuna chiamata di rete."}
    started = time.monotonic()
    try:
        results = search_images(url, "cellula", count=100, timeout=timeout)
    except ValueError as exc:
        return {"ok": False, "results": 0, "latency_ms": None, "message": str(exc)[:500]}
    latency = round((time.monotonic() - started) * 1000)
    n = len(results)
    message = (f"SearXNG risponde: {n} immagini per la ricerca di prova." if n
               else "SearXNG risponde ma non ha trovato immagini: controlla che i motori di ricerca immagini siano attivi.")
    return {"ok": n > 0, "results": n, "latency_ms": latency, "message": message}
