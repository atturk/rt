"""
rt.core.searxng_client
Client HTTP minimale per la ricerca immagini via un'istanza SearXNG self-hosted (RT non ne
include una: è un prerequisito esterno, il cui URL si imposta nella web in Impostazioni › Ricerca
web oppure come searxng_base_url in general.yaml).
"""
from dataclasses import dataclass
from typing import List, Optional
import requests


JSON_FORMAT_DISABLED = (
    "SearXNG non restituisce risultati in formato JSON: nel file settings.yml di SearXNG aggiungi "
    "json all'elenco search.formats (accanto a html) e riavvia SearXNG."
)


@dataclass
class WebImageResult:
    image_url: str
    title: str
    source_page_url: str


def search_images(base_url: str, query: str, count: int = 5, timeout: float = 15.0) -> List[WebImageResult]:
    """Interroga l'endpoint /search di SearXNG con categoria 'images' e format=json.
    Solleva ValueError se base_url non è raggiungibile o risponde con errore. Ritorna al
    massimo 'count' risultati."""
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/search",
            params={"q": query, "categories": "images", "format": "json"},
            timeout=timeout,
        )
    except Exception as e:
        raise ValueError(f"Impossibile raggiungere SearXNG su '{base_url}': {e}")
    if resp.status_code == 403:
        # SearXNG risponde 403 quando il formato json non è tra quelli abilitati.
        raise ValueError(JSON_FORMAT_DISABLED)
    if resp.status_code != 200:
        raise ValueError(f"SearXNG ha risposto con status {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        raise ValueError(JSON_FORMAT_DISABLED)
    if not isinstance(data, dict):
        raise ValueError("Risposta di SearXNG non riconosciuta.")
    results = []
    for item in data.get("results", [])[:count]:
        img_url = item.get("img_src") or item.get("url")
        if not img_url:
            continue
        results.append(WebImageResult(
            image_url=img_url,
            title=item.get("title", ""),
            source_page_url=item.get("url", ""),
        ))
    return results


def download_image(url: str, timeout: float = 15.0) -> bytes:
    """Scarica i byte grezzi di un'immagine da un URL. Solleva ValueError se il download
    fallisce o lo status non è 200."""
    try:
        resp = requests.get(url, timeout=timeout)
    except Exception as e:
        raise ValueError(f"Download immagine fallito ({e}): {url}")
    if resp.status_code != 200:
        raise ValueError(f"Download immagine fallito (status {resp.status_code}): {url}")
    return resp.content
