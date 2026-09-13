# Task 65 — Migra `issue_review.py` da `rich.Live` a Textual

Fa parte della migrazione a Textual iniziata col Task 64 (pilota su `outline_review.py`). Il
Task 64 è stato completato, verificato E confermato dall'utente con test manuale reale (nessuna
duplicazione visiva, Ctrl+Q interrompe correttamente) — procedi direttamente, nessuna pausa di
conferma richiesta per questo task. Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa
direttamente, senza produrre un piano preliminare.

## Contesto

Leggi prima `.agents/64-textual-migration-pilot-outline-review.md` per il contesto generale della
migrazione (motivazione, perimetro, cosa NON migrare) — non ripetuto qui per intero.

`issue_review.py` è la schermata di revisione interattiva ASR/scienza (`rich.Live` a riga 451,
dentro `with raw_mode() as is_raw, Live(...) as live:`, righe 451-559+ per il ramo ASR — verifica
se esiste un ramo analogo per "scienza" più sotto nello stesso loop, stessa struttura). È la
schermata più complessa delle 4 da migrare, per due motivi:

1. **Riproduzione audio in background**: i tasti P/play controllano un `subprocess.Popen` (
   `current_audio_proc`) che riproduce un ritaglio audio, con stato di pausa/ripresa (`audio_paused`,
   `audio_elapsed`, `audio_resumed_at`) mentre il carosello resta visibile e reattivo ad altri tasti.
2. **Editor esterno interattivo**: il tasto M/modifica fa `live.stop()`, lancia
   `edit_text_in_editor(...)` (apre `$EDITOR` a schermo intero, bloccante, l'utente scrive e salva),
   poi `live.start()` per riprendere (righe 528-531) — stesso pattern sospetto di duplicazione già
   visto nel Task 64.

## Modifica

- Sostituisci `with raw_mode() as is_raw, Live(...) as live:` con una `App` Textual, mantenendo
  ESATTAMENTE i comandi esistenti: `A`ccetta, `R`ifiuta, `M`odifica, `P`lay/pausa audio (e
  qualunque altro tasto già gestito più sotto nel loop — leggi l'intera funzione, non solo le
  righe già citate, per non perderne nessuno).
- Per il tasto M (editor esterno): sostituisci `live.stop()` / `edit_text_in_editor(...)` /
  `live.start()` con `App.suspend()` attorno alla sola chiamata a `edit_text_in_editor(...)` —
  è esattamente il caso d'uso per cui `App.suspend()` esiste (restituire il terminale a un
  processo esterno interattivo a schermo intero, poi riprendere il controllo Textual).
- Per la riproduzione audio in background: il subprocess va avviato/fermato/interrogato senza
  bloccare il loop di eventi Textual. Usa un worker Textual (`@work` / `run_worker`, o un
  controllo periodico via `set_interval`) per monitorare `current_audio_proc.poll()` e aggiornare
  lo stato mostrato (es. play/pausa) senza bloccare la ricezione di altri tasti — verifica
  l'API worker esatta della versione di Textual scelta nel Task 64.
- Mantieni identica la logica di business (chiamate a `record_decision`, `load_ledger`,
  `extract_context_sentence`, ecc.) — cambia SOLO il motore di rendering/input attorno a questa
  logica.
- Se esiste un secondo ramo nello stesso loop per `issue_type == "science"` (o simile) con una
  propria funzione `_build_*_panel` e propri comandi, migralo con lo stesso approccio, verificando
  che i comandi specifici di quel ramo restino tutti presenti.

## Test

- Verifica quali test esistenti coprono `issue_review.py` (`grep -rl issue_review tests/`),
  probabilmente basati su mock di `read_single_key`/`Live` — riscrivili usando `App.run_test()`
  e `pilot.press(...)` (stesso approccio del Task 64).
- Aggiungi/adatta test per: accetta/rifiuta/modifica un'issue con successo; play/pausa audio non
  blocca la ricezione del tasto successivo (simula una sequenza di tasti che include P poi un
  altro comando, verifica che entrambi vengano processati); il ciclo M→editor esterno→ritorno al
  carosello non duplica l'output e riprende con lo stato corretto (stesso tipo di test del Task 64
  per l'outline).

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Non toccare `rt/core/keyboard.py` (rimosso solo nel Task 68). Non
introdurre CSS/temi personalizzati (stile di default Textual, come nel Task 64).

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale con `rt review "<cartella_lezione>"` su una lezione con issue ASR pendenti:
   verifica accetta/rifiuta/modifica, riproduzione audio con pausa/ripresa, apertura editor
   esterno e ritorno senza duplicazione visiva.
