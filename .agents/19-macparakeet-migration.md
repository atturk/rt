# Task 19 — Sostituire MacWhisper con macparakeet-cli

Indipendente dagli altri task in questa cartella. Nel progetto RT
(/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un piano
preliminare.

## Contesto

RT oggi usa MacWhisper (binario `mw`, richiesto in `/Applications/MacWhisper.app`) per
trascrivere le lezioni. MacWhisper è un'app commerciale/a pagamento per usare la CLI con
i modelli Parakeet. `macparakeet-cli` (https://github.com/moona3k/macparakeet,
`brew install moona3k/tap/macparakeet-cli`) è gratuito, open source, ed è specificamente
basato sul modello Parakeet di NVIDIA (già il modello preferito dall'utente:
`DEFAULT_MODEL = "parakeet-pro:nvidia_parakeet-v3"` in `rt/pipeline/setup.py`). Decisione
dell'utente: **sostituire** MacWhisper, non aggiungerlo come alternativa — rimuovi il codice
MacWhisper-specifico invece di tenerlo morto in parallelo.

**Attenzione**: la documentazione pubblica di `macparakeet-cli` reperibile online (README,
`integrations/README.md`, `spec/contracts/cli-json-v1.md`) NON specifica in modo completo lo
schema JSON esatto di `transcribe --format json` (nomi campi, se i timestamp sono in secondi o
millisecondi, se l'output va su stdout o su file). La stessa documentazione del progetto
sconsiglia di fidarsi ciecamente: dice esplicitamente che per `--format json` "may write a file
and print the path" e di verificare con `macparakeet-cli spec --json` sul binario installato.
**Non indovinare lo schema dai frammenti trovati online: verificalo empiricamente sul binario
reale installato su questa macchina**, come descritto nei passi sotto.

## Passi

### 1. Installazione ed esplorazione reale del binario

```bash
brew install moona3k/tap/macparakeet-cli   # idempotente, salta se già installato
macparakeet-cli --version
macparakeet-cli spec --json                # catalogo machine-readable dei comandi reali
macparakeet-cli transcribe --help
macparakeet-cli models list
```

Se il modello Parakeet v3 non risulta già scaricato/selezionato, scaricalo e selezionalo
(`macparakeet-cli models download parakeet-v3`, `macparakeet-cli models select parakeet-v3` o
i comandi equivalenti reali che emergono da `spec --json`/`--help` — usa i nomi comando reali,
non quelli di questo paragrafo se differiscono).

### 2. Test reale end-to-end con audio parlato reale

Non serve una registrazione di lezione vera: genera un audio di test reale con la sintesi
vocale nativa di macOS (voce italiana), così il test è end-to-end autentico e non un mock:
```bash
say -v Alice -o /tmp/rt_macparakeet_test.aiff "Buongiorno a tutti. Oggi parliamo di biochimica e del metabolismo del glucosio. In particolare analizziamo la glicolisi e i suoi enzimi chiave."
ffmpeg -i /tmp/rt_macparakeet_test.aiff /tmp/rt_macparakeet_test.m4a
```
Poi esegui la trascrizione reale con la sintassi e i flag che risultano corretti dal punto 1
(engine/modello Parakeet, formato JSON), ispeziona l'output ottenuto DAVVERO (file o stdout,
a seconda di cosa emerge dal punto 1) e verifica che il testo italiano sia stato trascritto
correttamente (confronta con il testo dato in input a `say`). Se la trascrizione in italiano
risulta scadente con impostazioni di default, prova esplicitamente un flag di lingua
(es. `--language it` o `--language auto`, verifica quale esiste davvero) finché il risultato è
soddisfacente.

Riporta nel resoconto finale la struttura JSON REALE osservata (incolla un estratto vero
dell'output), non quella ipotizzata dai documenti online.

### 3. Adattare `rt/pipeline/setup.py`

- Rinomina `find_mw_binary()` → `find_macparakeet_binary()`: usa `shutil.which("macparakeet-cli")`
  con fallback a `/opt/homebrew/bin/macparakeet-cli` e `/usr/local/bin/macparakeet-cli` (stesso
  pattern difensivo della funzione originale).
- Sostituisci la costruzione del comando in `run_setup` (attualmente
  `[mw_bin, "transcribe", "--model", model, "--format", "json", "--overwrite", "-o", tmp_json, aud_abs]`)
  con l'invocazione reale corretta di `macparakeet-cli` scoperta al punto 1-2. Se
  `macparakeet-cli` non supporta un flag `-o <path>` per un file di output esplicito a percorso
  libero (verificalo: potrebbe scrivere secondo una convenzione propria, es. accanto al file
  audio o in una cartella indicata da `--output-dir`), adatta la logica per spostare/rinominare
  il file prodotto nel `tmp_json` atteso da `run_setup`, oppure per leggere l'output da stdout
  se quella è la modalità corretta — mantieni identico il comportamento a valle (il resto di
  `run_setup` continua a leggere da `tmp_json`/scrivere `trascritto grezzo.json`, non cambiare
  quella parte se non necessario).
- Aggiorna `DEFAULT_MODEL` con un valore sensato per la nuova CLI (es. semplicemente `"parakeet-v3"`
  se `macparakeet-cli` non usa più la sintassi `provider:model` di MacWhisper) e adatta
  `configure_setup_parser`'s `--model` help text di conseguenza. Se la nuova CLI seleziona il
  modello con più flag separati (es. `--engine`/`--parakeet-model`) invece di un singolo
  `--model`, va bene semplificare l'argomento CLI di RT (es. lasciare che l'utente scelga solo se
  vuole `parakeet` o l'engine alternativo whisper via un valore semplice), purché il caso d'uso
  di default (nessun flag passato da `rt run`/`rt setup`) continui a funzionare esattamente come
  oggi senza richiedere nulla in più all'utente.
- `_run_mw_with_spinner` può restare con lo stesso nome/comportamento (è generico, opera su
  qualunque `cmd`) oppure essere rinominato per chiarezza (es. `_run_transcribe_with_spinner`) —
  a tua scelta, purché coerente con le rinomine sopra.
- Aggiorna i messaggi di errore (`SetupError`) che citano "MacWhisper"/"/Applications/MacWhisper.app"
  con il messaggio corretto per `macparakeet-cli` (es. "installalo con `brew install
  moona3k/tap/macparakeet-cli`").

### 4. Adattare `rt/core/segments.py`

`parse_segments_from_json` deve continuare a supportare i 3 formati esistenti (compatibilità
con lezioni storiche già trascritte con MacWhisper, e con l'ingest da motori esterni descritto
in `docs/ALTERNATIVE_TRANSCRIPTION.md`) **e aggiungere il supporto per il formato reale di
macparakeet-cli** osservato al punto 2, se diverso dai 3 esistenti (es. se i timestamp sono in
secondi invece che millisecondi, o se i nomi dei campi sono diversi come `startMs`/`endMs`).
Aggiungi un nuovo `Caso 4` esplicito nella docstring e nel codice se necessario, con lo stesso
stile difensivo degli altri casi (non rompere nulla dei 3 casi esistenti).

### 5. Adattare `rt/core/recall_stt.py`

- Rinomina il branch `stt_engine == "macwhisper"` in `stt_engine == "macparakeet"`.
- Sostituisci `find_mw_binary` con `find_macparakeet_binary` (import da `rt.pipeline.setup`).
- Adatta l'invocazione del comando allo stesso modo del punto 3 (singolo file audio breve,
  stessa sintassi reale verificata).
- Aggiorna il docstring del modulo (righe 3-6) che cita MacWhisper.

### 6. Adattare `rt/core/config.py`

`TelegramRuntimeConfig.RecallConfig.stt_engine`: cambia il default da `"macwhisper"` a
`"macparakeet"` e la description da `"'macwhisper' | 'api'"` a `"'macparakeet' | 'api'"`.

### 7. Aggiornare `install.sh` (Task 18, già completato — questa è un'estensione mirata)

Aggiungi, nella sezione "1. Controllo prerequisiti di sistema" (dopo l'installazione di
`ffmpeg`), un passo idempotente per installare `macparakeet-cli`:
```bash
if command -v macparakeet-cli &>/dev/null; then
    echo "ℹ️ macparakeet-cli è già installato."
else
    echo "🍺 Installazione di macparakeet-cli via Homebrew..."
    brew install moona3k/tap/macparakeet-cli
fi
```
Se dal punto 1 risulta necessario anche un passo di download/selezione del modello Parakeet
(non bundlato con l'installazione brew), aggiungilo qui in modo non bloccante (es. con `|| true`
o un controllo preventivo "già presente"), così una MacBook Air pulita ottiene un motore ASR
funzionante subito dopo `./install.sh`, senza configurazione manuale aggiuntiva. Aggiorna anche
il messaggio di riepilogo finale dello script se questo cambia qualche passo successivo per
l'utente (probabilmente no, dato che ASR ora è automatico).

### 8. Test

Aggiorna/rinomina in `tests/test_setup.py`:
- `test_macwhisper_failure_hard_fails` → adatta i patch (`shutil.which`, il nome della funzione
  `_run_mw_with_spinner`/rinominata, i messaggi attesi) per riflettere `macparakeet-cli`.
- `test_macwhisper_single_run_per_audio` → stessa cosa.
- Qualunque altro test in questo file che assume la sintassi/i path di MacWhisper.

In `tests/test_recall_evaluation_voice.py`: aggiorna le chiamate
`transcribe_voice_answer(audio_path, stt_engine="macwhisper")` a `stt_engine="macparakeet"` e
adatta i mock di conseguenza.

In `tests/test_segments.py`: NON rimuovere i test esistenti per il formato MacWhisper (restano
validi per compatibilità storica) — aggiungi un nuovo test per il Caso 4 (formato reale
macparakeet-cli) usando la struttura JSON osservata realmente al punto 2 come fixture.

Esegui `python3 -m pytest tests/ -q` e correggi finché la suite passa per intero.

### 9. Documentazione

Sostituisci i riferimenti a MacWhisper con macparakeet-cli in:
- `README.md` (riga con "export JSON nativi di MacWhisper").
- `docs/ARCHITECTURE.md` (diagramma con il box "MacWhisper mw").
- `docs/DEVELOPMENT.md` (riga sul prerequisito MacWhisper — nota che ora è installato
  automaticamente da `install.sh`, quindi non è più un prerequisito manuale separato).
- `docs/WORKFLOW.md` (riga sull'invocazione MacWhisper CLI).
- `docs/ALTERNATIVE_TRANSCRIPTION.md`: aggiorna il framing (macparakeet-cli è ora il motore
  predefinito, non più MacWhisper; il documento resta utile per motori ULTERIORMENTE
  alternativi). Mantieni il "Formato MacWhisper" esistente come formato storico supportato, e
  documenta il nuovo formato reale di macparakeet-cli (Caso 4) se differisce, con lo stesso
  livello di dettaglio degli altri casi documentati.

## Nota sul bug di portabilità ricorrente

Vedi `.agents/00-README.md`: se aggiungi o modifichi firme di funzione con annotazioni
`Optional[...]`/`List[...]`/`Dict[...]` da `typing`, verifica sempre che siano importate
esplicitamente in quel file (non fidarti del fatto che i test passino, girano su Python 3.14
che maschera il problema).

## Verifica finale

1. `python3 -m pytest tests/ -q` — tutta la suite passa.
2. Test manuale end-to-end reale (non mock): `./bin/rt setup /tmp/rt_macparakeet_test.m4a -m TEST -a "Verifica macparakeet"` (o `rt run` sullo stesso file) e verifica che la cartella lezione prodotta contenga un `trascritto grezzo.json`/`trascritto grezzo.md` corretti, leggibili da `rt prepare` senza errori.
3. Riporta nel resoconto finale: comando reale usato per invocare `macparakeet-cli`, struttura JSON reale osservata, ed eventuali limitazioni/incertezze rimaste (es. se la selezione lingua italiana ha richiesto un flag esplicito).
