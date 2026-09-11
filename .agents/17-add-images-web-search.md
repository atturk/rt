# Task 17 — `rt add-images`: ricerca immagini sul web via SearXNG (`--web-search`)

Quinto e ultimo di 5 task sequenziali (13→17). **Richiede che i Task 13-16 siano già
completati** (il comando `rt add-images -i ...` deve già funzionare end-to-end — se
`rt/pipeline/add_images.py::run_add_images`/`rt/cli.py::cmd_add_images` non esistono ancora,
fermati e segnala che le precondizioni non sono soddisfatte).

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

Aggiunge un flag `--web-search N` indipendente da `-i`: cerca N immagini sul web (tramite
un'istanza SearXNG, un motore di metaricerca self-hosted — **prerequisito esterno**: RT non
include e non installa SearXNG, l'utente deve avere/configurare un'istanza propria
raggiungibile via HTTP) e le integra nel documento con lo stesso meccanismo di descrizione
(Task 14, MA con la variante di prompt SENZA contesto lezione — le immagini web non sono
curate) e giudizio (Task 15) delle altre. Uso combinabile con `-i`:
```
rt add-images <cartella> --web-search 5                    # solo 5 immagini cercate sul web
rt add-images <cartella> -i slide.pdf --web-search 5        # slide del PDF + 5 immagini web
```

## Parte 1 — Configurazione SearXNG

In `rt/core/config.py`, `RTConfig`: aggiungi un campo `searxng_base_url: Optional[str] = None`
a livello di configurazione globale (NON sotto `telegram`, è indipendente da Telegram — segui
lo stile degli altri campi opzionali già presenti su `RTConfig`, con `description=` chiara).
Documenta in `config.example/general.yaml` (commentato/con placeholder, es.
`# searxng_base_url: "http://localhost:8080"`) e in `docs/CONFIGURATION_REFERENCE.md`,
spiegando chiaramente che è un prerequisito ESTERNO: l'utente deve installare/avere accesso a
una propria istanza SearXNG (https://docs.searxng.org/) con l'API JSON abilitata, RT si limita
a interrogarla via HTTP.

## Parte 2 — Client SearXNG (`rt/core/searxng_client.py`, nuovo)

```python
"""
rt.core.searxng_client
Client HTTP minimale per la ricerca immagini via un'istanza SearXNG self-hosted (RT non ne
include una: è un prerequisito esterno configurato da searxng_base_url in general.yaml).
"""
import requests
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class WebImageResult:
    image_url: str
    title: str
    source_page_url: str


def search_images(base_url: str, query: str, count: int = 5, timeout: float = 15.0) -> List[WebImageResult]:
    """Interroga l'endpoint /search di SearXNG con categoria 'images' e format=json.
    Solleva ValueError se base_url non è raggiungibile o risponde con errore. Ritorna al
    massimo 'count' risultati. Verifica il formato esatto della risposta JSON di SearXNG
    (campo 'results', ciascuno con 'img_src'/'url'/'title' — la struttura può variare
    leggermente tra versioni, gestisci con .get() difensivo e salta risultati malformati
    invece di sollevare eccezioni su un singolo risultato incompleto)."""
    resp = requests.get(
        f"{base_url.rstrip('/')}/search",
        params={"q": query, "categories": "images", "format": "json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise ValueError(f"SearXNG ha risposto con status {resp.status_code}")
    data = resp.json()
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
    resp = requests.get(url, timeout=timeout)
    if resp.status_code != 200:
        raise ValueError(f"Download immagine fallito ({resp.status_code}): {url}")
    return resp.content
```

## Parte 3 — Derivazione query e distribuzione N immagini

Decisione presa con l'utente: query derivate DETERMINISTICAMENTE (nessuna chiamata LLM) dai
`key_concepts` (campo su `OutlineUnit`, NON sul `title` della macro — spesso un titolo
composito lungo, pessimo come query di ricerca). In `rt/pipeline/add_images.py`:

```python
import math

def build_macro_search_queries(outline) -> Dict[str, str]:
    """Per ogni macro-sezione, unisce (deduplicati, in ordine di comparsa) i key_concepts di
    tutte le sue unità, prende i primi 3 e li unisce in un'unica stringa di query. Ritorna
    {macro_id: query_string}. Macro-sezioni senza alcun key_concept ottengono una query di
    fallback basata sul solo title della macro (troncato/pulito)."""


def fetch_web_images(lesson_dir: str, outline, total_count: int, base_url: str) -> List[ExtractedImage]:
    """Per ogni macro-sezione (build_macro_search_queries), richiede
    ceil(total_count / numero_macro_sezioni) risultati a search_images(), scarica ogni
    immagine con download_image(), etichetta ciascuna con source_label=f"websearch:{query}"
    (Task 14 la riconoscerà dal prefisso 'websearch:' per scegliere il prompt SENZA contesto).
    Alla fine tronca la lista complessiva (in ordine di macro-sezione) a total_count elementi
    esatti. Solleva ValueError con messaggio chiaro se base_url non è configurato quando questa
    funzione viene chiamata."""
```

## Parte 4 — Wiring in CLI e nell'orchestratore

In `rt/cli.py`, sul subparser `add-images` (dal Task 16):
```python
p_addimg.add_argument(
    "--web-search", nargs="?", const=5, type=int, default=None,
    help="Cerca e integra N immagini dal web via SearXNG (default 5 se il flag è usato senza valore). "
         "Combinabile con -i. Richiede 'searxng_base_url' configurato in config/general.yaml."
)
```
(stesso pattern `nargs='?', const=<default>` già usato per `--with-review`/`--reset` in questo
progetto). Aggiorna `cmd_add_images` perché il controllo "nessuna sorgente indicata" diventi
`if not args.input and not args.web_search: ...errore...` (invece del solo controllo su
`args.input` lasciato dal Task 16).

In `run_add_images` (`rt/pipeline/add_images.py`, dal Task 16), aggiungi un parametro
`web_search_count: Optional[int] = None`: se fornito, dopo aver caricato l'outline (serve per
`build_macro_search_queries`) e PRIMA del passo di descrizione, chiama `fetch_web_images(...)`
e unisci il risultato alla lista di immagini da processare (stesso flusso di
partition_new_vs_cached_images → describe_new_images → judge_images_by_macro delle immagini
da `-i`, nessuna diramazione separata nel resto della pipeline — l'unica differenza è la
sorgente e quindi il prompt scelto al Task 14).

## Test

Aggiungi test per: `build_macro_search_queries` (query corrette da key_concepts, fallback su
title se nessun key_concept); `search_images`/`download_image` con `requests` mockato
(risposta SearXNG di esempio, verifica parsing difensivo su risultati malformati);
`fetch_web_images` con distribuzione corretta del conteggio tra macro-sezioni e troncamento
esatto a `total_count`; `cmd_add_images` con solo `--web-search` (senza `-i`) funziona;
`run_add_images` con `web_search_count` integra correttamente immagini web assieme a quelle da
`-i` quando entrambi sono forniti. Esegui `python3 -m pytest tests/ -q` e correggi eventuali
fallimenti tu stesso prima di considerare il task concluso.

## Attenzione — bug di portabilità ricorrente in questo progetto

Più round di task precedenti hanno usato `Optional[...]`/`List[...]`/`Dict[...]` come
annotazione di tipo senza il corrispondente `from typing import ...` in cima al file — funziona
per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito di
default, PEP 649) ma darebbe `NameError` su Python <3.14. Verifica sempre che ogni nome da
`typing` che usi sia importato esplicitamente nel file che lo usa.
