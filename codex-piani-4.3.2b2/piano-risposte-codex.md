# Piano 4 · Storico delle risposte e domande riposte senza la vecchia risposta

## Com'è oggi

- Le risposte stanno in `recall_bank.json` della lezione (`RecallBank.answers`, `rt/core/models.py`)
  e non scadono. Ce n'è però **una per domanda**: `record_recall_answer` (`rt/pipeline/recall.py`)
  cerca la risposta esistente e la sovrascrive. Un secondo tentativo cancella il primo.
- Bug: "Riproponi le risposte" (`restore_questions` in `rt/services/recall_editing.py`) rimette la
  domanda `pending`. Quando torna a essere posta (`asked`), `question_resume_view`
  (`rt/services/recall_service.py:279`) trova la vecchia risposta valutata e la restituisce come
  `saved_evaluation`. `LightweightSession.tsx` la mostra subito, con risposta e correzione.
  `mark_answer_seen` (`recall_editing.py`) ha lo stesso difetto: con una vecchia valutazione segna
  subito la domanda come `answered`.
- `saved_evaluation` serve a riprendere una valutazione dopo aver ricaricato la pagina, e quel caso
  deve continuare a funzionare.

## Cosa deve succedere

1. Ogni risposta è un **tentativo** nuovo: rispondere di nuovo alla stessa domanda aggiunge, non
   sovrascrive.
2. Una domanda riposta si presenta vuota: si risponde, si valuta, e solo dopo si vede la correzione.
3. Dal pannello Domande della lezione (`QuestionsPanel.tsx`) un pulsante a icona apre la pagina
   **Risposte**: tutte le risposte date per quella lezione.

## Modello

- `RecallQuestion` guadagna `asked_at: Optional[str] = None` (ISO locale, come `answered_at`).
- Si imposta **solo** nel passaggio a `asked` da un altro stato:
  - `get_next_pending_question` (`rt/pipeline/recall.py`, dove fa `selected.status = ASKED`), solo
    se lo stato precedente non era già `ASKED`: con `include_asked` una domanda già posta si riprende
    senza cambiare `asked_at`;
  - lo stato impostato a mano in `recall_editing.py` (`wanted == ASKED`).
- `RecallAnswer` guadagna `attempt_id: str` (default `uuid4().hex[:12]`), per indicare un tentativo
  senza contare sulle posizioni.

## Registrazione

- `record_recall_answer`:
  - se c'è una risposta della stessa domanda con `answer_text` vuoto e `answered_at >= asked_at`
    (una riga con il solo voto, creata da `record_recall_vote` durante questo giro), riempie quella;
  - in tutti gli altri casi **aggiunge** una `RecallAnswer` nuova.
  - Lo stato della domanda cambia come oggi.
- `record_recall_vote`: aggiorna il voto sull'ultima risposta della domanda (la più recente per
  `answered_at`). Se non ce n'è, crea la riga con il solo voto come oggi.
- Gli altri punti che leggono `bank.answers` vanno controllati uno per uno. Devono usare l'ultima
  risposta dove serve un solo esito, e tutte dove servono i conteggi:
  - `_latest_outcomes`, `recall_history`, `question_list` (i voti), in
    `rt/services/recall_service.py`;
  - `_last_outcome`, `mark_answer_seen`, in `rt/services/recall_editing.py`;
  - `rt/services/recall_sessions.py` (conta i tentativi nel periodo: va bene che conti ogni
    tentativo);
  - `rt/pipeline/recall.py:67` (i voti);
  - la cancellazione di domande (`recall_service.py:127`, `recall.py:835`), che continua a togliere
    tutte le risposte della domanda.

## Ripresa senza la vecchia risposta

Nuova funzione `current_answers(bank, question)` in `rt/pipeline/recall.py`: le risposte della
domanda con `answered_at >= question.asked_at`. Se `asked_at` è `None` (domande vecchie, mai
riposte), restituisce tutte le risposte, cioè il comportamento di oggi.

- `question_resume_view`: `saved_evaluation` solo dall'ultima di `current_answers` con
  `evaluation`.
- `mark_answer_seen`: segna `answered` solo se una di `current_answers` ha `evaluation`.
- `restore_questions` non deve cancellare niente: le risposte vecchie restano nello storico.

## API

- `GET /lessons/{lesson_id}/recall/history` esiste già (`schemas.RecallHistory`) e restituisce
  domande e risposte. Aggiungi `attempt_id` a `RecallAnswerRecord`.
- Ordina le risposte per `answered_at` decrescente.
- Rigenera lo schema del frontend e l'openapi.

## Pagina Risposte

- Rotta `lezioni/:lessonId/risposte`, `handle: bare`, componente `RecallAnswersPage` in
  `frontend/src/components/recall/RecallAnswersPage.tsx`, caricato pigro come le altre pagine di
  recall in `frontend/src/routes/index.tsx`.
- Dati: `useRecallHistory(lessonId)` (`frontend/src/api/recall.ts`).
- Elenco, dal più recente:
  - testo della domanda (con `MathText`, come nella sessione);
  - risposta data (testo; per il quiz l'opzione scelta; "Non lo so" se `dont_know`; un'icona
    microfono se `is_voice`);
  - esito con il colore già usato per `corretta`, `parziale` e `sbagliata`;
  - data e ora brevi.
- Un clic sulla riga apre la valutazione (`evaluation`, renderizzata come nella sessione).
- I tentativi della stessa domanda si raggruppano sotto la domanda, il più recente in alto.
- Filtro a icone in alto, come "Filtra per stato" del pannello: tutte, sbagliate, parziali,
  corrette. Niente leggenda.
- Vuoto: "Nessuna risposta."
- Indietro: torna alla lezione, sul pannello Domande.
- In `QuestionsPanel.tsx`, nel gruppo `questions-restore` accanto a "Riproponi le risposte", un
  `IconButton` con icona `History` (lucide) e `label="Risposte"`, che porta a
  `/lezioni/<id>/risposte`. Va mostrato anche quando non c'è niente da riproporre, ma solo se esiste
  almeno una risposta: il blocco oggi compare solo con `askedCount > 0 || wrongCount > 0`.

## Test

- `tests/test_recall_*.py` (accanto ai test esistenti di recall):
  - due risposte alla stessa domanda danno due tentativi;
  - il voto va sull'ultimo tentativo;
  - una domanda risposta, riposta con `restore_questions` e poi ripresa con `next_question` non ha
    `saved_evaluation`, e `mark_answer_seen` non la segna `answered`;
  - dopo una nuova risposta valutata, `saved_evaluation` torna e contiene la risposta nuova;
  - una domanda vecchia senza `asked_at` riprende la valutazione come oggi;
  - `asked_at` non cambia riprendendo una domanda già `asked` con `include_asked`.
- Vitest:
  - `RecallAnswersPage` raggruppa i tentativi e filtra per esito;
  - `QuestionsPanel` mostra il pulsante Risposte con almeno una risposta e non lo mostra senza.
- `LightweightSession.test.tsx`: una domanda senza `saved_evaluation` parte con il campo risposta
  vuoto (dovrebbe già passare: serve come guardia).

## Changelog

- Le domande riposte si possono rispondere davvero: la vecchia risposta e la correzione non
  compaiono più subito.
- Ogni risposta resta nello storico, e la pagina Risposte (dal pannello Domande) le mostra tutte per
  la lezione.
