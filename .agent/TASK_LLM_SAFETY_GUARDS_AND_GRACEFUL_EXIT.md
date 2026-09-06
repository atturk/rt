# TASK: Modello risolto globale, guardia anti-risposta-lazy su free tier, arresto controllato delle eccezioni LLM

## Contesto generale

`rt.config.yaml` dell'utente usa `openrouter/free` per 3 dei 4 job cognitivi (`outline`, `review_asr`, `review_science`), un router stocastico su un pool di modelli gratuiti: ogni chiamata può atterrare su un modello sottostante diverso. **Nessuno dei 4 job ha un blocco `fallback:` configurato** (scelta deliberata dell'utente per restare 100% gratuito — niente Google/DeepSeek come fallback automatico). Questo significa che `max_attempts` nel config è oggi puramente nominale per qualunque errore che non sia gestito da same-route retry: se la route primaria fallisce e non c'è fallback, la catena termina dopo un solo tentativo, indipendentemente dal valore di `max_attempts`.

Quattro problemi concreti osservati durante test end-to-end reali, da risolvere in un'unica sessione di lavoro:

1. Non si sa mai QUALE modello specifico ha risposto dietro l'alias `openrouter/free` (utile per capire perché una risposta è stata sospetta/lenta/lazy/degenerata).
2. Per `review_asr` e `review_science`, un modello free-tier può rispondere con un JSON sintatticamente valido ma vuoto (`issues: []`) in meno di un secondo — probabile segno che non ha davvero fatto il lavoro di analisi, ma essendo schema-valido viene accettato silenziosamente.
3. `OutputLimitFailure` (output explosion guard) oggi NON viene mai ritentata sulla stessa route. Analisi dei log OpenRouter di un caso reale (`review_science`, unit 7/13): il modello è entrato in un loop di ripetizione degenerato nel testo di **completion vero e proprio** (canale `content`, non `reasoning` — "tonaca più esterna" ripetuto decine di volte), superando i 96758 caratteri prima di emettere JSON valido. Non è quindi "contenuto legittimamente lungo" ma un guasto del modello specifico atterrato dietro `openrouter/free` in quella chiamata. Riprovare sulla stessa route ha buone probabilità di ottenere un modello/backend diverso (pool stocastico free, o provider upstream con quantizzazione diversa anche per modelli fissi via OpenRouter) che non degenera allo stesso modo.
4. Quando la catena di routing si esaurisce comunque (dopo i retry di cui sopra, o per qualunque altro errore non recuperabile, senza fallback configurato), l'eccezione propaga come traceback Python grezzo fino all'utente invece di un arresto controllato e comprensibile.

**Vincolo esplicito**: NON aggiungere blocchi `fallback:` a `rt.config.yaml` o `rt.config.yaml.example` per "risolvere" l'esaurimento della catena. L'utente ha scelto consapevolmente di non avere fallback a pagamento. L'obiettivo è rendere l'esaurimento un evento gestito e chiaro, non eliminarlo.

---

## Feature 1 — Modello risolto globale (visibilità, tutti i job)

Oggi nessun provider adapter estrae il campo `model` che l'API restituisce nella risposta effettiva. Per OpenAI-compatible APIs (DeepSeek, OpenRouter, Google via endpoint OpenAI-compatible) questo campo è presente sia nella risposta non-streaming (`raw_json["model"]`) sia in ogni chunk SSE (`chunk_dict["model"]`), e per `openrouter/free` rivela il modello REALE dietro il router (es. `meta-llama/llama-3.3-70b-instruct:free`).

### Modifiche

**`rt/llm/providers/base.py`**: aggiungere un campo opzionale a entrambi i modelli:
```python
class NormalizedResponse(BaseModel):
    ...
    resolved_model: Optional[str] = Field(default=None, description="ID del modello realmente utilizzato dal provider (può differire dal modello richiesto, es. per router aggregatori come 'openrouter/free')")

class StreamChunk(BaseModel):
    ...
    resolved_model: Optional[str] = None
```

**`rt/llm/providers/openrouter.py`, `rt/llm/providers/deepseek.py`, `rt/llm/providers/google.py`**: in `parse_stream_line`, popolare `resolved_model=chunk_dict.get("model")`; in `normalize_response`, popolare `resolved_model=raw_json.get("model")`. Per DeepSeek/Google coinciderà quasi sempre col modello richiesto (nessun impatto), per OpenRouter rivelerà l'alias risolto.

**`rt/llm/client.py`**: nel loop di streaming, tracciare l'ultimo `resolved_model` non nullo ricevuto tra i chunk (analogo a come oggi si traccia `finish_reason`); nel path non-streaming, prenderlo da `norm.resolved_model`. Propagarlo:
- a `LLMTelemetryRecord` (nuovo campo `resolved_model: Optional[str]` in `rt/llm/telemetry.py`);
- a `LiveTerminalMonitor` (nuovo attributo, settato via un metodo tipo `monitor.set_resolved_model(resolved_model)` chiamato quando arriva, oppure passato a `monitor.on_usage`/`monitor.finish` — a discrezione, purché sia disponibile prima del render finale).

**`rt/llm/monitor.py`**: nel blocco di rendering (dopo la riga `f"Model:    {self.model}",` circa riga 196), aggiungere una riga condizionale:
```python
if self.resolved_model and self.resolved_model != self.model:
    lines.append(f"Resolved: {self.resolved_model}")
```
(mostrata solo quando differisce dal modello richiesto, per non appesantire l'output nei casi banali DeepSeek/Google dove coincide sempre).

---

## Feature 2 — Guardia anti-risposta-lazy su free tier (solo `review_asr` e `review_science`)

### Regola di detection "free tier"
```python
def _is_openrouter_free_tier(provider: str, model: str) -> bool:
    p = (provider or "").lower().strip()
    m = (model or "").strip()
    return p == "openrouter" and (m == "openrouter/free" or m.endswith(":free"))
```
(funzione privata in `rt/llm/client.py`, usata solo lì).

### Comportamento
`call_structured` accetta un nuovo parametro opzionale:
```python
def call_structured(
    self,
    ...,
    min_elapsed_seconds: Optional[float] = None,
) -> T:
```
Quando `min_elapsed_seconds` è impostato E la route risolta è free-tier (per la regola sopra) E il tempo dell'attempt (`elapsed_att`) è inferiore alla soglia, il risultato — **anche se sintatticamente valido e già passato la validazione Pydantic** — viene considerato sospetto e SEMPRE scartato (non solo quando `issues` è vuoto: un retry su free tier non costa nulla, quindi non serve distinguere i casi, è più semplice trattarli tutti uguali).

`rt/pipeline/review_asr.py` e `rt/pipeline/review_science.py`: nella chiamata a `client.call_structured(...)`, aggiungere `min_elapsed_seconds=5.0`. `outline.py` e `rewrite.py` NON vanno toccati (restano senza questo controllo, come da decisione già presa: quei job producono contenuto sostanzioso che la validazione strutturale esistente già intercetta se insufficiente).

### Nuova classe di errore

**`rt/llm/errors.py`**:
```python
class SuspiciousFastResponseFailure(LLMFailure):
    """Sollevata quando un modello free-tier (tipicamente dietro 'openrouter/free') restituisce
    un risultato sintatticamente valido ma sospettosamente veloce, probabile segno di una
    risposta 'lazy' senza reasoning effettivo (rilevante per job di analisi come review_asr/review_science,
    dove un output minimale/vuoto è indistinguibile da un'analisi vera che non ha trovato nulla)."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "suspicious_fast_response"
```
Questa classe NON passa da `classify_failure` (non è un errore HTTP/di rete, è una validazione post-hoc di plausibilità) — va sollevata direttamente nel punto di successo di `call_structured`.

### Aggancio in `rt/llm/client.py` — GENERALIZZARE il meccanismo di retry già esistente per `ReasoningRequiredFailure`

Nella sessione precedente è già stato implementato un meccanismo di same-route retry con escalation locale di `thinking=true` per `ReasoningRequiredFailure` (variabili `reasoning_required_strikes`, `MAX_REASONING_REQUIRED_RETRIES`, `force_thinking_override` — vedi `rt/llm/client.py`, sub-loop attorno a `route_timeout_attempt`). **Riusa esattamente lo stesso meccanismo/contatore per `SuspiciousFastResponseFailure`**, trattando le due cause come un'unica categoria "risposta a basso sforzo": stesso contatore di strike condiviso (rinominalo se vuoi per chiarezza semantica, es. `low_effort_strikes`/`MAX_LOW_EFFORT_RETRIES`, ma **non deve rompere i 4 test già esistenti** in `tests/test_reasoning_required_retry.py`, che verificano comportamento black-box tramite `call_structured`, non i nomi interni delle variabili), stessa escalation a `thinking=true` dopo 2 fallimenti consecutivi (di qualunque combinazione tra le due cause), stesso limite di 3 tentativi totali sulla stessa route prima di procedere al failover/esaurimento normale.

Punto di aggancio per sollevare `SuspiciousFastResponseFailure`: subito dopo la validazione Pydantic riuscita (circa riga 656 di `rt/llm/client.py`, prima del blocco "SUCCESSO PIENO!"/telemetria di successo):
```python
if (
    min_elapsed_seconds is not None
    and elapsed_att < min_elapsed_seconds
    and _is_openrouter_free_tier(provider_name, model_name)
):
    raise SuspiciousFastResponseFailure(
        f"Risposta ricevuta in soli {elapsed_att:.2f}s da un modello free-tier ('{model_name}') "
        f"per il job '{job_name}' (soglia minima: {min_elapsed_seconds}s). "
        f"Probabile risposta a basso sforzo senza reasoning effettivo, scartata precauzionalmente.",
        provider=provider_name,
        model=model_name
    )
```
Questo deve finire nello stesso blocco `except Exception as e:` esistente (quindi il `raise` va dentro il `try` principale, non in un blocco separato) — e va aggiunta `SuspiciousFastResponseFailure` alla tupla `is_infra_error` (stesso motivo per cui ci è stata aggiunta `ReasoningRequiredFailure`: evitare che il sotto-loop di "repair turn" tenti inutilmente di correggere uno "schema" che in realtà è corretto).

### Edge case
- Il controllo si applica SOLO quando `min_elapsed_seconds` è esplicitamente passato dal chiamante (default `None` = disattivato) — `outline`/`rewrite`/qualunque chiamata diretta/diagnostica (`rt test-llm`) restano invariati.
- Non deve attivarsi nel path mock (`force_mock=True` ritorna prima di raggiungere questo codice — verificare che sia già così, nessuna modifica necessaria lì).
- Se anche il terzo tentativo (con `thinking=true` forzato) risulta ancora troppo veloce, la catena procede nel comportamento di esaurimento standard — gestito dalla Feature 3 sotto, NON aggiungere alcun fallback automatico.

---

## Feature 2b — Retry same-route per `OutputLimitFailure` (SENZA escalation di thinking)

Caso reale analizzato dai log OpenRouter (vedi Contesto, punto 3): il modello è entrato in un loop di ripetizione infinito nella completion (canale `content`), con `thinking: true` già attivo su `review_science` — la separazione reasoning/completion non ha impedito il degenerare del loop nel canale sbagliato. Che un loop degenerativo avvenga nel reasoning o nella completion è la stessa classe di guasto del modello; non c'è motivo di credere che forzare/mantenere `thinking=true` prevenga l'una o l'altra forma in modo affidabile — a differenza di `ReasoningRequiredFailure`/`SuspiciousFastResponseFailure` (dove il problema è specificamente l'assenza di reasoning), qui l'unica leva utile è riprovare sulla stessa route sperando di ottenere un modello/backend diverso (pool stocastico `openrouter/free`, o provider upstream con quantizzazione diversa anche dietro un modello fisso via OpenRouter).

`OutputLimitFailure` è già oggi correttamente classificata (nessuna modifica a `classify_failure` necessaria) e già presente nella tupla `is_infra_error` (nessuna modifica lì). Manca solo l'aggancio nel sotto-loop di same-route retry di `rt/llm/client.py`.

### Design
Contatore indipendente, **senza alcuna escalation** (niente `force_thinking_override`):
```python
output_limit_retries = 0
MAX_OUTPUT_LIMIT_RETRIES = 2  # fino a 2 retry aggiuntivi sulla stessa route, nessuna modifica ai parametri della richiesta
```
Nel blocco di decisione retry (stesso punto dove si gestiscono `TimeoutFailure` e la coppia low-effort), aggiungere un ramo aggiuntivo:
```python
elif isinstance(classified_failure, OutputLimitFailure) and output_limit_retries < MAX_OUTPUT_LIMIT_RETRIES:
    output_limit_retries += 1
    call_attempt += 1
    monitor.log_retry(reason="output_limit_retry", elapsed=elapsed_att, next_attempt=call_attempt)
    time.sleep(1.5)
    continue
```
Il payload del tentativo successivo NON deve differire in alcun modo da quello originale (stesso `thinking`, stesso `reasoning_effort`) — l'unica speranza è che il pool/provider a monte risolva diversamente la stessa richiesta.

Aggiornare di conseguenza il bound del while esterno del sotto-loop, sommando anche questo nuovo budget:
```python
while route_timeout_attempt < (total_route_timeout_attempts + MAX_LOW_EFFORT_RETRIES + MAX_OUTPUT_LIMIT_RETRIES):
```
(i tre contatori — timeout, low-effort, output-limit — restano totalmente indipendenti tra loro; ognuno controlla solo il proprio ramo `elif`, il bound complessivo serve solo a garantire che il while esterno non termini il ciclo prematuramente).

Questo retry si applica a **qualunque provider**, non solo a `openrouter/free` (nessun gate `_is_openrouter_free_tier` qui): anche un provider fisso via OpenRouter può atterrare su backend diversi a monte, e anche una API diretta può occasionalmente produrre un loop degenerato per motivi di sampling — il costo di 1-2 tentativi extra è trascurabile.

---

## Feature 3 — Arresto controllato per qualunque `LLMFailure` non gestita (nessun traceback all'utente)

### Causa del crash riportato dall'utente
`review_science` ha `max_attempts: 3` ma nessun `fallback:` configurato. Prima della Feature 2b, `OutputLimitFailure` non veniva mai ritentata sulla stessa route, quindi la catena terminava subito dopo il primo tentativo (`select_fallback_route` ritorna `None`, nessun fallback configurato), e l'eccezione propagava fino a `main()` in `rt/cli.py` senza essere mai intercettata — nessuno dei 6 punti di chiamata LLM nella CLI (`cmd_run`, `cmd_outline`, `cmd_rewrite`, `cmd_review_asr`, `cmd_review_science`) ha un try/except per questo caso (a differenza di `cmd_run`, che invece intercetta già `SetupError` per l'ingest audio). Con la Feature 2b questo specifico scenario avrà ora 2 retry aggiuntivi sulla stessa route prima di arrivare all'esaurimento — ma l'arresto controllato resta necessario come rete di sicurezza generale per QUALUNQUE `LLMFailure` che esaurisca comunque tutti i tentativi disponibili (timeout, low-effort, output-limit, o qualunque altra causa non ancora prevista).

### Fix: un solo punto di cattura, non sei
In `rt/cli.py`, funzione `main()`, riga 838 (`args.func(args)`):
```python
    normalized_argv = normalize_review_cli_args(sys.argv[1:])
    args = parser.parse_args(normalized_argv)
    from rt.llm.errors import LLMFailure
    try:
        args.func(args)
    except LLMFailure as e:
        print("\n" + "=" * 60, file=sys.stderr)
        print("❌ ESECUZIONE INTERROTTA: errore LLM non recuperabile", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"\n{e}\n", file=sys.stderr)
        failure_class = getattr(e, "failure_class", None)
        if failure_class:
            print(f"Classe di errore: {failure_class}", file=sys.stderr)
        provider = getattr(e, "provider", None)
        model = getattr(e, "model", None)
        if provider or model:
            print(f"Provider/modello: {provider or '?'} / {model or '?'}", file=sys.stderr)
        print(
            "\nLa pipeline non ha trovato (o non ha configurato) una route alternativa per "
            "questo errore. Puoi:\n"
            "  - Rilanciare lo stesso comando: la pipeline riprende dal checkpoint salvato e, "
            "trattandosi spesso di provider stocastici (es. 'openrouter/free'), un nuovo tentativo "
            "può avere esito diverso;\n"
            "  - Modificare 'rt.config.yaml' per il job coinvolto (es. aumentare 'max_output_chars', "
            "cambiare modello, o aggiungere un blocco 'fallback' se disponibile un'alternativa).\n",
            file=sys.stderr
        )
        sys.exit(1)
```
**Importante**: catturare `LLMFailure` (non `Exception` generico) — deve continuare a propagare normalmente qualunque altro errore di programmazione reale (bug, `KeyError`, ecc.), che deve restare visibile come traceback per il debug. `LLMError` è già un alias di `LLMFailure` (vedi `rt/llm/errors.py`), quindi questo cattura anche `LLMTimeoutError` e tutte le sottoclassi (`OutputLimitFailure`, `ReasoningRequiredFailure`, `SuspiciousFastResponseFailure`, `AuthenticationFailure`, ecc.) con un solo blocco.

Non serve toccare `cmd_run`, `cmd_outline`, `cmd_rewrite`, `cmd_review_asr`, `cmd_review_science` individualmente: essendo tutti invocati tramite `args.func(args)` in `main()`, questo unico blocco li copre tutti.

---

## Invarianti da rispettare

1. Nessun nuovo blocco `fallback:` in `rt.config.yaml`/`rt.config.yaml.example` — non è nello scope di questo task.
2. I 4 test esistenti in `tests/test_reasoning_required_retry.py` devono continuare a passare invariati (comportamento black-box, non i nomi interni delle variabili).
3. `min_elapsed_seconds` è opt-in, `None` di default: `outline`/`rewrite`/chiamate dirette non ne sono affette.
4. Il catch in `main()` intercetta SOLO `LLMFailure` (e sottoclassi/alias), non `Exception` generico.
5. Nessuna nuova opzione in `rt.config.yaml` — soglia `5.0` e costanti di retry restano hardcoded nel codice, coerente con quanto già deciso nella sessione precedente.
6. Il retry per `OutputLimitFailure` (Feature 2b) NON deve mai alterare `thinking`/`reasoning_effort` nel payload dei tentativi successivi — a differenza della coppia low-effort, qui il payload resta identico in ogni retry.
7. I tre contatori di retry same-route (timeout esistente, low-effort, output-limit) sono totalmente indipendenti: l'esaurimento di uno non deve consumare il budget degli altri due, e nessuno dei tre deve poter causare un loop infinito (ognuno ha un tetto fisso).

## Test di accettazione (`pytest tests/`)

1. **Feature 1**: in `tests/test_llm_config.py` o file dedicato, un test che simula una risposta OpenRouter con `"model": "meta-llama/llama-3.3-70b-instruct:free"` nel JSON e verifica che `LLMTelemetryRecord.resolved_model` (o il campo scelto) rifletta questo valore anche quando il modello richiesto era `"openrouter/free"`.
2. **Feature 2** (nuovo file o esteso `tests/test_reasoning_required_retry.py`):
   - risposta valida ma in 2s da `openrouter/free` con `min_elapsed_seconds=5.0` → scartata, retry same-route;
   - 2 risposte veloci consecutive → 3° tentativo con `thinking=true` forzato (verificare payload);
   - una risposta valida in 2s da un modello NON free-tier (es. `deepseek-chat`) con `min_elapsed_seconds=5.0` → accettata senza retry (il controllo non si applica);
   - `outline`/`rewrite` non invocano mai `min_elapsed_seconds` (verifica per lettura del codice o test di non-regressione che il parametro di default `None` non alteri il comportamento esistente).
3. **Feature 2b**: nello stesso file di test:
   - 2 `OutputLimitFailure` consecutive (HTTP 200 ma contenuto che supera `max_output_chars`) seguite da una 3ª risposta valida e sotto soglia → successo al 3° tentativo, e tutti e 3 i payload IDENTICI su `thinking`/`reasoning_effort` (nessuna escalation);
   - 3 `OutputLimitFailure` consecutive (budget esaurito) su un job SENZA `fallback` configurato → l'eccezione finale propagata da `call_structured` è `OutputLimitFailure` (comportamento di esaurimento invariato, gestito poi dalla Feature 3 a livello CLI);
   - verificare che un `OutputLimitFailure` e una `ReasoningRequiredFailure` alternate sulla stessa route non interferiscano tra loro (contatori indipendenti — es. 1 `OutputLimitFailure` + 1 `ReasoningRequiredFailure` + successo al 3° tentativo, senza che nessuno dei due budget risulti già esaurito per colpa dell'altro).
4. **Feature 3**: un test in `tests/test_cli_review.py` o nuovo file che invoca `main()` (con `sys.argv` mockato) in uno scenario che solleva una `LLMFailure` in fondo alla catena (nessun fallback configurato) e verifica: `SystemExit` con codice 1, nessun traceback stampato su stdout/stderr (solo il messaggio formattato), presenza del testo del messaggio d'errore originale nell'output.
5. Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare zero regressioni sui test esistenti (152 attuali + i nuovi).

## Output atteso
Diff completo sui file toccati + output di `python3 -m pytest tests/ -q` con il conteggio finale. Nessun walkthrough testuale necessario.
