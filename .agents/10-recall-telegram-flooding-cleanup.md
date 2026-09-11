# Task 10 — Recall via Telegram: elimina i messaggi audio/unità al cambio domanda, ripulisci sempre i bottoni, trascritto a comparsa

Indipendente dagli altri task in questa cartella (nessun file condiviso con 06-09; tocca solo
`rt/telegram/daemon.py`, `rt/telegram/formatting.py`, `rt/telegram/registry.py`,
`rt/telegram/client.py`, `rt/pipeline/recall_session.py`).

Nel progetto RT (/Users/attilioturco/Desktop/trt), leggi per intero
`rt/telegram/daemon.py` (in particolare `_send_post_answer_result`, `_handle_recall_callback`,
`_handle_post_answer_callback`, `handle_recall_command`/qualunque punto invii la domanda
corrente, `_handle_recall_text_answer`, `handle_voice`) e `rt/pipeline/recall_session.py`
(`send_current_recall_question`, `send_unit_audio`, `format_unit_reference`) prima di
modificare qualunque cosa — non indovinare la forma delle funzioni esistenti. Implementa
direttamente, senza produrre un piano preliminare.

## Problema

Durante una sessione di recall su Telegram si accumulano nella chat: il messaggio della
domanda (bottoni "Non lo so"/"Skip"), il messaggio dell'esito (correttezza/completezza/
commento + bottoni ⏭️/📖/🔊), e — se l'utente preme 📖 o 🔊 — messaggi separati col testo
dell'unità e/o l'audio. Tre problemi concreti:

1. I messaggi con testo unità e/o audio (inviati da 📖/🔊) non vengono mai eliminati: quando
   si passa alla domanda successiva (⏭️), restano nella chat per sempre, "floodandola".
2. I bottoni "Non lo so"/"Skip" sul messaggio della domanda vengono rimossi SOLO se l'utente
   risponde tramite quei bottoni stessi — se risponde con testo o messaggio vocale, i bottoni
   restano visibili sulla domanda anche dopo essere passati a quella successiva (bug
   confermato: `_handle_recall_text_answer`/`handle_voice` non chiamano mai
   `edit_message_reply_markup` sul messaggio della domanda).
3. Il trascritto di una risposta vocale viene sempre mostrato nel messaggio dell'esito
   (`🗣 Trascritto: "..."` in testa, prima di correttezza/completezza/commento) — occupa
   spazio anche quando non serve rileggerlo. Va nascosto di default, con un bottone dedicato
   per mostrarlo/nasconderlo a comparsa.

## Parte 1 — elimina (non solo rimuovi i bottoni: elimina il messaggio intero) audio/unità al passaggio alla domanda successiva

Quando l'utente preme 📖 (`rut`) o 🔊 (`rua`) nella tastiera post-risposta
(`_handle_post_answer_callback`), il messaggio inviato (testo unità o audio) non ha oggi alcun
message_id tracciato. Cattura il `message_id` del messaggio effettivamente inviato (il valore
di ritorno di `context.bot.send_message(...)`/di qualunque chiamata usata per l'audio in
`send_unit_audio` — se `send_unit_audio` oggi non ritorna il/i message_id dei messaggi audio
inviati, modificala perché lo faccia, dato che una domanda può avere più unità e quindi più
messaggi audio) e memorizzalo nell'entry di registry `kind="recall_post_answer"` già esistente
(`registry.register_pending(..., extra={"question_id": ...})` in `_send_post_answer_result`),
aggiungendo una lista, es. `extra["extra_message_ids"] = []`, aggiornata (via
`registry`'s meccanismo di update esistente — cercalo, es. un `update_pending`/simile, oppure
rileggi e riscrivi l'entry) ogni volta che 📖/🔊 inviano un nuovo messaggio.

Nel branch `rnx` (avanza alla domanda successiva) di `_handle_post_answer_callback`, PRIMA di
chiamare `send_current_recall_question`, elimina tutti i `message_id` accumulati in
`extra_message_ids` per quella `recall_post_answer` entry, chiamando `context.bot.
delete_message(chat_id=..., message_id=...)` per ciascuno (in un try/except silenzioso per
ogni singola delete, dato che Telegram rifiuta di eliminare messaggi troppo vecchi — non deve
bloccare l'avanzamento alla domanda successiva se una delete fallisce). `rt/telegram/client.py`
ha già `delete_message` (riga ~154-164, wrapper di `deleteMessage`) ma non risulta mai chiamato
da `daemon.py` oggi — puoi usare quello, o `context.bot.delete_message` direttamente (verifica
quale stile è più coerente con come `daemon.py` chiama già le altre API in questo file, es.
`context.bot.send_message` è lo stile prevalente lì).

## Parte 2 — rimuovi SEMPRE i bottoni della domanda dopo una risposta, qualunque sia il canale di risposta

Il messaggio della domanda (inviato da `send_current_recall_question` con la tastiera
"Non lo so"/"Skip") deve avere i suoi bottoni rimossi non solo quando si risponde tramite quei
bottoni (`rsk`/`rns` in `_handle_recall_callback`, già corretto), ma anche quando si risponde
con testo (`_handle_recall_text_answer`) o voce (`handle_voice`). Serve conoscere il
`message_id` del messaggio-domanda corrente in quei due handler: verifica come oggi
`send_current_recall_question` traccia/registra il messaggio della domanda (probabilmente un
`registry.register_pending(kind="recall_question", ...)` con o senza il proprio `message_id`
salvato — se non lo salva già, aggiungilo lì) così da poterlo recuperare in
`_handle_recall_text_answer`/`handle_voice` (che presumibilmente già risolvono la domanda
attiva per lesson_dir/thread_id per processare la risposta — usa lo stesso meccanismo per
risalire anche al message_id della domanda). Con quel `message_id` in mano, chiama
`context.bot.edit_message_reply_markup(chat_id=..., message_id=..., reply_markup=None)`
(nota: qui NON hai una `callback_query` da cui chiamare `.edit_message_reply_markup()` come
fanno `rsk`/`rns` — devi usare la variante `context.bot.edit_message_reply_markup(...)` con
`chat_id`+`message_id` espliciti) in un try/except silenzioso (il messaggio potrebbe essere
già stato modificato o essere troppo vecchio).

## Parte 3 — trascritto vocale a comparsa invece che sempre visibile

Riguarda solo il percorso `handle_voice` (l'unico dove esiste un trascritto separato dalla
risposta stessa — nel percorso testuale la risposta già scritta dall'utente È il testo, non
serve un trascritto separato).

1. In `handle_voice`, NON prependere più `f"🗣 Trascritto: \"{answer_text}\"\n\n"` al testo
   dell'esito prima di mandarlo — manda solo `evaluation` come fanno già gli altri percorsi
   (testo, "non lo so").
2. Passa il trascritto (`answer_text`) a `_send_post_answer_result` (aggiungi un parametro
   opzionale `transcript: Optional[str] = None`, `None` per tutti gli altri chiamanti che non
   hanno un trascritto — testo, "non lo so", quiz) e memorizzalo nell'entry di registry
   `recall_post_answer` (`extra["transcript"] = transcript`, più `extra["transcript_visible"]
   = False` come stato iniziale). Non serve ricalcolarlo mai: è già disponibile qui al momento
   dell'invio, e resta comunque persistito separatamente in `RecallAnswer.answer_text` nel
   recall bank per chi volesse recuperarlo in altro modo.
3. In `rt/telegram/formatting.py::build_post_answer_keyboard`, aggiungi un parametro (es.
   `has_transcript: bool = False`) che, quando `True`, aggiunge un quarto bottone ALLA
   SINISTRA degli altri tre, con la sola emoji `🗣` come testo, `callback_data=f"rtt:{short_id}"`
   (nuovo prefisso, "recall transcript toggle"). Passa `has_transcript=(transcript is not None)`
   da `_send_post_answer_result`.
4. Aggiungi il prefisso `"rtt"` al set/tupla che raggruppa le azioni post-risposta (cercalo,
   probabilmente una costante tipo `RECALL_POST_ANSWER_ACTIONS` usata nel dispatch di
   `handle_callback`) e un nuovo branch in `_handle_post_answer_callback` per `action == "rtt"`:
   - Risolvi l'entry `recall_post_answer` da `short_id` (come già fanno `rnx`/`rut`/`rua`).
   - Inverti `extra["transcript_visible"]` e salvalo (stesso meccanismo di persistenza usato
     per `extra_message_ids` nella Parte 1 — se serve un aggiornamento dell'entry esistente
     nel registry invece di crearne una nuova, cercalo/aggiungilo lì, sono la stessa esigenza).
   - Ricostruisci il testo del messaggio: se `transcript_visible` è ora `True`, testo =
     `f"🗣 Trascritto: \"{extra['transcript']}\"\n\n{evaluation_originale}"`; se `False`, solo
     `evaluation_originale` (devi quindi salvare anche il testo di valutazione originale
     nell'entry, es. `extra["evaluation_text"]`, per poterlo ricomporre in entrambe le
     direzioni senza richiamare l'LLM).
   - Aggiorna il messaggio con `context.bot.edit_message_text(chat_id=..., message_id=...,
     text=nuovo_testo, reply_markup=tastiera_invariata)` (serve il `message_id` del messaggio
     dell'esito stesso — se non è già tracciato nell'entry, aggiungilo quando
     `_send_post_answer_result` lo invia, sul modello di come altri flussi nel progetto
     salvano un `message_id` dopo l'invio, es. `tg_session.update_session_message` per
     l'outline).
   - Rispondi al callback (`update.callback_query.answer()`) senza alert, il toggle è silenzioso.

## Test

Aggiungi/aggiorna test in `tests/test_telegram_daemon_recall*.py` (o il file più pertinente
esistente per i callback recall — cercalo) per: eliminazione dei messaggi extra al click su
⏭️ dopo aver usato 📖/🔊 (mocka `context.bot.delete_message` e verifica che venga chiamato coi
message_id giusti); pulizia bottoni della domanda dopo risposta testuale e vocale (mocka
`context.bot.edit_message_reply_markup` e verifica la chiamata); toggle del trascritto (due
click consecutivi su `rtt` producono testi diversi, con e senza la riga del trascritto).
Esegui `python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu stesso prima di
considerare il task concluso.
