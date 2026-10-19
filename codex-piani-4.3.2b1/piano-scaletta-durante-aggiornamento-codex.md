# Piano per Codex · 4.3.2b1 · "Scaletta da approvare" resta a schermo durante l'aggiornamento della lezione

Base: `claude/rt-4.3.2-beta`. File: `rt/pipeline/source_update.py`, `rt/core/update_history.py`, test in `tests/test_source_update.py` e `tests/test_update_history.py`.

## Il bug (segnalato da Attilio)
Mentre una lezione si aggiorna con nuove fonti (Estendi, e anche Ricostruisci), al posto del testo compare la scheda gialla "Scaletta da approvare" con "Approva" e "Rigenera con queste modifiche" grigi (disattivati), senza conto alla rovescia. Resta lì finché l'aggiornamento non finisce, anche se la scaletta era già stata approvata.

## Causa
- L'approvazione è legata all'hash di `outline.json` (`rt/services/outline_service.py`, `is_outline_approved`).
- `_run_source_update` riscrive `outline.json`: in Estendi con `extend_outline` (`rt/pipeline/outline_extension.py`), in Ricostruisci con `run_outline(force=True)`. L'hash cambia, quindi la scaletta risulta non approvata. Nessun timer viene avviato, per questo il pulsante dice "Approva" senza numero.
- Durante la riscrittura delle unità la fase `rewrite` non è VALID. In `frontend/src/routes/lessons.tsx` `pendingOutline = !approved && phases.rewrite !== 'VALID'` è quindi vero e la pagina mostra `LessonOutline` invece di `DocumentCard`. C'è un job attivo, quindi la scheda è disattivata (`busy`).
- L'aggiornamento non aspetta mai l'approvazione: va dritto alla riscrittura. La scheda è quindi solo rumore, e nasconde il documento per tutta la durata.
- A fine aggiornamento `rewrite` torna VALID e la scheda sparisce. Se l'aggiornamento fallisce o viene annullato, `abort_update` ripristina il vecchio `outline.json` ma non `outline_approval.json` (non è in `FILES` di `update_history.py`). Oggi non si vede perché anche `rewrite` torna VALID, ma è fragile.

## Cosa fare
1. In `_run_source_update`, subito dopo il passo della scaletta (sia il ramo `extend_outline` sia il ramo `run_outline`) e prima di `run_rewrite`, registrare l'approvazione della nuova scaletta:
   `outline_service.approve_outline(lesson_dir, actor="source_update", channel="server")`.
   Motivo da scrivere nel commento: l'aggiornamento non chiede conferma della scaletta, va dritto alla riscrittura. Senza approvazione la pagina mostrerebbe la scheda di approvazione disattivata al posto del documento.
   `approve_outline` chiama anche `resume_waiting_jobs(lesson_dir, "outline_approval")`: verificare che durante l'aggiornamento non ci sia un job in attesa che riparta per sbaglio. Se ci può essere, aggiungere un parametro `resume: bool = True` ad `approve_outline` e passarlo a False qui.
2. Aggiungere `"outline_approval.json"` a `FILES` in `rt/core/update_history.py`. Così una fotografia (begin_update/abort_update, Annulla aggiornamento, ripristino versione) riporta insieme scaletta e approvazione. `_capture` usa già `lesson_path`, che lo risolve in `_state/`. Controllare che `_restore_snapshot_files` gestisca allo stesso modo un file che nella fotografia non c'era (va rimosso o lasciato com'è, come per gli altri file di stato).
3. Nessuna modifica al frontend.

## Test (pytest)
- `test_source_update.py`: aggiornamento in modalità `extend` (mock) su una lezione con scaletta approvata. Durante `run_rewrite` (patch che controlla lo stato quando viene chiamata) `is_outline_approved(lesson_dir)` è True, e lo è anche dopo. Stesso controllo in modalità `rebuild`.
- Aggiornamento che fallisce dentro `run_rewrite`: dopo il ripristino `outline.json` è quello vecchio e `is_outline_approved` è True (il vecchio record di approvazione è tornato).
- `test_update_history.py`: una fotografia contiene `outline_approval.json` quando esiste.
- Facoltativo, se semplice: un'approvazione esistente non viene toccata se `approve_outline` fallisce (eccezione propagata, aggiornamento annullato come oggi).

Comandi: `python -m pytest tests/test_source_update.py tests/test_update_history.py tests/test_outline_service.py -q`, poi la suite completa.

## Changelog
Sezione 4.3.2b1 di `CHANGELOG.md`: "Durante l'aggiornamento di una lezione con nuove fonti non compare più la scheda «Scaletta da approvare»: resta visibile il testo della lezione."
