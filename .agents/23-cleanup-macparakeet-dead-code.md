# Task 23 — Pulizia post-migrazione macparakeet-cli (codice morto + doc residue)

Indipendente dagli altri task. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa
direttamente, senza produrre un piano preliminare.

## Contesto

Durante la revisione dei task 19-22 (già committati localmente, non ancora pushati) ho
verificato empiricamente su questa macchina — installando davvero `macparakeet-cli` ed
eseguendo una trascrizione reale — che `macparakeet-cli transcribe --format json <file>` (senza
`--output-dir`) scrive SEMPRE l'oggetto `Transcription` su **stdout**, mai su un file. Ho anche
corretto direttamente in revisione due bug di importazione/credenziali e un timeout troppo
corto nella discovery Telegram (già commit locali separati). Restano da sistemare alcuni residui
di codice morto e testo di help/doc non aggiornato, elencati sotto — troppo numerosi e sparsi
per un fix diretto rapido in revisione, da qui questo task dedicato.

## 1. Rimuovere il fallback-da-file morto (mai eseguito, confermato empiricamente e dai test)

In `rt/pipeline/setup.py`, dentro `run_setup` (branch di trascrizione reale): rimuovi la
variabile `tmp_json = os.path.join(target_folder_path, f".tmp_mw_{audio_idx}.json")` e tutto il
blocco che tenta di leggere `raw_data` da quel file se il parsing di `res_json.stdout` fallisce
(incluso il successivo `if os.path.isfile(tmp_json): os.remove(tmp_json)` sia nel branch di
errore sia dopo il parsing riuscito). `macparakeet-cli` non riceve mai un flag `-o`/`--output-dir`
in questa invocazione (trascrizione di un singolo file), quindi quel file non viene mai scritto:
il ramo che lo legge è morto (nessun test lo esercita, l'ho verificato). Semplifica direttamente
a: prova a fare `json.loads(res_json.stdout)`, se fallisce o `res_json.returncode != 0` solleva
`SetupError` con lo stesso messaggio già presente.

Stessa pulizia in `rt/core/recall_stt.py::transcribe_voice_answer`: rimuovi
`tempfile.mkstemp(suffix=".json")`/`tmp_json_fd`/`tmp_json_path` (mai scritto da
`macparakeet-cli` per lo stesso motivo) e il blocco `try/finally` che lo elimina — il comando
non passa più nessun path di output, quindi non serve né crearlo né ripulirlo. Semplifica a
un parsing diretto di `result.stdout`.

Verifica sempre coi test esistenti (`tests/test_setup.py`, `tests/test_recall_evaluation_voice.py`)
che simulano già solo la risposta via stdout — non dovrebbero richiedere modifiche, ma
eseguili per conferma dopo la semplificazione.

## 2. Sweep testo residuo "MacWhisper" non aggiornato dal Task 19

Questi punti sono rimasti con il nome del vecchio motore anche se il codice ora usa
`macparakeet-cli` di default — aggiornali per coerenza con `rt -h`/i messaggi mostrati
all'utente (uno degli obiettivi originari di pulizia di questo progetto era proprio la
coerenza tra help e comportamento reale):

- `rt/cli.py`: riga 391 `"""Setup nativo per l'ingest di file audio, trascrizione MacWhisper e metadati."""`; riga 716 `help=f"Modello MacWhisper per trascrizione (default: {DEFAULT_MODEL})"`; riga 736 `help="Esegue l'ingest di file audio, trascrizione MacWhisper e metadati"`. Sostituisci "MacWhisper" con "macparakeet-cli" in tutti e 3.
- `rt/pipeline/setup.py`: docstring di modulo riga 3 ("trascrizione MacWhisper ASR"); docstring di `generate_deterministic_mock_asr` riga ~206 ("senza invocare MacWhisper"); `description` dell'`ArgumentParser` in `main()` riga ~624 ("Setup cartella, trascrizione MacWhisper e metadati YAML"). Aggiorna tutti e 3 a "macparakeet-cli" (o genericamente "il motore ASR configurato" dove più naturale).
- `rt/pipeline/prepare.py` riga ~63: messaggio d'errore mostrato REALMENTE all'utente
  (`"Esegui prima la trascrizione ASR con MacWhisper per generare trascritto grezzo.json."`).
  Aggiorna a "macparakeet-cli" — è un messaggio funzionale visto dall'utente in un caso d'errore
  reale, non solo un commento.
- `rt/core/segments.py`: docstring di modulo riga 4 ("Supporta sia l'export JSON nativo di
  MacWhisper..."). Aggiorna per menzionare anche/principalmente `macparakeet-cli` (Caso 4),
  mantenendo la menzione di MacWhisper come formato storico ancora supportato (Caso 1) — non
  cancellare l'informazione, solo aggiornare qual è il motore predefinito oggi.
- `rt/telegram/daemon.py` riga ~841: docstring `"""Risposta vocale a una domanda di recall:
  scarica, trascrive con MacWhisper, valuta."""` → aggiorna a "macparakeet".
- `docs/DEVELOPMENT.md` riga ~48: `"test_segments.py: parser MacWhisper, intervalli temporali
  e finestra di contesto scorrevole ~90s."` → aggiorna per menzionare anche il parser
  macparakeet-cli (Caso 4) aggiunto dal Task 19.
- `docs/ALTERNATIVE_TRANSCRIPTION.md`: la sezione "### 1. Setup della Lezione senza MacWhisper"
  (procedura passo-passo) e il paragrafo successivo che dice "...senza tentare di invocare
  MacWhisper" — dato che il resto del documento (aggiornato dal Task 19) ora tratta
  macparakeet-cli come motore predefinito e MacWhisper come storico/alternativo, rinomina questa
  sezione in coerenza (es. "Setup della Lezione senza macparakeet-cli") e aggiorna il testo del
  paragrafo di conseguenza.

Non serve toccare `.agents/18-install-script.md` (task file storico di un round già concluso,
resta un archivio di cosa è stato chiesto all'epoca, non documentazione live) né i riferimenti
a MacWhisper dentro `.agents/19-macparakeet-migration.md`/`22-rt-config-wizard-stt-pricing-finish.md`
stessi (stesso motivo).

## Verifica finale

1. `python3 -m pytest tests/ -q` — l'intera suite continua a passare (598 test all'ultimo giro).
2. `grep -rn "MacWhisper\|macwhisper" rt/ docs/ README.md` dopo le modifiche: gli unici risultati
   rimasti dovrebbero essere le menzioni intenzionali del formato storico/legacy (Caso 1 in
   `rt/core/segments.py`, `docs/ALTERNATIVE_TRANSCRIPTION.md`), non testo di help/errore/docstring
   che implica ancora che MacWhisper sia il motore predefinito.
3. Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga
   toccata (vedi `.agents/00-README.md`).
