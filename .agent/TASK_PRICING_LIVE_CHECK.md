Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Verifica prezzi in tempo reale contro il catalogo LiteLLM (diagnostico, non invasivo)

## Contesto

Verificato in sessione: i prezzi hardcoded in `rt/llm/pricing.py` (`DEFAULT_PRICING`) sono stime che possono invecchiare parecchio — confrontando con il catalogo prezzi mantenuto dalla community su [github.com/BerriAI/litellm](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) (progetto open source molto usato, copre le API dirette di ~100 provider, non solo aggregatori), è emerso ad esempio che `gemini-3.5-flash-lite` è stimato a $0.075/$0.30 nel nostro codice contro un prezzo reale attuale di $0.30/$2.50 — una differenza di 4-8x.

**Decisione presa**: non sostituire `DEFAULT_PRICING` né auto-scrivere `rt.config.yaml` in questo task. Sono scelte più grandi (riscrivere un file YAML dell'utente rischia di perdere i commenti — PyYAML non fa round-trip preservandoli, problema già noto in questo progetto) da valutare con calma dopo aver visto se lo strumento diagnostico è davvero utile nell'uso quotidiano. Questo task costruisce solo uno **strumento diagnostico separato, mai invocato automaticamente dalla pipeline** (dipende dalla rete, la pipeline deve restare veloce e tollerante all'offline).

---

## A. Nuovo modulo `rt/llm/pricing_sync.py`

```python
"""
rt.llm.pricing_sync
Verifica diagnostica dei prezzi configurati/hardcoded contro il catalogo prezzi in tempo
reale di LiteLLM (github.com/BerriAI/litellm), community-mantenuto, copre le API dirette
di molti provider (non solo aggregatori). Usato SOLO su richiesta esplicita dell'utente via
CLI (`rt prices-check` / `rt prices-lookup`) — mai invocato automaticamente durante la
pipeline, che deve restare veloce e funzionare offline.
"""

import json
import os
import time
from typing import Optional, Dict, Any, List
import requests

LITELLM_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
CACHE_PATH = os.path.join(os.path.expanduser("~"), ".cache", "rt", "litellm_pricing_cache.json")
CACHE_TTL_SECONDS = 24 * 3600


def load_litellm_catalog(force_refresh: bool = False) -> Dict[str, Any]:
    """Scarica il catalogo prezzi di LiteLLM, con cache locale di 24h per non riscaricare
    ~2.3MB ad ogni invocazione. Solleva l'eccezione originale di 'requests' se la rete
    non è disponibile e non c'è cache valida (nessun fallback silenzioso)."""
    if not force_refresh and os.path.isfile(CACHE_PATH):
        age = time.time() - os.path.getmtime(CACHE_PATH)
        if age < CACHE_TTL_SECONDS:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    resp = requests.get(LITELLM_PRICING_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp_path = CACHE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp_path, CACHE_PATH)
    return data


def lookup_live_price(model_query: str, provider_hint: Optional[str] = None) -> List[Dict[str, Any]]:
    """Cerca nel catalogo LiteLLM tutte le voci il cui nome contiene model_query (case-insensitive),
    opzionalmente filtrate per provider (campo 'litellm_provider' del catalogo, es. 'deepseek', 'gemini').
    Restituisce una lista di dict con chiave, provider, input_per_million, output_per_million
    (già convertiti da costo-per-token a costo-per-milione)."""
    catalog = load_litellm_catalog()
    query = model_query.lower()
    results = []
    for key, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        if query not in key.lower():
            continue
        if provider_hint and entry.get("litellm_provider", "").lower() != provider_hint.lower():
            continue
        in_cost = entry.get("input_cost_per_token")
        out_cost = entry.get("output_cost_per_token")
        if in_cost is None and out_cost is None:
            continue
        results.append({
            "key": key,
            "provider": entry.get("litellm_provider"),
            "input_per_million": round(in_cost * 1_000_000, 6) if in_cost is not None else None,
            "output_per_million": round(out_cost * 1_000_000, 6) if out_cost is not None else None,
        })
    return results


def collect_configured_routes(cfg: "RTConfig") -> List[Dict[str, Optional[str]]]:
    """Enumera tutte le route effettivamente configurate in tutti i job (primary, secondary,
    primary_routes, e ogni voce di fallback), deduplicate per (provider, model)."""
    seen = set()
    routes = []
    for job_name, job_cfg in cfg.jobs.items():
        candidates = []
        if job_cfg.primary:
            candidates.append(job_cfg.primary)
        if job_cfg.secondary:
            candidates.append(job_cfg.secondary)
        if job_cfg.primary_routes:
            candidates.extend(job_cfg.primary_routes)
        for fb_field in ("timeout", "rate_limit", "safety", "auth", "generic"):
            fb_route = getattr(job_cfg.fallback, fb_field, None)
            if fb_route:
                candidates.append(fb_route)
        for route in candidates:
            key = (route.provider.lower().strip(), route.model.lower().strip().lstrip("~"))
            if key in seen:
                continue
            seen.add(key)
            routes.append({"job": job_name, "provider": key[0], "model": key[1]})
    return routes


def check_configured_pricing(cfg: "RTConfig") -> List[Dict[str, Any]]:
    """Per ogni route configurata, confronta il prezzo attualmente USATO dalla pipeline
    (rt.config.yaml 'pricing:' se presente, altrimenti DEFAULT_PRICING hardcoded) contro
    il prezzo live trovato nel catalogo LiteLLM per lo stesso provider/modello, quando
    trovabile con un match esatto o quasi-esatto. NON modifica nulla, solo report."""
    from rt.llm.pricing import calculate_cost

    report = []
    for route in collect_configured_routes(cfg):
        provider, model = route["provider"], route["model"]
        used_input = calculate_cost(provider, model, input_tokens=1_000_000, output_tokens=0, custom_pricing=cfg.pricing)
        used_output = calculate_cost(provider, model, input_tokens=0, output_tokens=1_000_000, custom_pricing=cfg.pricing)

        live_matches = lookup_live_price(model, provider_hint=provider if provider != "openrouter" else None)
        exact_match = next((m for m in live_matches if m["key"].lower().endswith(model.lower())), None)

        entry = {
            "job": route["job"],
            "provider": provider,
            "model": model,
            "used_input_per_million": used_input,
            "used_output_per_million": used_output,
            "live_match": exact_match,
            "other_matches": [m for m in live_matches if m is not exact_match][:5],
        }
        if exact_match and used_input is not None:
            diff_pct = abs(exact_match["input_per_million"] - used_input) / max(used_input, 0.0001) * 100
            entry["input_diff_pct"] = round(diff_pct, 1)
            entry["stale"] = diff_pct > 15.0
        report.append(entry)
    return report
```

## B. Comandi CLI

In `rt/cli.py`, aggiungere due nuovi subcommand (stesso stile degli altri subparser esistenti):

```python
def cmd_prices_check(args):
    from rt.core.config import load_config
    from rt.llm.pricing_sync import check_configured_pricing
    cfg = load_config()
    report = check_configured_pricing(cfg)
    print("\n💵 VERIFICA PREZZI CONFIGURATI vs CATALOGO LIVE (LiteLLM)\n" + "=" * 70)
    for entry in report:
        flag = "⚠ DA VERIFICARE" if entry.get("stale") else "✔"
        print(f"\n[{entry['job']}] {entry['provider']}/{entry['model']}  {flag}")
        print(f"  In uso oggi:  in=${entry['used_input_per_million']}/M  out=${entry['used_output_per_million']}/M")
        if entry["live_match"]:
            lm = entry["live_match"]
            print(f"  Live (LiteLLM, '{lm['key']}'): in=${lm['input_per_million']}/M  out=${lm['output_per_million']}/M")
            if "input_diff_pct" in entry:
                print(f"  Differenza input: {entry['input_diff_pct']}%")
        else:
            print("  Nessun match trovato nel catalogo live per questo modello.")
    print("\n" + "=" * 70)
    print("Nota: nessuna modifica è stata applicata automaticamente. Se un prezzo risulta")
    print("invecchiato, aggiornalo manualmente nella sezione 'pricing:' di rt.config.yaml.")


def cmd_prices_lookup(args):
    from rt.llm.pricing_sync import lookup_live_price
    results = lookup_live_price(args.query, provider_hint=getattr(args, "provider", None))
    if not results:
        print(f"Nessun modello trovato per '{args.query}'.")
        return
    print(f"\nRisultati per '{args.query}':\n" + "=" * 70)
    for r in results[:20]:
        print(f"  {r['key']:<55} in=${r['input_per_million']}/M  out=${r['output_per_million']}/M  ({r['provider']})")
```

Subparser (vicino a `status`/`test-llm`):
```python
    # prices-check
    p_pc = subparsers.add_parser("prices-check", help="Confronta i prezzi configurati con il catalogo live LiteLLM")
    p_pc.set_defaults(func=cmd_prices_check)

    # prices-lookup
    p_pl = subparsers.add_parser("prices-lookup", help="Cerca il prezzo live di un modello nel catalogo LiteLLM")
    p_pl.add_argument("query", help="Stringa di ricerca (es. 'gemini-3.5-flash', 'deepseek-v4')")
    p_pl.add_argument("--provider", help="Filtra per provider LiteLLM (es. 'deepseek', 'gemini')", default=None)
    p_pl.set_defaults(func=cmd_prices_lookup)
```

## D. Avviso leggero di staleness all'avvio di `rt run` (nessuna chiamata di rete)

### Design
A differenza dei comandi A/B (che chiamano la rete), questo è un controllo puramente locale: guarda quanto è vecchia la cache locale di `pricing_sync` (lo stesso file `~/.cache/rt/litellm_pricing_cache.json` del punto A) e, se non esiste o è più vecchia di N giorni, stampa un avviso non bloccante — nessuna chiamata di rete, nessun impatto sul comportamento della pipeline.

In `rt/core/config.py`, `RTConfig`, aggiungere:
```python
pricing_staleness_warning_days: int = Field(default=7, description="Giorni dopo i quali avvisare che i prezzi configurati non sono stati verificati con 'rt prices-check' (0 per disattivare l'avviso)")
```

In `rt/llm/pricing_sync.py`, aggiungere:
```python
def get_cache_age_days() -> Optional[float]:
    """Restituisce l'età in giorni della cache locale, o None se non esiste ancora."""
    if not os.path.isfile(CACHE_PATH):
        return None
    age_seconds = time.time() - os.path.getmtime(CACHE_PATH)
    return age_seconds / 86400.0
```

In `rt/cli.py`, `cmd_run`, subito dopo la stampa dell'intestazione iniziale della pipeline (prima di "[1/9] SETUP..."), aggiungere un controllo silenzioso:
```python
from rt.core.config import load_config as _load_cfg_for_staleness
from rt.llm.pricing_sync import get_cache_age_days
_cfg_staleness = _load_cfg_for_staleness()
_staleness_days = getattr(_cfg_staleness, "pricing_staleness_warning_days", 7)
if _staleness_days > 0:
    _cache_age = get_cache_age_days()
    if _cache_age is None or _cache_age > _staleness_days:
        print(f"ℹ️  I prezzi configurati non sono stati verificati con 'rt prices-check' da oltre {_staleness_days} giorni "
              f"(o mai). Le stime di costo potrebbero non riflettere i prezzi reali attuali.")
```
(Nota: questo controllo legge solo la data di modifica di un file locale — nessuna chiamata a `requests`, nessuna dipendenza dalla rete disponibile in quel momento. Va inserito una sola volta all'avvio di `cmd_run`, non ripetuto per ogni job/unità.)

### Edge case
- Con `pricing_staleness_warning_days: 0` nel config, l'avviso è disattivato del tutto.
- Se la cache non esiste ancora (utente non ha mai lanciato `rt prices-check`), l'avviso compare comunque (trattato come "mai verificato").
- L'avviso non deve mai bloccare l'esecuzione né richiedere conferma — è puramente informativo.

### Test di accettazione (aggiunti alla stessa suite del punto sopra)
8. `get_cache_age_days()`: verificare `None` quando il file cache non esiste, e un valore numerico coerente quando esiste (con `monkeypatch` su `CACHE_PATH` verso un file di test con `mtime` controllato).
9. Un test su `cmd_run` (con le fasi pipeline mockate come negli altri test di `cmd_run`) che verifica la presenza dell'avviso quando la cache è assente/vecchia, e la sua assenza quando la cache è recente o `pricing_staleness_warning_days=0`.

---

## Edge case e invarianti

1. **Mai invocato automaticamente**: nessuna chiamata a `pricing_sync` da `client.py`/qualunque path della pipeline reale — solo dai due comandi CLI espliciti (il controllo di staleness del punto D è un'eccezione dichiarata: legge solo un timestamp locale, non fa mai rete).
2. **Nessuna scrittura su `rt.config.yaml` o su `rt/llm/pricing.py`**: solo lettura e stampa a schermo. L'utente decide se e come aggiornare la propria configurazione.
3. **Cache locale con TTL di 24h** in `~/.cache/rt/litellm_pricing_cache.json` (scrittura atomica, stesso pattern `tmp + os.replace` già usato altrove nel progetto) — evita di riscaricare ~2.3MB ad ogni invocazione, ma permette comunque un refresh (basta aspettare 24h o cancellare la cache).
4. **Nessun fallback silenzioso sulla rete**: se `requests.get` fallisce e non c'è cache valida, l'eccezione originale propaga con un messaggio chiaro (l'utente capisce che è un problema di rete, non un bug).
5. **`DEFAULT_PRICING` in `rt/llm/pricing.py` resta invariato in questo task** — nessuna sostituzione dei valori hardcoded. Aggiungere solo un commento nel docstring del modulo: `"I valori sottostanti sono stime di riferimento e possono invecchiare. Usa 'rt prices-check' per confrontarli con il catalogo live."`.
6. Il matching in `check_configured_pricing` è volutamente semplice (contiene + termina con) — può produrre falsi negativi (nessun match) su nomi molto generici, ma non deve mai produrre un falso positivo silenzioso che sostituisce un prezzo — in caso di dubbio, mostrare tutti i candidati trovati (`other_matches`) invece di sceglierne uno a caso.

## Test di accettazione

In un nuovo file `tests/test_pricing_sync.py`, **con `requests.get` sempre mockato — mai una vera chiamata di rete nei test**:
1. `load_litellm_catalog`: con un mock di `requests.get` che restituisce un piccolo catalogo finto, verificare che i dati vengano scaricati e salvati in cache (path di test tramite `monkeypatch` su `CACHE_PATH`, non il vero `~/.cache`).
2. Verificare che una seconda chiamata entro il TTL NON richiami `requests.get` di nuovo (usa la cache).
3. `lookup_live_price`: con un catalogo finto contenente varianti note (es. `"gemini/gemini-3.5-flash-lite"`, `"deepseek/deepseek-v4-flash"`), verificare che la ricerca per sottostringa e il filtro per provider funzionino.
4. `collect_configured_routes`: con un `RTConfig` di test contenente più job con `primary`/`secondary`/`fallback`, verificare che tutte le route vengano enumerate e deduplicate correttamente per (provider, model).
5. `check_configured_pricing`: con un catalogo finto e una config di test, verificare che il confronto percentuale (`input_diff_pct`) e il flag `stale` (soglia 15%) siano calcolati correttamente su un caso con differenza nota.
6. Un test per `cmd_prices_lookup`/`cmd_prices_check` (capsys) che verifica l'output testuale con un catalogo mockato.
7. Rieseguire l'intera suite e confermare zero regressioni (il conteggio totale dipende dall'esito del task TUI inviato in parallelo — verificare comunque zero regressioni sui test preesistenti a questo task specifico).

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q`. Verificare che la CI passi (attenzione: se i test di questo modulo chiamassero per errore la vera rete, la CI fallirebbe in modo intermittente — controllare con cura che `requests.get` sia sempre mockato in ogni test).
