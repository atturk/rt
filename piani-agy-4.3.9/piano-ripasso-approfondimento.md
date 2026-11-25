# Piano: ripasso, domanda di approfondimento, caricamento della prossima domanda

Branch: `agy/4.3.9-ripasso` (parte da `claude/rt-4.3.9-beta`). Solo codice e test unitari, niente verifiche
nell'app. Prima di tutto: `git pull` del branch. Un commit per punto, push sul branch.

File principali: `frontend/src/components/recall/LightweightSession.tsx`, `rt/llm/prompts.py`,
`rt/pipeline/recall.py`, `rt/services/recall_service.py`, `rt/core/models.py`, `rt/api/schemas.py`.

## 1. Dopo la risposta di approfondimento si vede la nuova valutazione
Oggi, valutata la seconda risposta, la UI mostra ancora i punteggi e il commento della PRIMA valutazione, più
un riquadro con domanda e risposta dello studente: il commento finale (`followup_evaluation`) e i punteggi
`followup_correttezza/completezza/attinenza` non si vedono mai.
- In `LightweightSession.tsx`, nei due punti che costruiscono `evaluatedResult` (riaggancio da
  `saved_evaluation` e `evaluationFinished`) leggi anche `followup_correttezza/completezza/attinenza`
  (aggiungili al tipo dello state).
- Se c'è `followupEvaluation`: i badge mostrano i punteggi `followup_*` (fallback sui primi se null), l'esito
  è quello aggiornato (`outcome` della risposta, già aggiornato dal backend), e il commento principale è
  `followupEvaluation` (stesso `cleanComment`).
- Il riquadro di riepilogo resta ma più discreto e sotto il commento: «Domanda di approfondimento» + «La tua
  risposta», poi in piccolo «Prima valutazione: Correttezza X% · Completezza Y% · Attinenza Z%» e il primo
  commento. Niente altro.
- Controlla anche `rt/services/recall_service.py` `question_resume_view`: deve restituire i tre `followup_*`
  (già nella lista di riga ~315, verifica) e `schema.d.ts` li ha già.
- Vitest: dopo una valutazione con `followup_evaluation` e `followup_completezza: 90` il badge mostra
  «Completezza 90%» e il testo del commento finale; il commento iniziale compare solo nel riepilogo.

## 2. Domanda di approfondimento da vero professore (non rivela la risposta)
Problema reale: commento «Manca però il meccanismo centrale legato al calcio: la riperfusione lo reintroduce in
cellule con pompe compromesse…» + domanda «Come contribuiscono il nuovo apporto di calcio e il deficit
energetico…?». Il commento dà la soluzione e la domanda la suggerisce.
- `rt/llm/prompts.py`, nei system prompt MIRATA e VASTA:
  - sezione COMMENTO: «Se proponi una domanda di approfondimento, il commento dice solo cosa è giusto e che
    manca un aspetto importante, SENZA nominarlo né descriverlo: niente termini chiave, meccanismi o
    esempi della parte mancante.»
  - sezione DOMANDA DI APPROFONDIMENTO: «Comportati come un professore all'orale che vede lo studente nella
    direzione giusta e vuole fargli trovare da solo ciò che ha dimenticato. La domanda non deve contenere la
    risposta né le sue parole chiave (es. se manca il ruolo del calcio, non nominare il calcio): parti da ciò
    che lo studente ha detto o da una conseguenza osservabile e chiedigli di proseguire il ragionamento.
    Una sola domanda, breve.» Aggiungi un esempio corto «sbagliato / giusto» generico (non di medicina
    del caso sopra, usa un altro argomento).
  - Nuovo campo facoltativo nel risultato (`RecallEvalMirataResult`, quindi anche Vasta):
    `parte_mancante: Optional[str]` = la spiegazione di ciò che manca (2-3 frasi), da compilare SOLO quando
    c'è `domanda_followup`. Non viene mostrata subito.
- Salvataggio: `RecallEvaluation` (models.py) e `RecallAnswer` hanno `parte_mancante: Optional[str] = None`;
  `save_recall_answer` la salva sulla risposta (prima valutazione). Esponila in `schemas.py` (record risposta
  e saved_evaluation) ma restituiscila **solo quando `domanda_followup` è null** (cioè dopo «Salta» o dopo la
  valutazione dell'approfondimento): finché la domanda è aperta l'API manda `parte_mancante: null`. Rigenera `docs/openapi.json` + `schema.d.ts` (`python scripts/export_openapi.py`,
  `npm run gen:api` in `frontend/`).
- Valutazione dell'approfondimento (`RECALL_EVAL_FOLLOWUP_SYSTEM_PROMPT` e builder): passa anche
  `parte_mancante` al modello e chiedi che il commento finale, se lo studente non l'ha trovata del tutto,
  spieghi chiaramente la parte mancante (ora sì, la soluzione va data).
- «Salta» e «Non lo so» sull'approfondimento: lo studente deve comunque vedere la soluzione. Con `skip`, la UI
  mostra sotto il commento la `parte_mancante` salvata con l'etichetta «Cosa mancava». («Non lo so» passa già
  dalla valutazione di approfondimento: lì basta il prompt sopra.)
- Mock (`force_mock`) aggiornati con un `parte_mancante` finto.
- Test pytest: i prompt contengono le nuove regole; `save_recall_answer` salva `parte_mancante`;
  il prompt di followup la include. Vitest: dopo «Salta» compare «Cosa mancava».

## 3. Tipi di domanda centrati
La riga dei tipi (Mista, Quiz, Mirata, Vasta, Caso clinico…) in cima alla sessione: centrala orizzontalmente
(`justify-center`, anche quando va a capo). Solo questo.

## 4. «Prossima»: niente domanda vecchia, subito il caricamento
Oggi `askNext` azzera risposta e valutazione ma lascia `currentQuestion` finché arriva la nuova: per circa un
secondo si vede la domanda precedente.
- Nuovo state `loadingNext` (true all'inizio di `askNext`, false all'arrivo o in errore, rispettando
  `requestSeq`).
- Mentre `loadingNext`: al posto di intestazione (tipo · unità · domanda N), testo della domanda e opzioni
  del quiz mostra subito un box di caricamento con le righe che luccicano già usate per le unità in
  scrittura (classe `rt-unit-pending` con tre `<div>`; per un quiz aggiungi sotto 3-4 righe con l'altezza
  delle opzioni usando `rt-skeleton rounded-md`). Stessa larghezza e margini del blocco domanda, così niente
  salti di layout. `aria-busy="true"` e `aria-label="Caricamento della prossima domanda"`.
- Pulsanti Termina/Prossima disabilitati durante il caricamento.
- Vitest: con la risposta di `next` in attesa, il testo della domanda precedente non è nel DOM e c'è il box di
  caricamento; all'arrivo compare la nuova domanda.

## 5. Tempi tra «Prossima» e la domanda
- Backend `POST /lessons/{id}/recall/next` (`rt/api/routers/recall.py` `next_question` →
  `next_question_for`, `pending_count`, `question_resume_view`, `_refill_later`): oggi carica e analizza il
  banco delle domande più volte per richiesta. Fai una sola lettura del banco per richiesta (passa il bank già
  caricato alle funzioni, con parametro opzionale per non rompere gli altri chiamanti) e controlla che
  `_refill_later` non faccia lavoro pesante nel thread della richiesta (deve solo accodare).
  Stessa cosa per `/recall/subject/next` se ripete il pattern.
- Frontend, causa principale dell'attesa: `frontend/src/api/recall.ts` (riga ~64) `useRecallMutation` ha un
  `onSettled` che RESTITUISCE `invalidateQueries(...)`, quindi `mutateAsync` aspetta il refetch di cronologia,
  conteggi ecc. prima di risolversi. Cambialo in `void queryClient.invalidateQueries(...)` (non attendere), sia per
  next sia per le risposte. Controlla che i test che si basavano sull'attesa passino ancora (aggiorna con
  `waitFor` dove serve). `evaluationFinished` usa già `history.refetch()` esplicito, quello resta.
- In caso di errore di `next` durante il caricamento: togli il box di caricamento e mostra l'errore con
  «Riprova», mai uno spazio vuoto.
- Frontend: subito dopo una valutazione (o una risposta al quiz) fai partire in background il prefetch dei
  dati statici che servono alla prossima schermata se ce ne sono (non chiedere la prossima domanda in
  anticipo: segnerebbe la domanda come posta).
- Test pytest: `next_question` con un banco di 200 domande chiama `load_recall_bank` una sola volta
  (monkeypatch con contatore).

## Chiusura
- `CHANGELOG.md`: crea `## 4.3.9b8 — da pubblicare` sopra la b7 (stesso stile). Correzioni: «Approfondimento
  nel ripasso: dopo la seconda risposta si vedono il commento e i punteggi aggiornati», «La domanda di
  approfondimento non suggerisce più la risposta e il commento non la anticipa; se salti, vedi cosa
  mancava», «Prossima domanda: subito un'animazione di caricamento invece della domanda precedente, e
  risposta più rapida». Novità/estetica: «Tipi di domanda centrati». Non cambiare `VERSION`.
- Esegui: pytest sui test toccati (`tests/test_recall*.py` e quelli nuovi), `npx vitest run`,
  `npx oxlint --deny-warnings`, `npm run build`, `npm run -s check:bundle` in `frontend/` (il bundle è vicino
  al limite: niente nuove dipendenze).
- Push su `agy/4.3.9-ripasso`.
