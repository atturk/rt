# Task 67 — Migra la pulizia domande "stale" di `recall_session.py` da `rich.Live` a Textual

Fa parte della migrazione a Textual iniziata col Task 64 (pilota su `outline_review.py`). **Esegui
questo task solo dopo che i Task 64 e 65 sono stati completati e verificati** (può precedere o
seguire il Task 66, sono indipendenti). Nel progetto RT (/Users/attilioturco/Desktop/trt),
implementa direttamente, senza produrre un piano preliminare.

## Contesto

Leggi prima `.agents/64-textual-migration-pilot-outline-review.md` per il contesto generale della
migrazione (motivazione, perimetro, cosa NON migrare).

Il `rich.Live` a riga 605 di `rt/pipeline/recall_session.py` (dentro `with raw_mode() as is_raw,
Live(...) as live:`) gestisce la revisione delle domande di active recall diventate "stale"
(contenuto delle unità sorgente cambiato dopo la generazione della domanda): un loop a indice
mobile su `stale_questions`, con comandi `M`antieni, `E`limina, `S`alta, `B`indietro, `Q`uit — è
la più semplice delle 4 schermate da migrare (nessun subprocess audio, nessun editor esterno,
solo lettura/scrittura dello stato tramite `load_recall_bank`/`save_recall_bank`).

## Modifica

- Sostituisci `with raw_mode() as is_raw, Live(...) as live: while idx < total_count: ...` con una
  `App` Textual, preservando ESATTAMENTE i comandi `M`/`E`/`S`/`B`/`Q` (e le rispettive varianti
  testuali `mantieni`/`elimina`/`salta`/`skip`/`right`/`indietro`/`back`/`left`/`quit`/`esci` già
  accettate oggi — leggi l'intera funzione, non solo le righe già citate, per il comportamento
  esatto di `B`/indietro che usa `history_stack` per annullare l'ultima azione).
- Il contenuto del pannello (`_build_stale_panel`, righe 577-602) resta identico nella sostanza
  (stesse informazioni mostrate), cambia solo il widget/contenitore Textual che lo rende.
- Mantieni identica la logica di business (`record_decision`... in realtà qui è
  `load_recall_bank`/`save_recall_bank` direttamente sulle domande, non `record_decision` — verifica
  bene leggendo il file, non assumere sia identica a `issue_review.py`).

## Test

- Verifica quali test esistenti coprono questa funzione (cerca in `tests/test_recall_session.py` o
  simile, filtro su "stale"), riscrivili con `App.run_test()`/`pilot.press(...)`.
- Aggiungi/adatta test per: mantieni (aggiorna fingerprint), elimina (rimuove domanda+risposte),
  salta, indietro (annulla l'ultima azione tramite `history_stack`, incluso il caso limite "sei già
  al primo elemento"), uscita anticipata con Q.

Esegui `python3 -m pytest tests/ -q` e correggi finché l'intera suite passa.

## Vincoli

Verifica il bug di portabilità ricorrente sulle annotazioni `typing` per qualunque riga toccata
(vedi `.agents/00-README.md`). Non introdurre CSS/temi personalizzati in questo task.

## Verifica finale

1. `python3 -m pytest tests/ -q`.
2. Test manuale su una lezione con domande recall rese "stale" artificialmente (modifica il
   contenuto di un'unità dopo aver generato le domande): verifica mantieni/elimina/salta/indietro,
   nessuna duplicazione visiva.
