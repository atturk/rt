# Task 45 — Trascrizione delle risposte vocali in active recall rotta (stesso bug del Task 35, mai applicato qui)

Indipendente dagli altri task attivi. Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

L'utente ha segnalato che la trascrizione delle risposte vocali inviate durante l'active recall
via Telegram è "totalmente rotta" (arriva "⚠️ Trascrizione non riuscita: Trascrizione
macparakeet-cli fallita (codice uscita: 1)" per ogni risposta vocale, sistematicamente).

**Causa esatta**: `rt/core/recall_stt.py`, funzione `transcribe_voice_answer` (righe 12-53),
costruisce il comando (riga 26):
```python
cmd = [parakeet_bin, "transcribe", "--format", "json", audio_path]
result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
```
e poi (righe 30-32) tenta `json.loads(result.stdout)` — esattamente il pattern che il Task 35
ha già identificato come rotto e corretto in `rt/pipeline/setup.py` per la trascrizione della
lezione principale: senza `--output-dir`, macparakeet-cli può non stampare affatto un JSON
valido su stdout nel modo atteso da questo codice (a seconda della versione/comportamento del
binario per l'assenza di quel flag), causando un fallimento sistematico. Il Task 35 ha già
risolto lo stesso problema in `rt/pipeline/setup.py` (righe 484-512: `--output-dir` su una
directory temporanea + lettura del JSON da file, non da stdout) — questo secondo call site in
`recall_stt.py`, che gestisce le risposte vocali dell'active recall (chiamato da
`rt/telegram/daemon.py` riga 894 dentro `handle_voice`), non ha mai ricevuto lo stesso
trattamento ed è rimasto sul pattern vecchio/rotto. Manca anche `--no-diarize` (irrilevante per
correttezza ma incoerente con l'altro punto).

## Modifica

Applica in `rt/core/recall_stt.py::transcribe_voice_answer` lo stesso schema già usato in
`rt/pipeline/setup.py` per il Task 35:
- Usa una directory temporanea (`tempfile.mkdtemp()`, ripulita a fine funzione anche nel path
  d'errore) come `--output-dir`.
- Aggiungi `--no-diarize`.
- Dopo l'esecuzione, leggi il JSON dal file scritto nella directory temporanea (stesso pattern
  di ricerca del file già usato in `setup.py`: elenca i file `.json` nella directory di output),
  non da `result.stdout`.
- Le risposte vocali dell'active recall sono clip brevi (pochi secondi), quindi il rischio di
  deadlock da buffer pieno del Task 35 è meno probabile qui, ma usa comunque `--output-dir` per
  coerenza con l'interfaccia reale del binario e per eliminare la causa di fallimento sistematico
  osservata.
- Mantieni invariata la firma della funzione (`transcribe_voice_answer(audio_path, stt_engine)`)
  e il suo comportamento di ritorno/eccezione per il resto della pipeline di recall — cambia
  solo COME ottiene il JSON da macparakeet-cli.

## Test

- Test che verifica che il comando costruito includa sempre `--output-dir` e `--no-diarize`.
- Test che mocka l'esecuzione di macparakeet-cli scrivendo un JSON valido in una directory
  temporanea (simulando `--output-dir`) e verifica che `transcribe_voice_answer` lo legga
  correttamente e ritorni il testo trascritto atteso.
- Test che verifica che un fallimento reale (returncode != 0, o nessun file JSON scritto)
  produca ancora l'eccezione/messaggio di errore attuale, senza regressioni sul path di
  fallimento.
- Se esistono già test per `recall_stt.py` (verifica in `tests/`), adattali al nuovo
  meccanismo invece che sostituirli ciecamente.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Leggi anche la nota su come isolare l'ambiente di test da
`config/` reale prima di qualunque verifica funzionale diretta.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Se hai macparakeet-cli disponibile nell'ambiente Antigravity: registra un breve messaggio
   vocale di prova (o usa un file audio corto esistente) e verifica che
   `transcribe_voice_answer` produca una trascrizione valida invece di fallire sistematicamente.
   Se non è possibile, documentalo esplicitamente: sarà l'utente a verificarlo su Telegram con
   una vera risposta vocale durante l'active recall.
