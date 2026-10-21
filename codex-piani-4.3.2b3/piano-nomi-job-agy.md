# Piano 4 · Nomi dei job leggibili

## Com'è oggi

- I nomi dei job vengono da `JOB_TYPE_LABELS` (`frontend/src/lib/jobs.ts:7`); se un tipo manca si vede
  il nome grezzo (`jobTypeLabel`, `jobs.ts:64`).
- `JobsPanel.tsx:23-31` ha un secondo elenco suo, più corto (`JOB_TYPES`, `jobLabel`).
- Mancano questi tipi registrati nel backend (`register_handler` in `rt/services/job_handlers.py` e
  `rt/services/api_jobs.py:528-541`).

## Cosa deve succedere

1. In `JOB_TYPE_LABELS` (nomi approvati da Attilio):
   - `review_unit` → Verifica di un'unità
   - `ingest_sources` → Aggiunta di fonti
   - `ingest_notes` → Importazione degli appunti
   - `update_lesson` → Aggiornamento della lezione
   - `enrichment_analyze` → Idee per la lezione
   - `enrichment_generate` → Generazione di un'idea
   - `classifier` → Classificatore
   - `compact_audio` → Compressione dell'audio
   - `study_note` → Nota di studio
   - `recall_comment` → Commento alla risposta
   - `restore_version` → Ripristino di una versione
   - `recall_regenerate` → Nuova domanda di recall
2. `JobsPanel` prende i nomi da `JOB_TYPE_LABELS` e perde il suo `JOB_TYPES`. Il suo `jobLabel` resta
   com'è nel resto: per `run_phase` il nome della fase, e l'unità accanto quando c'è.
3. Le fasi mostrate sopra la barra di avanzamento (`progressLabel`, `jobs.ts:183`) non devono mai
   mostrare un nome grezzo: controlla tutti i valori di `phase` passati a `ctx.progress(...)` e a
   `phase_scope(...)` nel backend e dai a ognuno un'etichetta in `PHASE_LABELS` o nel ramo speciale
   di `progressLabel` (come già `setup` e `archive`).
4. Test che impedisce di dimenticarne uno: `tests/test_job_labels.py` importa `rt.services.api_jobs`
   (che registra tutti i tipi), legge `_HANDLERS` da `rt/services/worker.py` e controlla che ogni tipo
   compaia come chiave in `frontend/src/lib/jobs.ts`. Stessa cosa per i nomi delle fasi di
   `ctx.progress` trovati nel codice, se si possono raccogliere in modo affidabile; altrimenti un
   elenco esplicito nel test.

## Test

- `tests/test_job_labels.py` come sopra.
- Vitest: `jobTypeLabel` per tre dei tipi nuovi; `JobsPanel` mostra "Verifica di un'unità 3.2" per
  un `review_unit` sull'unità 3.2.

## Changelog

- I job hanno tutti un nome leggibile (prima alcuni comparivano come `enrichment_generate` o
  `review_unit`).
