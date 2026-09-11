# Task 11 — Recall Telegram: bottoni 📖/🔊 permanenti e a comparsa (toggle), 🗣/⏭️ ripuliti anche su /quit

Indipendente dagli altri task in questa cartella. Segue e affina il comportamento introdotto
dal Task 10 (già implementato e committato) — leggi per intero `rt/telegram/daemon.py`
(`_send_post_answer_result`, `_handle_post_answer_callback`, `handle_quit`),
`rt/telegram/formatting.py` (`build_post_answer_keyboard`), `rt/pipeline/recall_session.py`
(`format_unit_reference`, `send_unit_audio`, `send_current_recall_question`,
`load_recall_session_state`/`save_recall_session_state`) prima di modificare qualunque cosa —
non indovinare la forma delle funzioni esistenti, sono già state scritte in un giro precedente.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto e comportamento desiderato

Oggi (dopo il Task 10) i bottoni 📖 (testo unità) e 🔊 (audio unità) sul messaggio di esito di
una domanda di recall: (a) mandano SEMPRE un nuovo messaggio a ogni click (mai un toggle), e
(b) i messaggi che producono vengono eliminati quando si passa alla domanda successiva (⏭️),
insieme a tutta la tastiera dell'esito. Il nuovo comportamento voluto è diverso e più
persistente:

- 📖 e 🔊 diventano bottoni **permanenti**: NON vengono più rimossi né dal passaggio alla
  domanda successiva (⏭️) né dalla chiusura della sessione (`/quit`). Restano cliccabili
  indefinitamente, anche a distanza di tempo e di innumerevoli altre sessioni di recall aperte
  e chiuse nel mezzo (nessun problema di scadenza: `rt/telegram/registry.py::prune_registry`
  esiste ma non risulta mai invocato automaticamente da nessuna parte — verificato, non è un
  rischio reale oggi, ma se aggiungi logica di pulizia in questo task non applicarla a queste
  entry).
- 📖 e 🔊 diventano dei **toggle invece di "manda sempre"**: primo click su 📖 → manda il testo
  dell'unità (già oggi preso "fresco" da `load_resolved_draft` via `format_unit_reference`,
  quindi già sempre la versione più recente — non serve cambiare questo). Secondo click sullo
  STESSO bottone, quando il messaggio testo-unità è ancora presente → elimina quel messaggio
  (non manda nulla di nuovo). Stesso schema per 🔊 con l'audio (già cachato in
  `recall_audio_clips/<unit_id><ext>` dentro la lezione da `send_unit_audio`, quindi non serve
  già ritagliarlo di nuovo con ffmpeg — verificato, questa parte è già corretta). Una domanda
  con più unità (es. tipo vasta) può produrre più messaggi audio: traccia una lista di
  message_id per l'audio, mostra/nascondi tutti insieme con lo stesso bottone.
- I bottoni 🗣 (trascritto a comparsa) e ⏭️ (prossima domanda), al contrario, devono sparire sia
  al passaggio alla domanda successiva (già cosà oggi per ⏭️ dato che rimuove l'intera tastiera
  — va solo cambiato per NON rimuovere anche 📖/🔊) sia alla chiusura della sessione con
  `/quit` (oggi NON succede affatto: bug confermato, vedi sotto).

## Parte 1 — nuova tastiera "persistente" e modifica del comportamento di ⏭️

1. In `rt/telegram/formatting.py`, aggiungi:
   ```python
   def build_persistent_recall_keyboard(short_id: str) -> dict:
       """Bottoni 📖/🔊 permanenti: sopravvivono al passaggio alla domanda successiva e alla
       chiusura della sessione, restano cliccabili indefinitamente."""
       return {"inline_keyboard": [[
           {"text": "📖", "callback_data": f"rut:{short_id}"},
           {"text": "🔊", "callback_data": f"rua:{short_id}"},
       ]]}
   ```
2. Nel branch `rnx` di `_handle_post_answer_callback` (`rt/telegram/daemon.py`): sostituisci
   `await update.callback_query.edit_message_reply_markup(reply_markup=None)` con
   `await update.callback_query.edit_message_reply_markup(reply_markup=tg_fmt.build_
   persistent_recall_keyboard(short_id))`. RIMUOVI il blocco che elimina
   `entry.get("extra_message_ids", [])` (quei messaggi non vengono più eliminati al
   passaggio alla domanda successiva — restano, gestiti dal toggle di Parte 2).

## Parte 2 — 📖/🔊 diventano toggle send/delete

Nell'entry di registry `kind="recall_post_answer"` (creata da `_send_post_answer_result`),
sostituisci il campo `extra_message_ids` (lista generica) con due campi dedicati:
`unit_text_message_id: Optional[int] = None` e `audio_message_ids: List[int] = []` (aggiorna
sia la creazione dell'entry in `_send_post_answer_result` sia ogni punto che la leggeva prima).

Riscrivi il branch `rut` di `_handle_post_answer_callback`:
```python
if action == "rut":
    await update.callback_query.answer()
    existing_id = entry.get("unit_text_message_id")
    if existing_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=existing_id)
        except Exception:
            pass
        registry.update_pending(short_id, {"unit_text_message_id": None}, state_dir)
        return
    from rt.pipeline.recall_session import format_unit_reference
    text = await loop.run_in_executor(None, format_unit_reference, lesson_dir, question)
    text = text.strip() or "⚠️ Nessun contenuto disponibile per questa unità."
    res = await _send_with_retry(lambda: context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, message_thread_id=thread_id,
    ))
    msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
    if isinstance(msg_id, int):
        registry.update_pending(short_id, {"unit_text_message_id": msg_id}, state_dir)
    return
```
E il branch `rua`, stesso schema ma su una lista:
```python
if action == "rua":
    existing_ids = entry.get("audio_message_ids") or []
    if existing_ids:
        await update.callback_query.answer()
        for mid in existing_ids:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=mid)
            except Exception:
                pass
        registry.update_pending(short_id, {"audio_message_ids": []}, state_dir)
        return
    await update.callback_query.answer("🔊 Preparo l'audio...")
    from rt.pipeline.recall_session import send_unit_audio
    try:
        sent_ids = await loop.run_in_executor(None, send_unit_audio, lesson_dir, question, thread_id)
        if sent_ids:
            registry.update_pending(short_id, {"audio_message_ids": [i for i in sent_ids if isinstance(i, int)]}, state_dir)
    except Exception as e:
        await _send_with_retry(lambda: context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"⚠️ Impossibile inviare l'audio: {e}", message_thread_id=thread_id,
        ))
    return
```
Adatta ai nomi esatti già presenti (`_send_with_retry`, gestione errori, ecc. — non
reinventare quello che già c'è, riusa lo stile del file).

## Parte 3 — `/quit` deve ripulire anche il messaggio di esito, non solo quello della domanda

Bug confermato: `handle_quit` oggi rimuove i bottoni solo dal messaggio tracciato dalla
sessione generica (`tg_session`, che per il recall è il messaggio della DOMANDA, aggiornato da
`send_current_recall_question` via `tg_session.update_session_message(...)`), ma non sa nulla
del messaggio di ESITO separato (`recall_post_answer`, tracciato solo nel `registry` generico)
— quindi dopo aver risposto, i suoi bottoni (🗣/⏭️/📖/🔊) restano intatti anche dopo `/quit`.

1. In `rt/pipeline/recall_session.py`, in `_send_post_answer_result`... aspetta, questa
   funzione è in `rt/telegram/daemon.py`, non in recall_session.py — verifica tu la
   collocazione esatta leggendo il file. Ovunque si trovi, subito dopo aver ottenuto `msg_id`
   dall'invio del messaggio di esito, persisti anche lì (stesso file/meccanismo con cui oggi
   viene salvato `current_question_message_id` in `recall_session_state.json` via
   `load_recall_session_state`/`save_recall_session_state` in `rt/pipeline/recall_session.py`)
   due nuovi campi: `current_post_answer_short_id` e `current_post_answer_message_id`.
2. In `handle_quit` (`rt/telegram/daemon.py`), quando `kind == "recall"` (la sessione
   registrata da `rt/pipeline/recall_session.py:198`,
   `tg_session.start_session(..., "recall", lesson_dir)`), oltre alla pulizia già esistente del
   messaggio-domanda: carica `load_recall_session_state(lesson_dir)`, e se presenti
   `current_post_answer_short_id`/`current_post_answer_message_id`, chiama
   `context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=<quel message_id>,
   reply_markup=tg_fmt.build_persistent_recall_keyboard(<quel short_id>))` in un try/except
   silenzioso (il messaggio potrebbe non esistere più, o essere già stato modificato — non
   deve bloccare la chiusura della sessione).

## Test

Aggiorna/aggiungi test in `tests/test_recall_session.py`/i test daemon recall esistenti per:
toggle di 📖 (primo click invia, secondo click elimina, terzo click reinvia); toggle di 🔊 con
lista di message_id; `rnx` che lascia intatti 📖/🔊 ma rimuove 🗣/⏭️; `/quit` che ripulisce
anche il messaggio di esito a 🗣/⏭️-vuoto lasciando 📖/🔊. Esegui `python3 -m pytest tests/ -q`
e correggi eventuali fallimenti tu stesso prima di considerare il task concluso.

## Attenzione — bug di portabilità già visto due volte in questo progetto

In diversi task precedenti (06-10) sono stati introdotti usi di `Optional[...]`/`List[...]`
come annotazione di tipo senza il corrispondente `from typing import Optional, List` in cima
al file — funziona per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo
differito di default, PEP 649) ma darebbe `NameError` su Python <3.14. Se aggiungi o modifichi
firme di funzione con annotazioni di tipo da `typing` in questo task, verifica sempre che siano
importate esplicitamente nel file, non dare per scontato che "funzioni" sia sufficiente.
