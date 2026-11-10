# Piano: elenco lezioni subito pronto all'avvio (vetrina persistente)

Base: `main` dopo la 4.3.8.1 + questo branch. Solo codice e test (pytest sui test toccati). Niente Playwright.

Perché: al primo `GET /api/v1/lessons` dopo l'avvio la cache in memoria `_summary_cache`
(`rt/services/lesson_service.py`) è vuota e RT ricalcola il riepilogo di ogni lezione: sull'Air
62 lezioni = 5–10 s; dal secondo caricamento 0,6 ms a lezione. Redis è stato scartato: la vetrina va nel
DB SQLite che RT ha già. Già fatto da Claude su questo branch: il salvataggio dei metadati invalida solo
la propria lezione (`forget_summary`) e api.log scrive «📋 Elenco lezioni: N lezioni, M ricalcolate, X ms».

## 1. Tabella `lesson_summary_cache`
- Modello in `rt/db/models.py` + migrazione come le altre: `lesson_id` (PK, FK su Lesson con cancellazione a cascata),
  `fingerprint` (str), `schema` (int), `summary` (JSON testo), `updated_at`.
- Costante `SUMMARY_SCHEMA = 1` in `lesson_service.py`: va incrementata quando cambiano i campi del riepilogo
  (`_lesson_summary`); le righe con schema diverso si ignorano e si riscrivono.

## 2. Lettura e scrittura in `_cached_summaries`
- Ordine: memoria → tabella (stessa impronta e stesso schema) → ricalcolo.
- Una sola query per leggere tutte le righe delle lezioni dell'elenco (non una per lezione); i ricalcoli riusciti
  (`error is None`) si scrivono in un'unica transazione alla fine, anche in memoria come oggi.
- Le righe delle lezioni che non ci sono più si cancellano (come oggi `stale` in memoria).
- `clear_summary_cache()` e `forget_summary()` cancellano anche le righe corrispondenti.
- La riga di api.log distingue: «N lezioni, M dalla vetrina, K ricalcolate, X ms».

## 3. Riempimento all'avvio
- Nel `lifespan` di `rt/api/app.py` (accanto a `start_backfill`) un thread daemon chiama `list_lessons()` una volta,
  con try/except e log dell'errore: le lezioni cambiate mentre RT era chiuso sono pronte prima che l'utente apra la pagina.
- Il lock `_summary_lock` evita il doppio calcolo se la richiesta del frontend arriva durante il riempimento:
  aggiungi un lock per lezione (o un lock di ricalcolo globale) così la stessa lezione non si calcola due volte.

## 4. Meno lavoro nel ricalcolo
- Dentro `fs.read_snapshot()` memorizza `load_segments_json(path)` e `check_phase_status(lesson_dir, phase)` per la
  durata dello snapshot (chiave: percorso + mtime/sha del file dal backend storage). Oggi per lezione: segments.json
  caricato fino a 33 volte, `check_phase_status` 36 volte.
- `compute_file_sha256` per le lezioni con storage `db`: usa `LessonFile.sha256` già nel DB invece di rileggere e
  ri-hashare il contenuto.
- Restituisci copie (o oggetti immutabili) dalla memoizzazione: nessun chiamante deve poter modificare il valore condiviso.

## Test
- Riavvio simulato (memoria svuotata, tabella piena) → nessun `_lesson_summary` chiamato, risultato identico.
- Impronta cambiata (file, decisione, chiamata LLM, config) → ricalcolo e riga aggiornata.
- Schema diverso → ricalcolo. Lezione cancellata → riga cancellata.
- Memoizzazione: stessi risultati di `list_lessons()` con e senza; `load_segments_json` chiamato al massimo una volta per
  lezione in un `list_lessons()` a freddo (spy come in `tests/test_lesson_summary_cache.py`).
- Tutti i test esistenti di `tests/test_lesson_summary_cache.py`, `tests/test_lesson_metadata.py`, `tests/test_idempotency*.py`.
