# Task 35 — CRITICO: `rt run`/`rt setup` si bloccano indefinitamente in trascrizione

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare. Priorità massima: questo è un
bug bloccante che impedisce l'uso base della pipeline su una lezione reale.

## Contesto

Test empirico diretto su un MacBook Air reale: `rt run <file_audio_86_minuti>.m4a` si è
bloccato oltre i 200 secondi in `[2/9] MACPARAKEET TRANSCRIPTION` senza mai completarsi (la
cartella di destinazione è rimasta vuota), fino a interruzione manuale. Lo stesso identico file
audio, trascritto lanciando manualmente `macparakeet-cli transcribe <file> --no-diarize --format
json --output-dir <dir>` (che scrive su un FILE invece che stampare su stdout), si è completato
regolarmente producendo un JSON valido.

**Causa radice**: `rt/pipeline/setup.py::run_setup`, sezione "5. ESECUZIONE TRASCRIZIONE ASR"
(righe 450-465), costruisce il comando SENZA `--output-dir`:
```python
cmd_json = [
    parakeet_bin, "transcribe",
    "--format", "json",
]
if model:
    model_param = model.replace("parakeet-", "") if model.startswith("parakeet-") else model
    cmd_json.extend(["--parakeet-model", model_param])
cmd_json.append(aud_abs)
```
Senza `--output-dir`, per un singolo file di input macparakeet-cli scrive l'INTERO JSON di
trascrizione su **stdout**. Per una lezione di 86 minuti questo include un `wordTimestamps` con
una entry per OGNI parola pronunciata (~9500 parole in questo caso, verificato nel JSON reale
prodotto dal test manuale — vedi `wordRange.endIndexExclusive: 9495` nell'ultimo segmento), quindi
centinaia di KB di testo.

`_run_transcribe_with_spinner` (righe 284-294) apre il processo con
`subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)` e poi fa
polling con `proc.poll()` in un ciclo `while` **senza mai leggere `proc.stdout`/`proc.stderr`**
finché il processo non termina — solo dopo il ciclo chiama `proc.communicate()`. Il pipe di
stdout tra processo padre e figlio ha un buffer limitato (tipicamente 64KB su macOS): se il
figlio produce più output di quanto il padre stia consumando, la `write()` del figlio si blocca
in attesa che il buffer si svuoti. Dato che il padre non legge mai finché non vede `poll()`
diverso da `None`, e il figlio non termina mai perché è bloccato a scrivere — **deadlock
permanente**, per qualunque trascrizione abbastanza lunga da superare i 64KB di JSON (in pratica
qualunque lezione universitaria reale di durata normale).

Inoltre, senza specificare `--speaker-detection`/`--no-diarize`, macparakeet-cli usa
`app-default` per la diarizzazione (segue la preferenza salvata nella GUI, che potrebbe averla
attiva). RT non usa la diarizzazione in nessun punto della pipeline: va sempre passato
`--no-diarize` esplicitamente, sia per correttezza sia perché la diarizzazione aggiunge un
passaggio di elaborazione più lento e non necessario.

**Bug collaterale nel drag-and-drop**: trascinare nel Terminale macOS un file con una virgola nel
nome produce un path tipo `/Users/.../ANATOMIA I\, 6 maggio.m4a` (virgola preceduta da un
backslash singolo). `clean_input_path` (righe 48-56) gestisce già `\ ` (spazio), `\(`, `\)`,
`\[`, `\]` ma non `\,`, quindi il file non viene trovato
(`SetupError: File audio non trovato: '.../ANATOMIA I\, 6 maggio.m4a'`), riprodotto
empiricamente sia con `rt setup` che con `rt run`.

**Dato di confidenza per-parola mai preservato**: lo schema ufficiale di macparakeet-cli
(verificato in `spec/01-data-model.md` del repo https://github.com/moona3k/macparakeet) ha il
campo `confidence` SOLO dentro ogni elemento di `wordTimestamps` (per singola parola: `word`,
`startMs`, `endMs`, `confidence`, `speakerId`), MAI dentro `transcriptSegments` (che ha `id`,
`startMs`, `endMs`, `speakerId`, `speakerLabel`, `text`, e `wordRange.startIndex`/
`endIndexExclusive` — un range semi-aperto sull'array `wordTimestamps` per citare le parole
esatte del segmento). Questo significa che `rt/core/segments.py::parse_segments_from_json`
righe 74-76 (`confidence=item.get("confidence")` sul singolo `transcriptSegment`) non ha MAI
popolato nulla per l'export macparakeet-cli: è sempre `None`, un campo morto ereditato
dall'integrazione MacWhisper precedente. Il resto della pipeline
(`rt/pipeline/review_asr.py`) non usa comunque questo campo per il proprio confidence-gating:
usa una confidenza AUTO-VALUTATA dal modello LLM sul testo (`ASRIssue.confidence`, vedi
`rt/core/models.py:124`, "non una probabilità fonetica calibrata sull'audio originale"), non un
dato acustico reale. Va quindi preservato il dato di confidenza per-parola nel salvataggio dei
segmenti, così che sia disponibile per usi futuri (inclusa una possibile fase di review basata
su confidenza acustica reale + giudizio LLM, discussa separatamente e non in scope di questo
task).

## Modifiche

### 1. `rt/pipeline/setup.py::clean_input_path` — fix escape virgola

Aggiungi `.replace(r"\,", ",")` alla catena di sostituzioni di riga 55, insieme agli altri
caratteri già gestiti.

### 2. `rt/pipeline/setup.py::run_setup` — elimina il deadlock, `--output-dir` + `--no-diarize`

Riscrivi la sezione "5. ESECUZIONE TRASCRIZIONE ASR" (righe ~450-501, loop `for audio_idx,
aud_file in enumerate(cleaned_audios, start=1)`) in modo che ogni invocazione:
- Usi una directory temporanea dedicata (es. `tempfile.mkdtemp(prefix="rt_macparakeet_")`, ripulita
  con `shutil.rmtree` a fine funzione, anche nel path d'errore) come `--output-dir`, MAI
  `target_folder_path` direttamente (macparakeet-cli sceglie da sé il nome del file di output
  in base al nome del file audio, es. `ANATOMIA I, 6 maggio.json`, che non coincide col nome
  fisso `trascritto grezzo.json` che RT si aspetta).
- Aggiunga sempre `--no-diarize` al comando.
- Dopo l'esecuzione, legga il JSON dal file scritto nella directory temporanea (verifica
  empiricamente il nome esatto del file prodotto — deriva dal basename senza estensione del file
  audio di input) invece che da `stdout`.
- Verifichi solo il return code per l'hard-fail esistente (il controllo
  `res_json.returncode != 0 or raw_data is None` righe 477-481 va adattato: ora l'assenza/
  illeggibilità del file di output è il segnale di fallimento, non uno stdout vuoto/non
  parsabile).

Con l'output ora su file, il polling in `_run_transcribe_with_spinner` (righe 284-294) non deve
più accumulare stdout in un buffer implicito non letto: sostituisci il ciclo `while
proc.poll() is None: ... time.sleep(0.5)` con lettura non bloccante riga per riga da
`proc.stdout` (unifica `stderr=subprocess.STDOUT` per semplicità, dato che ora stdout porta solo
le righe di progresso testuali tipo `Transcribing... NN%`, non più il JSON), così il pipe non si
riempie mai indipendentemente dalla lunghezza dell'output futuro — questo è un fix strutturale
che elimina la classe di bug, non solo il sintomo per questo caso specifico.

Applica lo stesso schema a tutte le iterazioni del loop per file audio multipli.

### 3. Barra di progresso leggibile

Sfruttando la lettura riga-per-riga introdotta al punto 2, aggiorna lo status `rich` con l'ultima
percentuale vista (regex semplice tipo `re.search(r"(\d+)%", line)` sull'ultima riga letta)
invece del solo contatore di secondi trascorsi attuale. Se una riga non contiene una percentuale
(es. `Converting audio...`, `Preparing speech model...`), mostra quel testo di stato al posto
della percentuale — sempre una singola riga che si aggiorna in place (già garantito da
`console.status`), non una riga stampata per ogni progresso come fa macparakeet-cli di suo in
modalità non interattiva.

### 4. Preserva la confidenza per-parola

Nel payload finale salvato in `trascritto grezzo.json` (righe 503-512), includi il campo
`wordTimestamps` letto dal JSON prodotto da macparakeet-cli, applicando lo stesso offset
temporale cumulativo (`cumulative_offset_ms`) già usato per `transcriptSegments` quando ci sono
più file audio concatenati (stesso pattern di `all_segments_combined`, ma per
`wordTimestamps`).

In `rt/core/segments.py::parse_segments_from_json`, ramo macparakeet-cli (righe 52-76): calcola
un `confidence` di segmento aggregato come media delle `confidence` delle parole nel range
`wordRange.startIndex:wordRange.endIndexExclusive` sull'array `wordTimestamps` del documento
JSON originale, se disponibile — altrimenti lascia `None` come oggi (retrocompatibile con JSON
senza `wordTimestamps`, incluso il mock ASR esistente che non deve essere toccato). Questo
sostituisce il campo oggi sempre-`None` con un valore reale calcolato dal dato per-parola;
nessun consumer esistente usa questo campo per gating, quindi zero rischio di regressione
comportamentale — è solo dato in più disponibile per usi futuri.

## Test

- Test che verifica che il comando costruito per `subprocess.Popen` include sempre
  `--output-dir` e `--no-diarize` (mockando `subprocess.Popen` o l'equivalente, verifica gli
  `args` passati).
- Test che simula un file scritto da macparakeet-cli in `--output-dir` con un
  `wordTimestamps` grande (es. migliaia di entry fittizie, per superare abbondantemente 64KB se
  venisse per errore rimandato a stdout) e verifica che la funzione completi senza bloccarsi in
  un tempo ragionevole (bound temporale nel test stesso, es. eseguendo la chiamata in un thread
  con `join(timeout=...)` e fallendo il test se il thread è ancora vivo oltre soglia — verifica
  prima se il progetto ha già un pattern per questo genere di test, altrimenti usa questo
  approccio senza introdurre nuove dipendenze).
- Test su `clean_input_path` con un path contenente `\,` (es.
  `"/Users/foo/ANATOMIA I\\, 6 maggio.m4a"` → `"/Users/foo/ANATOMIA I, 6 maggio.m4a"`).
- Test su `parse_segments_from_json` che verifica il calcolo corretto della `confidence`
  aggregata di segmento da un JSON di esempio con `transcriptSegments` + `wordTimestamps` +
  `wordRange`, e che resti `None` quando `wordTimestamps` è assente dal documento.
- Adatta i test esistenti in `tests/test_setup.py` che mockano `_run_transcribe_with_spinner`
  con un `CompletedProcess(stdout=<json_string>, ...)` (es. `test_run_setup_on_progress_callback`,
  `test_macparakeet_single_run_per_audio`) al nuovo schema basato su file — se necessario, fai
  scrivere al mock il JSON su un file temporaneo nella directory che la funzione userebbe come
  `--output-dir`, invece che restituirlo su `stdout`.
- Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`).

Non toccare `generate_deterministic_mock_asr` (il mock `--mock` resta invariato, non passa da
macparakeet-cli, non è affetto da questo bug).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se possibile nell'ambiente Antigravity (macparakeet-cli installato e funzionante): test
   manuale reale con `rt run <file_audio_almeno_20_minuti>.m4a`, verificando che (a) non si
   blocchi, (b) `trascritto grezzo.json` risultante contenga `wordTimestamps` con `confidence`
   per parola, (c) i segmenti abbiano una `confidence` aggregata non-null. Se l'ambiente non lo
   consente, documentalo esplicitamente nel riepilogo finale: sarà l'utente a rifare questo test
   empirico su un Mac reale prima del merge.
