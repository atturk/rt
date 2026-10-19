# Piano per Codex · 4.3.2b1 · Tre ritocchi rimasti dalla 4.3.1

Base: `claude/rt-4.3.2-beta` (creato da main alla 4.3.1). Tre correzioni piccole e indipendenti: un commit ciascuna, nella stessa PR va bene.

## 1. «Riesegui tutto da capo» salta l'arricchimento automatico
**Dove:** `rt/pipeline/source_update.py`, `_run_source_update`, ramo `if reingest or with_review:`.
**Causa:** «da capo» (Dettagli › Fasi, `mode="rebuild", reingest=True`) rifà trascrizione, scaletta, rielaborazione, revisione facoltativa e build, ma non chiama mai `automatic_enrichment` (`rt/services/pipeline_service.py`). «Rifai tutte le fasi» (`run_pipeline`) invece la chiama (riga `result.phase_results["enrichment"] = automatic_enrichment(...)`).
**Cosa fare:** solo quando `reingest` è vero, dopo `run_build` (non quando il documento resta un'anteprima per correzioni in sospeso, come fa la pipeline normale: verificare in `run_pipeline` quando la salta e fare lo stesso), chiamare `automatic_enrichment(lesson_dir, mock, ctx)` e salvare il risultato in `result["enrichment"]`. `automatic_enrichment` usa `ctx.emit`: se `ctx` può essere None qui, passare un `RunContext` minimo o saltare l'arricchimento con un commento. Un errore dell'arricchimento non deve far fallire l'aggiornamento (la funzione già lo cattura). Estendi semplice e Ricostruisci senza `reingest` restano come oggi.
**Test:** `tests/test_source_update.py`: rebuild con reingest in mock, con arricchimento in modalità `pipeline` → `automatic_enrichment` chiamata una volta; con modalità `manual` → saltata; extend → mai chiamata.

## 2. Le icone delle unità nell'editor sfarfallano dopo un salvataggio
**Dove:** `frontend/src/components/lesson/lessonShortcuts.ts` e l'effetto in `LessonEditor.tsx` che invia `setUnitShortcuts`.
**Causa:** dopo ogni salvataggio `doc.sections` arriva come array nuovo, quindi l'effetto invia un nuovo oggetto `options`. `Shortcuts.eq` confronta `other.options === this.options` (per identità): tutte le icone Studio/Domande vengono distrutte e ricreate, e si vede uno sfarfallio.
**Cosa fare:**
- `eq`: confrontare `unit`, `options.lessonId` e `options.navigate` invece dell'oggetto intero.
- In `LessonEditor.tsx` calcolare la lista delle unità con `useMemo` su una chiave stabile (per esempio `units.join('|')`) e inviare l'effetto solo quando quella chiave, `lessonId` o `openStudy` cambiano.
**Test (vitest):** in un test dell'editor, dopo un nuovo `doc` con le stesse sezioni il nodo DOM `.rt-editor-shortcuts` della prima unità è lo stesso oggetto di prima (`toBe`). Con una sezione in più compare la nuova icona.

## 3. Un import in corso perde il collegamento all'ora dopo una modifica «per un intervallo»
**Dove:** `rt/services/materials_lesson_service.py` (`link_imported_lesson`, `finish_import`), `rt/api/routers/jobs.py` (accodamento), `rt/services/api_jobs.py` (`ingest_sources_job`).
**Causa:** l'import salva nel job la key dell'ora (`calendar_entry_id`, per esempio `tpl_12`). Collega la lezione all'inizio e la ricollega a fine import (`finish_import`). Se nel frattempo la settimana tipo viene modificata per un intervallo, la riga del modello viene divisa e cambia id, quindi la key non esiste più. `link_imported_lesson` solleva `ValueError('Ora del calendario non trovata')` e l'import fallisce alla fine, oppure il collegamento si perde.
**Cosa fare:**
- All'accodamento salvare nel payload, oltre a key e data, anche `calendar_materia` e `calendar_start` dell'ora, presi dall'evento che `require_linkable_event` già restituisce.
- In `link_imported_lesson`: se la key non si trova, cercare nello stesso giorno l'unica ora con la stessa materia e la stessa ora d'inizio, e collegare quella.
- Se la lezione risulta già collegata a un'ora di quel giorno, non fare nulla.
- Se non si trova niente, non far fallire l'import: scrivere un avviso nel log (o `ctx.emit(Notice(level="warning", ...))` dove c'è un contesto) con il testo «Lezione importata, ma l'ora del calendario è cambiata: collegala dal calendario.».
- Lasciare invariato l'errore 422 all'accodamento, quando l'ora non esiste già in partenza.
**Test (pytest):** import accodato con `tpl_X`. Prima di `finish_import` l'ora viene spostata su un nuovo modello per un intervallo (usare il servizio calendario). Risultato atteso: la lezione è collegata alla nuova ora dello stesso giorno. Caso in cui l'ora sparisce del tutto: l'import finisce comunque, senza collegamento, con l'avviso.

Comandi: `python -m pytest tests/test_source_update.py tests/test_calendar*.py tests/test_materials_lesson*.py -q`, `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`, poi la suite completa.

## Changelog
Sezione 4.3.2b1, Correzioni:
- «Riesegui tutto da capo» rifà anche l'arricchimento automatico, quando è attivo.
- Le icone di Studio e Domande accanto alle unità non sfarfallano più dopo un salvataggio.
- Un import in corso resta collegato alla sua ora anche se nel frattempo modifichi la settimana tipo per un intervallo.
