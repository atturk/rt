# Piano 1 · Verifiche: le issue di un'unità sparita non devono restare in giro

Bug trovato da Attilio sulla lezione 39 (log del 20/10): dopo una nuova rielaborazione l'unità 7.2
non esiste più, ma nel pannello Verifiche resta un gruppo "Unità non ritrovata" con due issue "Da
riconfermare" ("Qualità ASR · statistica" e "Fedeltà al parlato"). "Ho controllato" su una fa
comparire l'altra, all'infinito (nel log: `POST /issues/sci_000001/decision` e `sci_000003/decision`
alternati, sempre 200). Rifare la verifica non le toglie.

## Perché succede

1. **Rifare la verifica non le pulisce.** `run_review` (`rt/pipeline/review.py:864-871`) toglie le
   issue delle unità sparite solo se non hanno una decisione: "Le decisioni e le relative issue restano
   leggibili e da riconfermare". Quelle due avevano già una decisione dalla verifica precedente.
2. **Nessuna decisione le chiude.** `apply_decisions_to_draft` (`rt/pipeline/ledger.py:193-201`)
   mette in `missing_decisions` ogni decisione di un'unità che non c'è più, tranne i rifiuti con
   `original_context == ''`. `record_review_decision` (`rt/services/review_service.py:226-246`) quando
   riconferma non scrive mai `original_context = ''` (lo fa solo nel ramo non riconferma, e solo per i
   rifiuti). Per le issue ASR e di fedeltà la scelta è "accettato", quindi la nuova decisione finisce di
   nuovo fra le mancanti: l'issue resta `needs_reconfirmation` per sempre.
3. **Il pannello salta all'altra.** Dopo la decisione `onDecide` (`ReviewPanel.tsx:96-117`) passa alla
   prossima da decidere. Con due issue bloccate così, si alternano.

## Cosa deve succedere

1. **Le issue di un'unità che non c'è più si chiudono da sole.** Un'issue con `unit_id` che non è
   più fra le unità della bozza è **obsoleta**:
   - funzione nuova `drop_vanished_unit_issues(lesson_dir) -> int` in `rt/pipeline/review.py`: sposta
     le issue obsolete da `science_issues.json` a `science_issues_obsolete.json` (si aggiungono in
     coda, con `obsoleta_il`), sotto il lock della lezione, e scrive solo se qualcosa cambia;
   - il ledger non si tocca (resta append-only): le decisioni di quelle issue restano registrate;
   - si chiama: alla fine della rielaborazione (`rt/pipeline/rewrite.py`, dove si registra la fase,
     sia completa sia per unità), all'inizio di `run_review` al posto del filtro di `:864-871` (anche nel
     ramo che salta per le sole modifiche a mano) e accanto a `migrate_review_anchors` in
     `load_resolved_draft`, così le lezioni che hanno già il problema si sistemano alla prima apertura
     senza rifare niente;
   - un'issue obsoleta non conta in nessun posto: né da decidere, né in `orphan_issue_ids`, né negli
     avvisi del build, né nei conteggi della lista delle lezioni.
2. **Una decisione presa su un'unità che non c'è più vale.** In `record_review_decision`, se
   `_unit_content(...)` è `None`, la decisione si registra con `original_context = ''` per ogni scelta
   (anche in riconferma e anche per "accettato"). In `apply_decisions_to_draft` una decisione con
   `original_context == ''` su un'unità che non c'è non va più fra le mancanti, qualunque sia la scelta.
   È la rete di sicurezza se un'issue di un'unità sparita arriva comunque al pannello.
3. **Il pannello non gira in tondo.** In `ReviewPanel.onDecide`, se dopo la decisione la stessa issue
   torna `needs_reconfirmation` con la decisione appena presa, resta selezionata e la scheda mostra
   l'errore "La decisione non si applica: l'unità non c'è più." invece di passare alla prossima.

## Test

- Pytest (`tests/test_review_vanished_units.py`):
  - una lezione con issue decise (ASR statistica accettata, fedeltà accettata, una correzione
    accettata) su un'unità che la nuova bozza non ha: dopo `drop_vanished_unit_issues` non sono più
    in `GET /lessons/{id}/issues?status=all`, sono in `science_issues_obsolete.json`, il ledger è
    uguale a prima, `review_complete` è vero se non resta altro;
  - `run_review` con `force` le toglie anche se avevano una decisione;
  - la prima `load_resolved_draft` di una lezione già nel problema le sposta, la seconda non scrive;
  - una decisione registrata con l'unità sparita ha `original_context == ''` e non è fra le mancanti,
    anche se è "accettato";
  - le issue delle unità che ci sono ancora non cambiano.
- Vitest (`ReviewPanel.test.tsx`): se la stessa issue torna da riconfermare dopo la decisione, resta
  selezionata con l'errore e non si passa all'altra.
- I test di riconferma esistenti (decisione il cui tratto si sposta nella stessa unità) restano verdi.

## Changelog

- Verifiche: dopo una nuova rielaborazione le issue di un'unità che non c'è più si chiudono da sole,
  invece di restare "Da riconfermare" e rimbalzare l'una sull'altra.
