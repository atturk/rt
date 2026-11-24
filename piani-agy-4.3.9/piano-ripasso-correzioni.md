# Piano C: correzioni del ripasso dopo i test sulla b8

Branch: `agy/4.3.9-ripasso2` (parte da `claude/rt-4.3.9-beta`). Solo codice e test unitari, niente verifiche
nell'app. Prima di tutto: `git pull` del branch. Un commit per punto, push sul branch.
Non toccare `rt/services/api_jobs.py`, `rt/worker.py`, `rt/telegram/` (li sta cambiando un altro lavoro).

## 1. «Non lo so» sull'approfondimento non azzera la prima valutazione
Oggi «Non lo so» sulla domanda di approfondimento passa dal modello, che dà 0/0 e «sbagliata».
- `rt/pipeline/recall.py` `evaluate_recall_answer` con `is_followup` e `is_dont_know`: NON chiamare il modello.
  Restituisci i punteggi e l'esito della prima valutazione (`c1/comp1/att1` e l'`outcome` della risposta), con
  commento = «Nessun problema, ecco cosa mancava:» + `parte_mancante` (se manca: «Confermata la valutazione
  precedente.»). Come fa già il ramo mock: allinealo e usalo anche per il caso reale.
- `record_recall_answer` con `is_followup`: in questo caso l'esito della risposta resta quello della prima
  valutazione (non scende a «sbagliata»).
- Test pytest: prima valutazione 70/60 parziale con `parte_mancante`, poi «Non lo so» sull'approfondimento →
  nessuna chiamata al client (monkeypatch che fallisce se chiamato), punteggi `followup_*` = 70/60, esito
  parziale, commento contiene la parte mancante.

## 2. La valutazione non aspetta in coda dietro il rifornimento delle domande
Oggi `recall_refill` (generazione in background, lunga) prende `active_lesson` e una valutazione
(`recall_evaluate` o simili) della stessa lezione aspetta ~15 s in coda (`rt/services/jobs.py` `claim`, riga ~501).
- In `rt/services/jobs.py` definisci `SHARED_LESSON_JOB_TYPES` = i job del ripasso che scrivono SOLO il banco
  delle domande sotto il suo lock (`recall_refill`, la valutazione delle risposte, `recall_comment` se scrive solo
  il banco: verifica ciascuno leggendo il handler e mettilo solo se è vero). Questi job non impostano
  `active_lesson` e non vengono saltati per `busy`; tutti gli altri restano come oggi.
- Attenzione al vincolo UNIQUE e a `requeue_expired`/rilascio (righe ~326, 374, 548, 592): devono funzionare con
  `active_lesson` null.
- Controlla che la generazione del refill legga il banco, chiami il modello FUORI dal lock e poi riscriva sotto
  lock rileggendo il banco (merge delle nuove domande, mai sovrascrivere risposte arrivate nel frattempo). Se oggi
  non è così, correggilo in `rt/pipeline/recall.py` (non in api_jobs).
- Test: con un `recall_refill` RUNNING sulla lezione, `claim` prende subito la valutazione della stessa lezione;
  una rielaborazione della stessa lezione invece resta bloccata. Test di merge: risposta salvata durante il
  refill → c'è ancora dopo.

## 3. Domanda di approfondimento su materie tecniche
Nella lezione di ingegneria la domanda suggeriva ancora la risposta (nominava la grandezza mancante, la distanza).
- `rt/llm/prompts.py`, sezione DOMANDA DI APPROFONDIMENTO di MIRATA e VASTA: aggiungi «Nelle materie tecniche e
  scientifiche non nominare la grandezza, la variabile, la formula o la legge che manca: chiedi cosa succede al
  risultato se cambia una condizione, o da cosa dipende ciò che lo studente ha scritto.» con un secondo esempio
  sbagliato/giusto tecnico (es. sbagliato «E la distanza dal centro come influisce sul campo?», giusto «Il valore
  che hai scritto vale in ogni punto? Da cosa dipende?»).
- Test pytest: il prompt contiene la nuova regola.

## 4. Tipi personalizzati (Esercizio, Caso clinico…): punteggi nei badge e approfondimento
`rt/pipeline/recall_special.py` `evaluate` (righe ~483-506) mette «Correttezza: X%\nCompletezza: Y%» dentro il
testo del commento invece che nei campi.
- Restituisci `RecallEvaluation(commento, outcome, correttezza=..., completezza=..., attinenza=...)` come la
  Mirata (attinenza: se il modello non la dà, None e la UI non mostra il badge). Anche i mock.
- Per le risposte già salvate col vecchio formato: in lettura (`question_resume_view` / record risposta) se i campi
  sono null e il commento inizia con quelle righe, estrai i numeri e togli le righe dal testo.
- Approfondimento anche per i tipi personalizzati: `RECALL_EVAL_RAGIONAMENTO_SYSTEM_PROMPT` e
  `RECALL_EVAL_TEXT_SYSTEM_PROMPT` ricevono le stesse regole COMMENTO / DOMANDA DI APPROFONDIMENTO /
  `parte_mancante` della Mirata (riusa le stesse costanti di testo, non duplicarle) e il risultato passa
  `domanda_followup` e `parte_mancante` a `save_recall_answer`. La valutazione dell'approfondimento usa la
  soluzione attesa del tipo come riferimento.
- Frontend: controlla che `LightweightSession.tsx` mostri badge e approfondimento anche per questi tipi
  (stesso percorso della Mirata). Vitest: risposta a un tipo personalizzato con correttezza 70 → badge
  «Correttezza 70%» e nessuna riga «Correttezza:» nel testo.

## 5. Testo del modello con caratteri di controllo
Nei commenti delle valutazioni arrivano a volte caratteri di controllo e formule rotte: tipico JSON con `\f`, `\t`,
`\b` non raddoppiati, così `\frac` diventa «form feed + rac», `\text` «tab + ext», `\beta` «backspace + eta».
- `rt/core/encoding.py`: nuova funzione `repair_llm_text(text)`: dentro `$...$`/`$$...$$` ripristina `\x0c`→`\\f`,
  `\x08`→`\\b`, `\t`→`\\t`, `\r`→`\\r` quando seguiti da lettere; fuori dalle formule toglie i caratteri C0 tranne
  `\n` e `\t`. Riusa `_repair_inside_math` se adatto.
- Applicala a commento, `domanda_followup`, `parte_mancante` e alle domande generate del ripasso prima di salvarle.
- Test pytest con i tre casi sopra e un testo normale che resta identico.

## 6. Righe di lezione vuote dopo un'importazione fallita
Sul computer di prova sono rimaste lezioni vuote (nessun file, nessuna unità) dopo importazioni di fonti/appunti
fallite. Trova dove la riga della lezione viene creata prima dell'import (creazione lezione da fonti/appunti e
`rt/services/lesson_import_service.py`) e, se il primo job fallisce prima di aver scritto qualcosa, togli riga e
cartella vuota (senza mai cancellare una cartella che contiene file). Test: import che fallisce subito → nessuna
lezione nuova in elenco.

## Chiusura
- `CHANGELOG.md`: nella sezione `## 4.3.9b9 — da pubblicare` (creala sopra la b8 se non c'è, stesso stile).
  Correzioni: «Ripasso: "Non lo so" sull'approfondimento mantiene la prima valutazione e mostra cosa mancava»,
  «Valutazione delle risposte più rapida anche mentre RT prepara nuove domande», «Domande di approfondimento che
  non suggeriscono la risposta anche nelle materie tecniche», «Esercizi e tipi personalizzati: punteggi nei badge
  e domanda di approfondimento», «Formule e caratteri strani nei commenti del ripasso», «Niente lezioni vuote dopo
  un'importazione non riuscita». Non cambiare `VERSION`.
- Esegui: pytest sui test toccati (`tests/test_recall*.py`, `tests/test_jobs*.py` e i nuovi), `npx vitest run`,
  `npx oxlint --deny-warnings`, `npm run build`, `npm run -s check:bundle` in `frontend/` (niente nuove dipendenze).
- Push su `agy/4.3.9-ripasso2`.
