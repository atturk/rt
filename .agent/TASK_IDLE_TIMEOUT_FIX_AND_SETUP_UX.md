Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Fix reale del timeout di inattività, UX del setup/trascrizione, piccole rifiniture

## Contesto

Durante un test e2e reale è emerso che il timeout di inattività (idle_read_timeout, 45s di default) NON scatta come previsto: un job `outline` è rimasto bloccato per oltre 100 secondi (su un deadline di 300s) con 0 progressi reali, senza che il meccanismo di sicurezza intervenisse. Causa identificata con certezza leggendo il codice. Insieme a questo, sono stati verificati e confermati altri problemi di esperienza utente durante `rt run` con audio in ingresso.

---

## A. Fix reale del timeout di inattività (bug, non solo tuning)

### Causa esatta
`stream_req_timeout` (`rt/llm/client.py`, calcolato riga ~354-355) è un **timeout di socket** passato a `requests.post(timeout=..., stream=True)`. Per come funzionano `requests`/`urllib3`, questo timeout scatta solo se **non arriva nessun byte** per quella durata — e si resetta ad ogni singola lettura di rete, comprese le righe SSE di keep-alive che OpenRouter invia periodicamente per evitare timeout dei client (righe che non iniziano con `data:` e che `parse_stream_line` scarta correttamente come "non contenuto", riga 84-86 in `rt/llm/providers/openrouter.py` — ma quei byte sono comunque arrivati sul socket, quindi il timer si resetta comunque). Risultato: un modello completamente bloccato può restare "vivo" fino all'intero deadline del job, purché arrivi almeno un keep-alive ogni 45s.

Non esiste oggi alcun controllo che misuri il tempo trascorso dall'**ultimo contenuto o reasoning realmente ricevuto** (`t_last_chunk` in `rt/llm/client.py` viene tracciato ma usato solo per telemetria, mai per decidere un abort — verificato).

### Fix
In `rt/llm/client.py`, nel blocco di streaming (dentro `if hasattr(response, "iter_lines")...`, circa righe 396-402):

1. Subito dopo `streamed_any_chunk = False` (riga 399), inizializzare:
```python
t_last_progress = time.monotonic()
```
(va reinizializzato qui perché questo blocco è già dentro lo scope per-tentativo, quindi si azzera correttamente ad ogni retry/nuova route — nessuna modifica aggiuntiva necessaria per quello).

2. Subito dopo il controllo di deadline esistente (righe 403-415, `if deadline is not None and now_mono >= deadline: ... raise TimeoutFailure(...)`), aggiungere un nuovo controllo che riusa lo stesso `now_mono` già calcolato in questa iterazione:
```python
if now_mono - t_last_progress > effective_idle_read_timeout:
    try:
        response.close()
    except Exception:
        pass
    raise TimeoutFailure(
        f"Nessun contenuto o reasoning reale ricevuto da oltre {effective_idle_read_timeout:.0f}s, "
        f"nonostante il socket resti attivo (probabili keep-alive silenziosi del provider). "
        f"Streaming interrotto precauzionalmente.",
        provider=provider_name,
        model=model_name
    )
```

3. Subito dopo le righe esistenti `if chunk.content_delta: content_parts.append(chunk.content_delta)` / `if chunk.reasoning_delta: reasoning_parts.append(chunk.reasoning_delta)` (righe 439-442), aggiungere:
```python
if chunk.content_delta or chunk.reasoning_delta:
    t_last_progress = now_mono
```

Questo è un `TimeoutFailure` a tutti gli effetti (stessa `failure_class`, stesso meccanismo di retry same-route e fallback già esistenti) — nessuna modifica a `classify_failure`, al router, o al blocco di decisione retry. `effective_idle_read_timeout` è la variabile già risolta più sopra nella funzione (da config o override), riusala così com'è.

### Edge case e invarianti
- Il controllo di deadline complessivo esistente (righe 403-415) resta invariato e prioritario — se scatta prima lui, va bene così.
- Non toccare il calcolo di `stream_req_timeout`/il timeout di socket esistente: questo nuovo controllo è complementare (cattura il caso "byte in arrivo ma nessun progresso reale"), non sostitutivo (il timeout di socket resta l'ultima rete di sicurezza contro una connessione davvero morta).
- Il reasoning conta come "progresso" tanto quanto il content — un modello in una fase di "thinking" lunga ma attiva non deve essere interrotto ingiustamente.

### Test di accettazione
In `tests/test_llm_timeout_retry.py` o file dedicato:
1. Simulare uno stream che manda 1 chunk di contenuto reale, poi solo righe SSE di commento/keep-alive (non `data:`, quindi ignorate da `parse_stream_line`) per un tempo simulato superiore a `effective_idle_read_timeout`, usando `patch("time.monotonic", side_effect=...)` per avanzare il tempo simulato ad ogni riga. Verificare che venga sollevata `TimeoutFailure` con il nuovo messaggio, ben PRIMA che il deadline complessivo del job venga raggiunto.
2. Test di non-regressione: uno stream che manda contenuto reale a intervalli regolari (ciascuno entro la soglia di idle) deve completare con successo, senza mai attivare questo nuovo controllo.
3. Rieseguire l'intera suite e confermare zero regressioni sui test di retry/timeout esistenti.

---

## B. Ordine degli step e feedback live durante setup/trascrizione MacWhisper

### Causa verificata
In `rt/pipeline/setup.py`, `run_setup()` esegue TUTTO il lavoro (creazione cartella, metadata, le due chiamate bloccanti `subprocess.run` per trascrizione JSON e Markdown, copia audio, scrittura `info.yaml`) prima ancora di ritornare. In `rt/cli.py`, `cmd_run` (righe 605-633) stampa `"[1/9] SETUP..."` PRIMA di chiamare `run_setup`, poi `"✔ Cartella lezione: ..."` e `"[2/9] MACWHISPER TRANSCRIPTION..."` solo DOPO che `run_setup` è già tornato — cioè dopo che la trascrizione (spesso già conclusa in pochi secondi) è già avvenuta. Risultato: le conferme appaiono tutte insieme con un ritardo percepito come "blocco".

### Fix 1: callback di progresso per allineare le stampe al momento reale in cui accadono
In `rt/pipeline/setup.py`, l'import `typing` esistente (riga 14: `from typing import Dict, Any, List, Optional, Tuple, Union`) NON include `Callable` — aggiungerlo. Poi aggiungere un parametro opzionale a `run_setup`:
```python
def run_setup(
    ...,
    on_progress: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
```
Chiamarlo in 2 punti:
1. Subito dopo `os.makedirs(target_folder_path, exist_ok=True)` (riga 381), prima di procedere con mock/skip/trascrizione:
```python
if on_progress:
    on_progress(f"✔ Cartella lezione: {target_folder_path}")
```
2. Subito dopo la verifica di `find_mw_binary()` (riga 401-405), prima del loop sui file audio (riga 412), SOLO nel ramo `elif not skip_transcribe:` (quindi solo per la trascrizione reale via MacWhisper, non per mock/skip):
```python
if on_progress:
    on_progress("\n[2/9] MACWHISPER TRANSCRIPTION (ASR Timecoded)...")
```

In `rt/cli.py`, `cmd_run` (righe 605-633):
- Passare `on_progress=print` alla chiamata di `run_setup` (riga 607).
- Rimuovere la stampa `print(f"✔ Cartella lezione: {lesson_dir}")` (riga 620) — ora arriva dalla callback al momento giusto.
- Nel blocco dopo il ritorno di `run_setup` (righe 625-633), la stampa `"\n[2/9] MACWHISPER TRANSCRIPTION..."` va mantenuta SOLO nei rami `mock_mode`/`skip_transcribe` (che non passano mai dalla callback, essendo istantanei), rimossa dal ramo `else` finale (dove ormai è già stata stampata dalla callback):
```python
if mock_mode:
    print("\n[2/9] MACWHISPER TRANSCRIPTION (ASR Timecoded)...")
    print("⏩ [MOCK ASR] Trascrizione deterministica generata offline a costo zero.")
elif getattr(args, "skip_transcribe", False):
    print("\n[2/9] MACWHISPER TRANSCRIPTION (ASR Timecoded)...")
    print("⚠️  [SKIP] Trascrizione saltata (--skip-transcribe). Stato impostato su METADATA_ONLY.")
    print("La pipeline si arresta qui. Esegui la trascrizione per procedere con 'rt prepare'.")
    return
else:
    print(f"✔ Trascrizione completata: {setup_res.get('trascritto_json')}")
```

### Fix 2: indicatore live durante l'attesa di MacWhisper (nessun timeout duro — deciso esplicitamente di non introdurne uno, per non penalizzare modelli più pesanti o macchine più lente)
Aggiungere `rich` a `requirements.txt` (nuova dipendenza, libreria matura e leggera, solo per gli indicatori di stato — non un framework TUI completo).

In `rt/pipeline/setup.py`, sostituire le due chiamate bloccanti `subprocess.run(cmd_json, capture_output=True, text=True)` / `subprocess.run(cmd_md, capture_output=True, text=True)` (righe 436, 446) con `subprocess.Popen` + polling, avvolto in uno spinner `rich`:
```python
from rich.console import Console

def _run_mw_with_spinner(cmd: List[str], label: str) -> subprocess.CompletedProcess:
    console = Console()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start = time.monotonic()
    with console.status(f"[cyan]{label}...", spinner="dots") as status:
        while proc.poll() is None:
            elapsed = int(time.monotonic() - start)
            status.update(f"[cyan]{label}... ({elapsed}s)")
            time.sleep(0.5)
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=stderr)
```
E sostituire le due chiamate:
```python
res_json = _run_mw_with_spinner(cmd_json, "Trascrizione MacWhisper (JSON)")
...
res_md = _run_mw_with_spinner(cmd_md, "Trascrizione MacWhisper (Markdown)")
```
Il resto della logica (controllo `returncode`, `os.path.isfile`, `os.path.getsize`, gestione errori) resta **invariato** — `_run_mw_with_spinner` restituisce lo stesso tipo (`subprocess.CompletedProcess`) con gli stessi attributi (`returncode`, `stdout`, `stderr`) già usati subito dopo.

### Edge case
- Nessun timeout duro sull'attesa di MacWhisper — solo feedback visivo, come deciso esplicitamente.
- Il fallback per l'export Markdown (vedi punto C sotto) resta com'è nella logica, cambia solo il meccanismo di invocazione.
- Verificare che lo spinner `rich` non interferisca con l'output del `LiveTerminalMonitor` esistente usato più avanti nella pipeline per le chiamate LLM (sono momenti diversi e non si sovrappongono mai — la trascrizione avviene prima di qualunque chiamata LLM).

### Test di accettazione
- Un test che verifica che `run_setup` con `on_progress` impostato a una funzione di test (che accumula i messaggi in una lista) riceva le chiamate nell'ordine e con il contenuto atteso, con `mock_asr=True` e poi con lo scenario di trascrizione reale mockando `subprocess.Popen`.
- Un test che verifica che `_run_mw_with_spinner` restituisca correttamente `returncode`/`stdout`/`stderr` mockando `subprocess.Popen` (nessuna chiamata reale a MacWhisper nei test, come già avviene altrove nella suite).
- Nessuna modifica al comportamento di `--mock`/`--skip-transcribe`, che non attraversano mai questo codice.

---

## C. Chiarire il messaggio di fallimento dell'export Markdown di MacWhisper (nessun hard-fail)

### Causa verificata
`rt/pipeline/setup.py`, riga 447-448: se l'export Markdown di `mw` fallisce, oggi viene solo stampato un avviso, senza sollevare errore. **Verificato che questo è corretto e va mantenuto così**: il file Markdown grezzo di MacWhisper non è mai la fonte di verità (lo è sempre e solo il JSON, già validato con hard-fail subito sopra), e un Markdown normalizzato equivalente viene comunque rigenerato più avanti nella pipeline da `rt prepare` a partire dai segmenti validati (`export_normalized_transcript_md` in `rt/core/segments.py`). L'unico intervento è rendere il messaggio più chiaro, specificando che non ha alcun impatto sulla pipeline:
```python
if res_md.returncode != 0:
    print(f"{YELLOW}⚠ Export Markdown di MacWhisper non riuscito (codice {res_md.returncode}) — nessun impatto: "
          f"il Markdown verrà comunque rigenerato da 'rt prepare' a partire dal JSON validato.{RESET}")
```
Nessun altro cambio di comportamento.

---

## D. Chiarire il concetto di `credential` in `rt.config.yaml.example` (solo commento, nessun cambio di codice)

Aggiungere, vicino alla prima occorrenza di `credential:` in `rt.config.yaml.example`, un commento esplicativo:
```yaml
# 'credential' identifica una chiave API specifica sotto un provider (utile quando hai più chiavi
# per lo stesso provider, es. per distribuire il carico su più quote indipendenti — è il caso di
# google_1/google_2 qui sotto). Se hai una sola chiave per provider, 'credential' può essere omesso:
# verrà usata automaticamente quella di default per quel provider.
```
Nessuna modifica a `rt/core/config.py`/`rt/llm/credentials.py` in questo punto — è stato valutato esplicitamente di NON rimuovere il concetto di `credential` (permette in futuro di gestire più chiavi per lo stesso provider, es. due chiavi OpenRouter, senza dover moltiplicare i nomi di provider).

---

## Invarianti generali da rispettare in tutto il task

1. Nessuna modifica a `classify_failure`, al routing engine, o al meccanismo di retry esistente — il punto A riusa `TimeoutFailure` così com'è.
2. Nessun timeout duro introdotto sull'attesa di MacWhisper (deciso esplicitamente).
3. `--mock`/`--skip-transcribe` continuano a funzionare esattamente come oggi, non attraversano il nuovo codice di spinner/callback per la trascrizione reale.
4. L'export Markdown di MacWhisper resta un fallimento "soft" (solo avviso, mai un'eccezione) — comportamento confermato corretto, non un bug.
5. Nessuna modifica al concetto di `credential` — solo documentazione.

## Verifica finale
Rieseguire `python3 -m pytest tests/ -q` e confermare zero regressioni sui test esistenti (172 attuali + i nuovi). Assicurarsi che la CI (`.github/workflows/tests.yml`) passi su entrambe le versioni Python della matrice per il commit di questo task (che ora installa anche `rich` via `requirements.txt`/`requirements-dev.txt`).
