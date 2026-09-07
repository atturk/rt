Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Rimozione export MD morto di MacWhisper, TUI compatta con log dettagliato, interruzione Ctrl+C intelligente, documentazione pricing custom

## Contesto

Emerso da un test e2e reale: (1) l'export Markdown di MacWhisper durante il setup è codice completamente morto (generato e mai letto), causa doppio tempo di attesa e un secondo spinner confuso; (2) il monitor a terminale (`LiveTerminalMonitor`) è troppo verboso per l'uso quotidiano — un blocco di 15 righe per OGNI chiamata LLM resta permanentemente nello scrollback, "inquinando" il terminale su run con molte unità (es. 25 unità di rewrite = 25 blocchi permanenti); (3) oggi non c'è modo di abbandonare un tentativo lento e passare a un'altra route se non uccidendo l'intero processo con Ctrl+C; (4) i prezzi in `rt/llm/pricing.py` sono stime, l'utente vuole poter inserire prezzi reali senza modificare il codice (funzionalità già esistente ma non documentata).

---

## A. Rimuovere l'export Markdown morto di MacWhisper

### Causa verificata
In `rt/pipeline/setup.py`, righe 445-492 (ramo di trascrizione reale, dentro `elif not skip_transcribe:`): `cmd_md`/`res_md`/`tmp_md` vengono generati con una seconda chiamata `_run_mw_with_spinner`, il codice di ritorno viene controllato solo per un avviso, e **il file `tmp_md` viene poi cancellato senza mai essere letto da nessuna parte** (riga 491-492: `if os.path.isfile(tmp_md): os.remove(tmp_md)`). Il file finale `trascritto grezzo.md` (generato più sotto, righe 503+) viene costruito indipendentemente da `all_segments_combined` (derivato dal JSON), **non ha alcuna relazione con `tmp_md`**. Confermato con `mw transcribe --help` che l'export multi-formato in una sola chiamata non è supportato dalla CLI di MacWhisper — quindi non è nemmeno recuperabile con un flag, va solo rimosso.

### Fix
Rimuovere completamente, dal ramo `elif not skip_transcribe:` di `run_setup`:
- La definizione di `cmd_md` (righe 445-453).
- La chiamata `res_md = _run_mw_with_spinner(cmd_md, "Trascrizione MacWhisper (Markdown)")` e il relativo controllo `if res_md.returncode != 0: print(...)` (righe 466-469).
- La variabile `tmp_md` (riga 435) e la sua cancellazione (riga 491-492).
Nessun'altra modifica: il file finale `trascritto grezzo.md` (righe 503+, costruito da `all_segments_combined`) resta invariato e continua a essere generato normalmente.

### Test di accettazione
- Aggiornare/verificare i test esistenti in `tests/test_setup.py` che mockano `_run_mw_with_spinner` (es. `test_run_setup_on_progress_callback`, `test_macwhisper_markdown_failure_is_soft`) — quest'ultimo test specifico sul fallimento soft dell'export MD **va rimosso** (il codice che testava non esiste più) o riadattato se la fixture serviva anche ad altro.
- Verificare che `_run_mw_with_spinner` venga chiamata **una sola volta** per file audio (non più due), con un test dedicato che conta le chiamate mockate.
- Rieseguire l'intera suite e confermare zero regressioni.

---

## B. TUI: riga compatta di default, box dettagliato opzionale, log dettagliato su file, riepilogo costi finale, interruzione Ctrl+C

### B1. Riga compatta di default in `LiveTerminalMonitor`

In `rt/core/config.py`, `RTConfig`, aggiungere un nuovo campo:
```python
show_monitor_verbose: bool = Field(default=False, description="Se True, mostra il box dettagliato multi-riga invece della riga compatta di default")
```

In `rt/llm/monitor.py`, `LiveTerminalMonitor.__init__`, aggiungere un parametro `verbose: bool = False` e salvarlo (`self.verbose = verbose`).

In `rt/llm/client.py`, dove oggi viene costruito `LiveTerminalMonitor(...)` (cercare `monitor = LiveTerminalMonitor(`), passare `verbose=getattr(self.config, "show_monitor_verbose", False)`.

In `LiveTerminalMonitor.render()` (`rt/llm/monitor.py`), il metodo oggi costruisce sempre il blocco multi-riga a partire dalla variabile locale `lines` (circa riga 186 in poi, dopo aver già calcolato `in_est/out_est/reas_est`, `current_cost`, `step_badge`, ecc. — **riusa queste variabili già calcolate, non duplicare la logica di stima**). Introdurre un ramo alternativo quando `not self.verbose`:

```python
if not self.verbose:
    spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    frame = spinner_frames[int(elapsed_render * 10) % len(spinner_frames)] if not final else ("✔" if self.status == "completed" else "✗")
    unit_part = f" · {self.unit_id}" if self.unit_id else f" · {self.attempt}/{self.max_attempts}"
    slow_tag = ""
    if self.timeout_seconds and not final:
        elapsed_now = time.time() - self.start_time
        if elapsed_now > 0.5 * self.timeout_seconds:
            slow_tag = " ⚠lento"
    retry_tag = f" · retry:{self._last_retry_reason}" if getattr(self, "_last_retry_reason", None) and not final else ""
    compact_line = (
        f"{frame} {self.job}{unit_part} · ↑{in_est}{suffix} ↓{out_est}{suffix} R{reas_est}{suffix} "
        f"{cost_str} · {self.provider}/{self.model}{retry_tag}{slow_tag} · {int(elapsed_render)}s"
    )
    if self.is_tty:
        sys.stdout.write(f"\r\033[K{compact_line}")
        if final:
            sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        if final:
            print(compact_line)
    return
```
(inserire questo ramo PRIMA della costruzione di `lines = [...]`, con un `return` che salta tutta la logica del box verboso sottostante; `elapsed_render` è il tempo trascorso già disponibile/calcolabile come nel resto del metodo — riusare la stessa variabile di elapsed già presente in `render()`, non ricalcolarla in modo diverso). Il valore esatto della soglia "lento" (50%) e la struttura della riga vanno rispettati come sopra, ma la sintassi precisa di accesso alle variabili già presenti nel metodo va adattata a come sono effettivamente chiamate nel codice corrente (leggere l'intero metodo `render()` prima di procedere).

**Nuovo attributo per il tag di retry**: in `LiveTerminalMonitor`, aggiungere un metodo:
```python
def set_retry_reason(self, reason: Optional[str]) -> None:
    self._last_retry_reason = reason
```
e chiamarlo da `rt/llm/client.py` nei punti in cui oggi si chiama `monitor.log_timeout(...)` o `monitor.log_retry(...)` (i rami di retry same-route per timeout, low-effort, output-limit), passando un tag breve (es. `"timeout"`, `"reasoning_required"`, `"suspicious_fast_response"`, `"output_limit"`) PRIMA di richiamare `monitor.reset_for_attempt(...)`. Con la riga compatta, questi metodi `log_timeout`/`log_retry` esistenti (pensati per stampare righe multiple nel box verboso) vanno resi condizionali: se `self.verbose` stampano come oggi, altrimenti non stampano nulla di proprio (il tag di retry comparirà comunque nella riga compatta al prossimo render tramite `set_retry_reason`).

### B2. Riepilogo costi a fine pipeline

In `rt/cli.py`, `cmd_run`, dopo il completamento di tutti gli step (subito prima del `return` finale della funzione, o subito dopo l'ultimo step `build`), aggiungere:
```python
from rt.llm.telemetry import GLOBAL_TELEMETRY
summary = GLOBAL_TELEMETRY.get_summary()
if summary["total_requests"] > 0:
    print("\n" + "=" * 60)
    print("💰 RIEPILOGO COSTI SESSIONE")
    print("=" * 60)
    for job_name, job_stats in summary["by_job"].items():
        print(f"  {job_name:<16} {job_stats['requests']:>3} richieste  ${job_stats['estimated_cost_usd']:.6f}")
    print(f"  {'TOTALE':<16}     ${summary['total_estimated_cost_usd']:.6f}")
    print("=" * 60)
```
(riusa `GLOBAL_TELEMETRY.get_summary()`, già esistente con `by_job`/`total_estimated_cost_usd` — nessuna nuova infrastruttura di calcolo). Non serve aggiungerlo ai comandi a fase singola (`rt outline`, `rt rewrite`, ecc.) in questo task — solo a `cmd_run`.

### B3. Log dettagliato per lezione (`llm_debug.log`, file visibile, JSON Lines)

In `rt/llm/client.py`, aggiungere un parametro opzionale a `call_structured`:
```python
lesson_dir: Optional[str] = None
```
Quando fornito, ad ogni tentativo (sia successo che fallimento — cioè negli stessi punti in cui oggi si chiama `GLOBAL_TELEMETRY.add(telemetry_rec)` e `GLOBAL_TELEMETRY.add(err_rec)`), scrivere in append una riga JSON su `os.path.join(lesson_dir, "llm_debug.log")`:
```python
def _append_debug_log(lesson_dir: str, entry: Dict[str, Any]) -> None:
    import json as _json
    log_path = os.path.join(lesson_dir, "llm_debug.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Il log di debug non deve mai far fallire la pipeline
```
Campi minimi per riga: `timestamp` (ISO), `execution_id`, `job`, `unit_id`, `provider`, `model`, `resolved_model`, `attempt`, `route_role`, `status` (success/timeout/error), `elapsed_seconds`, `input_tokens`, `output_tokens`, `reasoning_tokens`, `estimated_cost`, `finish_reason`, `error_message` (solo se fallito), `reasoning_text` (contenuto completo di `reasoning_content`/`reasoning_parts`, solo se disponibile), `content_text` (contenuto completo, solo su successo). Nessun troncamento arbitrario del testo (è pensato per debug ad alto livello).

**Chiamanti**: aggiungere `lesson_dir=lesson_dir` alle chiamate `client.call_structured(...)` già esistenti in `rt/pipeline/outline.py`, `rt/pipeline/rewrite.py`, `rt/pipeline/review_asr.py`, `rt/pipeline/review_science.py` (tutte e 4 le funzioni hanno già `lesson_dir` nello scope locale). Se `lesson_dir` non è fornito (es. chiamate diagnostiche da `rt test-llm`), il logging su file è semplicemente disattivato (nessun errore).

### B4. Interruzione Ctrl+C durante lo streaming → passa alla route di fallback

In `rt/llm/errors.py`, aggiungere:
```python
class UserAbortedFailure(LLMFailure):
    """Sollevata quando l'utente interrompe manualmente (Ctrl+C) un tentativo di streaming in corso."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.failure_class = "user_aborted"
```

In `rt/llm/client.py`, riga 780 (`except Exception as e:`, dentro il sotto-ciclo `for repair_turn in range(max_retries + 1):`), aggiungere un handler PRIMA di esso:
```python
except KeyboardInterrupt:
    if 'response' in locals():
        try:
            response.close()
        except Exception:
            pass
    print("\n⚠ Interrotto dall'utente durante lo streaming — passo alla route di fallback (se disponibile)...")
    attempt_exception = UserAbortedFailure(
        "Tentativo interrotto manualmente dall'utente (Ctrl+C) durante lo streaming.",
        provider=provider_name,
        model=model_name
    )
    break
except Exception as e:
    ... (invariato)
```
Il `break` esce immediatamente dal ciclo di repair turn (nessun tentativo di correzione JSON su un'interruzione manuale). Il codice successivo (classificazione del fallimento, decisione di retry) NON necessita modifiche: `UserAbortedFailure` è già un `LLMFailure`, quindi `classify_failure` la restituisce così com'è; non essendo `TimeoutFailure`/`ReasoningRequiredFailure`/`SuspiciousFastResponseFailure`/`OutputLimitFailure`, il blocco di decisione retry esistente la fa cadere direttamente nel ramo `else: break`, uscendo dal sotto-ciclo same-route e procedendo al failover cross-route esistente (`select_fallback_route`) — **nessuna modifica a `rt/llm/router.py` necessaria**.

**Comportamento a due livelli ottenuto gratuitamente**: un secondo Ctrl+C premuto FUORI dalla finestra di streaming attiva (es. durante l'attesa tra un tentativo e il successivo, `time.sleep(backoff)`) non è intercettato da questo handler specifico e si propaga normalmente, terminando l'intero processo — nessuna gestione aggiuntiva necessaria per questo comportamento, è già la conseguenza naturale dello scoping del `try/except`.

### B5. Avviso "provider lento" (soglia fissa 50%)

Già incluso nel design della riga compatta al punto B1 (`slow_tag`) — nessun controllo aggiuntivo altrove nel codice, è puramente un'informazione visiva nella riga compatta quando il tempo trascorso supera il 50% di `timeout_seconds` per il tentativo corrente, mentre lo streaming è ancora attivo.

### Edge case e invarianti
- Il box verboso esistente (`self.verbose = True`, via `show_monitor_verbose: true` in config) deve continuare a funzionare esattamente come oggi, incluse le chiamate a `log_timeout`/`log_retry` che stampano righe multiple.
- `UserAbortedFailure` non deve mai essere silenziosamente ignorata: se esaurisce la catena di routing (nessun fallback configurato), deve propagare fino al blocco `except LLMFailure` già esistente in `main()` (`rt/cli.py`), risultando in un arresto controllato con messaggio chiaro — non un traceback grezzo.
- `_append_debug_log` non deve mai sollevare eccezioni che interrompono la pipeline (già garantito dal `try/except Exception: pass` nella sua implementazione).
- Nessuna modifica al comportamento di `min_elapsed_seconds`/free-tier guard/idle-timeout esistenti — questo task è ortogonale a quei meccanismi.

### Test di accettazione
1. Un test che verifica che con `show_monitor_verbose=False` (default), il rendering di `LiveTerminalMonitor` produca una singola riga (non il box multi-riga), contenente job/token/costo/modello.
2. Un test con `show_monitor_verbose=True` che verifica il comportamento invariato del box esistente.
3. Un test che verifica che superato il 50% di `timeout_seconds` durante lo streaming, la riga compatta contenga il tag di avviso (es. `⚠lento`).
4. Un test che simula `KeyboardInterrupt` sollevata durante l'iterazione di `response.iter_lines()` (mockando un generatore che solleva `KeyboardInterrupt` dopo il primo chunk) e verifica che il client proceda al failover cross-route configurato, invece di propagare l'eccezione fino a uccidere il processo.
5. Un test per `_append_debug_log`/il parametro `lesson_dir` di `call_structured`: verificare che dopo una chiamata riuscita con `lesson_dir=tmp_path`, il file `llm_debug.log` contenga almeno una riga JSON valida con i campi attesi.
6. Un test per il riepilogo costi di `cmd_run`: verificare che dopo un run mockato con più job, l'output contenga il blocco "RIEPILOGO COSTI SESSIONE" con i costi per job e il totale.
7. Rieseguire l'intera suite e confermare zero regressioni sui test esistenti (189 attuali + i nuovi).

---

## C. Documentare il pricing custom in `rt.config.yaml.example`

**Nessun cambio di codice** — la funzionalità esiste già e basta (`rt/llm/pricing.py:81-85`, `custom_pricing` verificato prima della tabella hardcoded). Aggiungere in `rt.config.yaml.example`, come sezione commentata separata (non attiva di default):
```yaml
# ------------------------------------------------------------------------------
# ESEMPIO: PREZZI CUSTOM (sostituiscono le stime hardcoded in rt/llm/pricing.py)
# ------------------------------------------------------------------------------
# I prezzi in rt/llm/pricing.py sono stime di riferimento. Per usare i prezzi reali
# e aggiornati, dichiarali qui — hanno SEMPRE precedenza sulla tabella hardcoded.
# IMPORTANTE: la chiave del modello deve corrispondere ESATTAMENTE (minuscolo, senza
# eventuale prefisso '~') al valore "model:" configurato per quella route — a differenza
# della tabella di default, qui NON c'è alcun matching approssimato per prefissi/segmenti.
# pricing:
#   deepseek:
#     deepseek-v4-flash:
#       input_per_million: 0.14    # USD per 1M token di input
#       output_per_million: 0.28   # USD per 1M token di output
#       # reasoning_per_million: 0.14   # opzionale: se assente, usa output_per_million
#   google:
#     gemini-3.5-flash-lite:
#       input_per_million: 0.075
#       output_per_million: 0.30
```
Aggiungere anche una riga in `docs/ARCHITECTURE.md` (sezione sul routing/telemetria) che menziona questa possibilità con un rimando a `rt.config.yaml.example`.

---

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q` e confermare zero regressioni. Verificare che la CI (`.github/workflows/tests.yml`) passi su entrambe le versioni Python della matrice per il commit di questo task.
