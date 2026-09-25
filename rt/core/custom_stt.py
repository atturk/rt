"""Adattatore per endpoint STT OpenAI-compatible con timestamp di segmento."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import requests


def transcribe_custom(audio_path: str, base_url: str | None, model: str | None,
                      timeout_seconds: int = 600) -> dict:
    """Restituisce il formato interno RT (millisecondi) da verbose_json OpenAI."""
    if not base_url or not model:
        raise ValueError("Imposta Base URL e modello STT custom in Configurazione.")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Il Base URL STT deve iniziare con http:// o https://.")
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/audio/transcriptions"):
        endpoint += "/audio/transcriptions"
    headers = {}
    if os.environ.get("RT_STT_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['RT_STT_API_KEY']}"
    try:
        with Path(audio_path).open("rb") as audio:
            response = requests.post(
                endpoint, headers=headers,
                data={"model": model, "response_format": "verbose_json",
                      "timestamp_granularities[]": "segment"},
                files={"file": (Path(audio_path).name, audio)},
                timeout=timeout_seconds,
            )
        response.raise_for_status()
        payload = response.json()
    except (OSError, requests.RequestException, ValueError):
        # Errori HTTP e URL possono includere la chiave: non propagarli nei log.
        raise RuntimeError("La trascrizione STT custom è fallita. Controlla endpoint, modello e log del server STT.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
        raise RuntimeError("Il server STT deve restituire verbose_json con segments e timestamp.")
    segments = []
    for item in payload["segments"]:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
            text = str(item["text"]).strip()
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Un segmento STT non contiene start, end e text validi.") from None
        if not text or start < 0 or end <= start:
            raise RuntimeError("Un segmento STT ha testo o timestamp non validi.")
        segments.append({"startMs": round(start * 1000, 3), "endMs": round(end * 1000, 3),
                         "text": text, "confidence": item.get("confidence")})
    if not segments:
        raise RuntimeError("Il server STT non ha restituito segmenti temporizzati.")
    text = str(payload.get("text") or " ".join(item["text"] for item in segments)).strip()
    return {"rawTranscript": text, "text": text, "transcriptSegments": segments,
            "wordTimestamps": []}
