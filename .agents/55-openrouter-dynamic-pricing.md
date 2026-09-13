# Task 55 — Pricing OpenRouter rilevato automaticamente invece di tabella statica incompleta

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Test reale: le chiamate Google mostrano il costo stimato correttamente
(`$0.000434`), le chiamate OpenRouter per lo stesso tipo di job mostrano sempre `pending`.

**Causa esatta**: `calculate_cost()` in `rt/llm/pricing.py` cerca il modello in
`DEFAULT_PRICING`, una tabella statica hardcoded. `DEFAULT_PRICING["google"]` elenca 11 modelli
Gemini con nomi "nudi" che tipicamente matchano; `DEFAULT_PRICING["openrouter"]` contiene solo
9 voci hardcoded (poche varianti deepseek, un paio di altri modelli) — un modello come
`openai/gpt-5.6-luna` non c'è, nessun match per segmenti riesce, e (essendo non-deepseek) la
funzione ritorna `None`. `MonitorState.render()` in `rt/llm/monitor.py` (righe 121-187, la
decisione è a riga 186) mostra `"pending"` ogni volta che `calculate_cost(...)` ritorna `None`.

**Nessun codice interroga mai il campo pricing di OpenRouter**: l'unica chiamata a un endpoint
`/models` di OpenRouter esiste in `rt/pipeline/configure.py` (riga ~456, dentro
`_create_new_model_profile`), usata SOLO per popolare l'autocomplete della lista modelli in
fase di configurazione — estrae solo `item["id"]` (riga ~464), ignora completamente
`item["pricing"]` (che l'API OpenRouter espone realmente: `GET
https://openrouter.ai/api/v1/models` ritorna per ogni modello un oggetto `pricing` con
`prompt`/`completion` in USD per token).

Nota anche che `RouteConfig` (in `rt/core/config.py`) ha già un campo `pricing:
Optional[ModelPricing]` per un pricing custom specifico-per-route con priorità massima
(`LLMClient._resolve_custom_pricing`, `rt/llm/client.py` riga ~97) — questo meccanismo di
override esiste già e funziona, manca solo il popolamento AUTOMATICO al momento della
configurazione.

## Modifica

### 1. In fase di configurazione: rileva il pricing reale invece di chiedere genericamente

In `_create_new_model_profile` (`rt/pipeline/configure.py`), quando il fetch dei modelli da
OpenRouter riesce (il blocco che oggi estrae solo `item["id"]`), estrai ANCHE
`item.get("pricing", {})` (`prompt`, `completion` — verifica i nomi esatti dei campi
nell'attuale risposta reale di `https://openrouter.ai/api/v1/models`, potrebbero essere
stringhe rappresentanti USD-per-token, es. `"0.0000012"` — vanno convertiti in USD-per-milione-
token, cioè moltiplicati per 1_000_000, per essere coerenti con lo schema `ModelPricing`
esistente in `rt/llm/pricing.py`) per il modello scelto specificamente (non serve per tutti i
modelli della lista, solo per quello selezionato).

Sostituisci la domanda attuale in `_configure_pricing_section`
(`"Vuoi configurare un listino prezzi custom per questo modello? (opzionale, RT ha già stime
interne)"`) con, quando il pricing è stato rilevato con successo:
```
Costo rilevato per milione di token: input $X.XX; output $Y.YY. Vuoi modificarlo? (y/N)
```
Se l'utente conferma "No" (default), salva DIRETTAMENTE il pricing rilevato come pricing
custom della route (stesso meccanismo già esistente, `RouteConfig.pricing`) — non serve alcuna
domanda ulteriore, l'utente ha già visto ed accettato il prezzo. Se conferma "Sì" (vuole
modificarlo), prosegui con le domande attuali di inserimento manuale (Costo Input/Output per
milione di token), pre-riempendo i default con i valori rilevati invece che vuoti.

Se il pricing NON è stato rilevabile (provider non-OpenRouter senza un meccanismo simile, o
fetch fallito): mantieni il comportamento attuale (domanda generica sì/no per inserimento
manuale) — non regredire il caso Google, che già funziona tramite la tabella statica.

### 2. A runtime: fallback dinamico se la tabella statica non ha il modello

Per rendere il sistema robusto anche per modelli configurati PRIMA di questo task (senza
pricing custom salvato) o per round-robin dove non è stato chiesto per ogni singola chiave:
in `calculate_cost()` (`rt/llm/pricing.py`), quando il provider è `openrouter` e il modello non
è trovato in `DEFAULT_PRICING` né ha un pricing custom sulla route, valuta se aggiungere una
chiamata (con cache in-memory per processo, per non rifare la richiesta ad ogni singola
chiamata LLM) a `GET https://openrouter.ai/api/v1/models` per recuperare il pricing al volo la
PRIMA volta che serve per quel modello in quella sessione — usa un timeout breve (es. 3-5
secondi) e in caso di fallimento/timeout ritorna `None` come oggi (nessuna eccezione che
blocchi la pipeline). Verifica se questo livello va aggiunto qui in `pricing.py` (centralizzato,
beneficia tutti i chiamanti) o se preferisci limitarti al punto 1 (rilevamento solo in fase di
config) se ritieni sufficiente coprire il caso comune — a tua valutazione in base alla
complessità che introduce, ma il punto 1 è quello richiesto esplicitamente e non è opzionale.

## Test

- Test che verifica che, dato un mock della risposta `/models` di OpenRouter con un campo
  `pricing` popolato, `_create_new_model_profile` mostri il messaggio con i valori rilevati e
  salvi correttamente `RouteConfig.pricing` se l'utente conferma senza modificare.
- Test che verifica che, con "vuoi modificarlo" = Sì, i campi di inserimento manuale siano
  pre-riempiti con i valori rilevati come default.
- Test che verifica che il comportamento attuale (domanda generica) resti invariato quando il
  fetch pricing fallisce o il provider non è openrouter.
- Se implementi anche il punto 2: test che verifica che `calculate_cost` per un modello
  OpenRouter non in `DEFAULT_PRICING` tenti il fetch dinamico e usi il risultato; test che
  verifica che un fallimento di rete non sollevi eccezioni e ritorni `None` come oggi.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare il meccanismo di pricing custom esistente (`RouteConfig.pricing`,
`_resolve_custom_pricing`): è già corretto, questo task lo popola automaticamente invece di
richiedere sempre inserimento manuale.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test funzionale diretto (se hai accesso di rete nell'ambiente Antigravity): configura un
   nuovo profilo OpenRouter con un modello reale, verifica che il prezzo rilevato venga
   mostrato correttamente e che una chiamata reale (anche `--mock` se preferisci non spendere)
   mostri il costo invece di "pending".
