# Task 12 — Recall: da cancellazione silenziosa ad avviso + `rt recall --check` per rivedere manualmente

Indipendente dagli altri task in questa cartella, ma **rivede un comportamento introdotto dal
Task 08** (già implementato e committato): leggi per intero `rt/pipeline/recall.py`
(`get_next_pending_question`, `_compute_units_fingerprint`, `generate_recall_batch`) e
`rt/core/models.py` (`RecallQuestion`, `RecallBank`, `RecallAnswer`) prima di modificare
qualunque cosa — il meccanismo di fingerprint esiste già, va solo cambiato COSA si fa quando
il fingerprint non corrisponde più.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Cosa cambia rispetto al Task 08

Oggi (`get_next_pending_question`, dopo il Task 08) una domanda PENDING il cui
`content_fingerprint` non corrisponde più al contenuto attuale dell'unità viene **rimossa
silenziosamente** dal recall bank, senza che l'utente ne sappia nulla. Il nuovo comportamento
voluto è diverso: **non cancellare mai automaticamente**, ma segnalare e lasciare all'utente la
scelta.

1. In `get_next_pending_question`: **rimuovi** il blocco che filtra `pending` per fingerprint e
   cancella `stale_ids` dal bank (quello aggiunto dal Task 08). Le domande stale restano nel
   pool esattamente come le altre — nessun filtro qui. La funzione `_compute_units_fingerprint`
   resta (serve ancora, riusata sotto).

2. Quando una domanda viene effettivamente proposta via Telegram (`rt/pipeline/
   recall_session.py::send_current_recall_question`, sia per il testo mirata/vasta sia per il
   poll quiz), PRIMA di costruire il testo/poll da inviare, verifica se è stale:
   ```python
   from rt.pipeline.recall import _compute_units_fingerprint
   current_fp = _compute_units_fingerprint(lesson_dir, question.unit_ids)
   is_stale = (
       question.content_fingerprint is not None
       and current_fp is not None
       and current_fp != question.content_fingerprint
   )
   ```
   Se `is_stale`, antepone al testo della domanda (per mirata/vasta) o al testo introduttivo
   del poll (per quiz — verifica come è costruito oggi, i poll Telegram hanno un limite di
   caratteri sulla domanda stessa, quindi se serve manda l'avviso come messaggio separato
   PRIMA del poll invece che dentro la domanda del poll) una riga tipo:
   ```
   ⚠️ L'unità {unit_ids} da cui è tratta questa domanda è stata modificata dopo la generazione
   di questa domanda.
   ```
   (usa gli `unit_ids` effettivi della domanda, non un placeholder letterale "[numero]").
   Questo avviso è puramente informativo: non cambia in alcun modo il flusso di risposta o
   valutazione della domanda, che procede normalmente.

## `rt recall <cartella> --check`

Nuovo flag booleano su `p_recall` in `rt/cli.py` (`--check`, `action="store_true"`), gestito
in `cmd_recall` PRIMA di qualunque altra logica (stesso stile di come `--reset` è già gestito
lì, guarda quel codice come precedente diretto).

1. **Controllo sessione Telegram attiva**: prima di procedere, verifica se esiste una sessione
   attiva di tipo `"recall"` per questa lezione (`tg_session.start_session(..., "recall",
   lesson_dir)` è come viene registrata in `rt/pipeline/recall_session.py:198` — leggi
   `rt/telegram/session.py` per capire come enumerare/interrogare le sessioni attive dato un
   `lesson_dir` invece che un `chat_id`+`thread_id` specifico, dato che qui non abbiamo quei
   due valori a portata di mano da terminale; potrebbe servire risolvere il/i topic associati
   alla materia della lezione — verifica `rt.telegram.config.resolve_topic_id` — e controllare
   la sessione su quel `chat_id`+`thread_id`, oppure se `session.py` espone già un modo più
   diretto per cercare per `lesson_dir`, usa quello). Se c'è una sessione attiva, stampa un
   messaggio che invita a chiuderla da Telegram con `/quit` e a rilanciare `--check` dopo, poi
   esci senza fare nient'altro (nessuna modifica al recall bank).

2. **Raccolta delle domande da rivedere**: se non c'è una sessione attiva, carica il recall
   bank (`load_recall_bank(lesson_dir)`) e filtra **tutte** le domande (`pending`, `asked`, E
   `answered` — tutti e tre gli stati, non solo pending) il cui `content_fingerprint` non è
   `None` e non corrisponde più a `_compute_units_fingerprint(lesson_dir, q.unit_ids)`. Se
   nessuna, stampa "Nessuna domanda da rivedere." ed esci.

3. **Sessione di revisione interattiva da terminale**, sullo stesso modello di
   `run_interactive_review` in `rt/pipeline/issue_review.py` (raw_mode/read_single_key da
   `rt/core/keyboard.py`, `rich.live.Live` per il redraw, indice mobile con possibilità di
   tornare indietro annullando l'ultima decisione — copia lo STESSO schema di navigazione, non
   inventarne uno nuovo): per ciascuna domanda stale, mostra in un pannello: tipo
   (quiz/mirata/vasta), `unit_ids`, `question_text`, stato (`pending`/`asked`/`answered`), ed
   eventualmente `pregenerated_material`/l'ultima risposta registrata se `answered` (per dare
   contesto su cosa si sta per tenere o eliminare). Tasti:
   - `[M]antieni`: aggiorna `content_fingerprint` al valore corrente
     (`_compute_units_fingerprint(lesson_dir, q.unit_ids)`) e salva il bank — la domanda non
     verrà più segnalata come stale finché il contenuto non cambia di nuovo. Avanza alla
     successiva.
   - `[E]limina`: rimuove la domanda dal bank E ogni `RecallAnswer` con `question_id` uguale al
     suo (stesso filtro già usato in `purge_recall_by_type` del Task 09 — riusa quella logica
     di rimozione risposte associate, non duplicarla da zero se riesci a fattorizzarla in un
     helper condiviso). Avanza alla successiva.
   - Freccia destra: salta (nessuna decisione, resta stale, ricomparirà in un `--check`
     successivo). Freccia sinistra: torna indietro e annulla l'ultima decisione presa in questa
     sessione (se era "Mantieni", ripristina il fingerprint precedente; se era "Elimina",
     reinserisce la domanda e le sue risposte nel bank — tienile temporaneamente in memoria
     durante la sessione per poterle ripristinare, esattamente come `revert_last_decision`
     funziona per la review ASR/scienza).
   Quando tutte le domande stale sono state gestite (o saltate), stampa un riepilogo (quante
   mantenute, quante eliminate, quante saltate) ed esci.

## Test

Aggiungi test per: il messaggio di avviso ⚠️ antemesso quando `send_current_recall_question`
propone una domanda stale (e la sua assenza quando non è stale); `--check` che rifiuta di
procedere con una sessione Telegram attiva su quella lezione; la sessione di revisione
interattiva (mantieni aggiorna il fingerprint, elimina rimuove domanda+risposte, indietro
annulla l'ultima decisione) usando lo stesso pattern di test già presente per
`run_interactive_review` in `tests/test_issue_review.py` (simulazione tasti via `builtins.
input` quando non-TTY). Esegui `python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu
stesso prima di considerare il task concluso.

## Attenzione — bug di portabilità già visto più volte in questo progetto

In diversi task precedenti sono stati introdotti usi di `Optional[...]`/`List[...]` come
annotazione di tipo senza il corrispondente `from typing import ...` in cima al file — funziona
per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito di
default, PEP 649) ma darebbe `NameError` su Python <3.14. Se aggiungi o modifichi firme di
funzione con annotazioni da `typing` in questo task, verifica sempre che siano importate
esplicitamente nel file.
