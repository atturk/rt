# Task 09 — Recall: niente commento ridondante su "Non lo so" + flag `rt recall --reset`

Piccola sovrapposizione col Task 08 su `rt/pipeline/recall.py` (funzioni diverse). Se entrambi
i task sono in esecuzione, eseguili in ordine numerico: 08 prima di 09.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente due funzionalità
indipendenti, senza produrre un piano preliminare.

## Parte 1 — "Non lo so" non deve generare un commento che dice "la risposta è assente"

Quando l'utente sceglie "🤷 Non lo so" su Telegram, `rt/telegram/daemon.py:458` passa la
stringa letterale `"[Non lo so]"` come `answer_text` a `handle_recall_answer`, che finisce in
`rt/pipeline/recall.py::evaluate_recall_answer` (righe ~449-514). Oggi questa stringa viene
interpolata nel prompt normale (`build_recall_eval_mirata_user_prompt`/`build_recall_eval_
vasta_user_prompt` in `rt/llm/prompts.py`) senza alcun trattamento speciale, e il modello
segue la regola generale del system prompt (evidenziare cosa manca) producendo un commento
tipo "La risposta è assente: non viene menzionato...", ridondante quando l'utente ha già
dichiarato esplicitamente di non sapere.

Fix (prompt-level, come richiesto, non un semplice bypass della chiamata — l'LLM serve comunque
per generare la spiegazione corretta, che non abbiamo pre-calcolata):

1. In `rt/pipeline/recall.py::evaluate_recall_answer`, subito dopo aver risolto `question` e
   prima del ramo `force_mock`, rileva il caso speciale:
   ```python
   is_dont_know = answer_text.strip() == "[Non lo so]"
   ```
2. In `rt/llm/prompts.py`, in `build_recall_eval_mirata_user_prompt` e
   `build_recall_eval_vasta_user_prompt` (leggi le firme esatte prima di modificarle), aggiungi
   un parametro opzionale `dont_know: bool = False` che, quando `True`, aggiunge al prompt
   utente un'istruzione tipo:
   ```
   NOTA: lo studente ha dichiarato esplicitamente di non sapere rispondere (non ha fornito
   alcun tentativo). NON scrivere che la risposta è assente, mancante o non fornita — è già
   noto. Fornisci direttamente e solo la spiegazione corretta e completa dell'argomento, come
   se stessi semplicemente insegnando la risposta.
   ```
   invece del testo/placeholder di risposta studente normale (o in aggiunta, a tua scelta di
   dettaglio implementativo, purché il modello riceva chiaramente che non deve commentare
   l'assenza). Passa `dont_know=is_dont_know` da `evaluate_recall_answer` quando costruisce i
   due prompt.
3. Indipendentemente da cosa risponde il modello per i campi numerici, quando `is_dont_know` è
   `True` sovrascrivi via codice (non fidarti del modello per un caso deterministico):
   per MIRATA, forza `result.correttezza = 0` e `result.completezza = 0` prima di costruire la
   stringa di ritorno `f"Correttezza: {result.correttezza}%\n..."`. Per VASTA non ci sono
   percentuali da forzare (solo commento), nessun cambio necessario oltre al prompt.
4. NON toccare lo schema Pydantic `RecallEvalMirataResult`/`RecallEvalVastaResult` — restano
   identici, cambia solo il contenuto del prompt e l'eventuale override numerico post-chiamata.
5. Verifica se esiste un percorso equivalente lato terminale (grep "Non lo so"/logica simile in
   `rt/pipeline/recall_session.py`) che passa per la stessa `evaluate_recall_answer` — se sì,
   il fix qui sopra lo copre automaticamente, non serve toccare altro.

## Parte 2 — `rt recall <cartella> --reset [quiz|mirata|vasta]`

Nuovo flag CLI, solo terminale per ora (nessun comando Telegram equivalente — deliberatamente,
per ora il bot resta "pulito" da funzioni di reset).

1. In `rt/pipeline/recall.py`, aggiungi una funzione che rimuove domande/risposte per tipo,
   sul modello di `purge_decisions_by_prefix` in `rt/pipeline/ledger.py:150-158`:
   ```python
   def purge_recall_by_type(lesson_dir: str, qtype: Optional[RecallQuestionType] = None) -> int:
       """Rimuove dal recall bank le domande (e le relative risposte) del tipo specificato,
       o tutte se qtype è None. Ritorna il numero di domande rimosse."""
       bank = load_recall_bank(lesson_dir)
       if qtype is None:
           removed_ids = {q.id for q in bank.questions}
           bank.questions = []
       else:
           removed_ids = {q.id for q in bank.questions if q.type == qtype}
           bank.questions = [q for q in bank.questions if q.type != qtype]
       bank.answers = [a for a in bank.answers if a.question_id not in removed_ids]
       if removed_ids:
           save_recall_bank(bank, lesson_dir)
       return len(removed_ids)
   ```
   Adatta i nomi esatti (`load_recall_bank`/`save_recall_bank`/`RecallQuestionType` sono già
   nel file — verifica gli import) e lo schema esatto di `RecallBank`/`RecallQuestion`/
   `RecallAnswer` in `rt/core/models.py` prima di scrivere il filtro.

2. In `rt/cli.py`, sul subparser `recall` (`p_recall`, cercalo in `main()`), aggiungi:
   ```python
   p_recall.add_argument(
       "--reset", nargs="?", const="all", choices=["all", "quiz", "mirata", "vasta"], default=None,
       help="Resetta le domande/risposte di recall già effettuate: senza valore o 'all' azzera "
            "tutto, 'quiz'/'mirata'/'vasta' azzera solo quel tipo. Va eseguito PRIMA di avviare "
            "una sessione (esce subito dopo il reset, non avvia la sessione nella stessa invocazione)."
   )
   ```
   In `cmd_recall` (`rt/cli.py`), gestisci `--reset` come primissima cosa nella funzione
   (prima del controllo `check_phase_status`/prima di qualunque altra logica): se presente,
   chiama `purge_recall_by_type` col tipo giusto (`None` per "all"), stampa quante domande sono
   state rimosse, e fai `return` subito (NON avviare una sessione di recall nella stessa
   invocazione — l'utente rilancerà `rt recall` normalmente dopo, per design, così il comando
   fa una cosa sola e il suo effetto è chiaro).

## Test

Aggiungi test per `purge_recall_by_type` (reset selettivo per tipo, reset totale, nessun
effetto su tipi non specificati, risposte orfane rimosse insieme alle domande) e per il branch
"non lo so" di `evaluate_recall_answer` (mock del client LLM, verifica che `correttezza`/
`completezza` risultino forzati a 0 nel testo restituito quando `answer_text == "[Non lo so]"`).
Esegui `python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu stesso prima di
considerare il task concluso.
