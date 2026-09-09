"""
rt.telegram.daemon
Processo persistente in polling: unico componente che riceve bottoni cliccati e
messaggi di feedback. Risolve short_id -> lesson_dir tramite rt.telegram.registry
e scrive le risposte in telegram_pending.json tramite rt.telegram.pending.
"""
import os
import sys
import json
import time
import asyncio
from datetime import datetime

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, CommandHandler, PollAnswerHandler, MessageReactionHandler, ContextTypes, filters

from rt.core.config import load_config
from rt.telegram.config import load_telegram_config
from rt.telegram import registry, pending as tg_pending, conversation_state as convo, session as tg_session

ISSUE_ACTIONS = {"ia", "ir", "ie", "is", "iq", "ib"}
RECALL_ACTION_ACTIONS = {"rns", "rsk"}
RECALL_POST_ANSWER_ACTIONS = {"rnx", "rut", "rua"}
RECALL_REACTION_VOTE_MAP = {"👍": "up", "👎": "down", "⚡": "lightning"}


async def _send_with_retry(coro_factory, max_retries: int = 1):
    attempts = 0
    while True:
        try:
            return await coro_factory()
        except RetryAfter as e:
            if attempts < max_retries:
                attempts += 1
                if isinstance(e.retry_after, (int, float)):
                    retry_sec = float(e.retry_after)
                elif hasattr(e.retry_after, "total_seconds"):
                    retry_sec = float(e.retry_after.total_seconds())
                else:
                    try:
                        retry_sec = float(e.retry_after)
                    except (ValueError, TypeError):
                        retry_sec = 1.0
                await asyncio.sleep(retry_sec)
                continue
            raise


def _heartbeat_path(state_dir: str) -> str:
    return os.path.join(state_dir, "daemon_heartbeat.json")


async def _write_heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    os.makedirs(state_dir, exist_ok=True)
    tmp_path = _heartbeat_path(state_dir) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"last_seen": datetime.now().isoformat()}, f)
    os.replace(tmp_path, _heartbeat_path(state_dir))


async def handle_quit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message else None

    active = tg_session.get_active_session(state_dir, chat_id, thread_id)
    if active is None:
        await _send_with_retry(lambda: update.effective_message.reply_text(
            "Nessuna attività in corso in questo topic.",
            message_thread_id=thread_id,
        ))
        return

    kind = active.get("kind")
    lesson_dir = active.get("lesson_dir")
    message_id = active.get("message_id")

    if message_id is not None:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except Exception:
            pass

    convo.clear_awaiting_feedback(state_dir, chat_id)
    tg_session.end_session(state_dir, chat_id, thread_id)

    if kind == "issue_review":
        await _send_with_retry(lambda: update.effective_message.reply_text(
            "⏹ Revisione interrotta. I progressi finora sono stati salvati.",
            message_thread_id=thread_id,
        ))
    elif kind == "outline_confirmation":
        if lesson_dir and os.path.exists(lesson_dir):
            try:
                tg_pending.mark_responded(lesson_dir, status="cancelled", responded_via="telegram")
            except Exception:
                pass
        await _send_with_retry(lambda: update.effective_message.reply_text(
            "⏹ Conferma outline annullata.",
            message_thread_id=thread_id,
        ))
    else:
        await _send_with_retry(lambda: update.effective_message.reply_text(
            "⏹ Attività interrotta.",
            message_thread_id=thread_id,
        ))


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message else None

    active = tg_session.get_active_session(state_dir, chat_id, thread_id)
    if active is None:
        await _send_with_retry(lambda: update.effective_message.reply_text(
            "Nessuna attività in corso in questo topic.",
            message_thread_id=thread_id,
        ))
        return

    kind = active.get("kind", "sconosciuto")
    lesson_dir = active.get("lesson_dir", "")
    folder_name = os.path.basename(os.path.normpath(lesson_dir)) if lesson_dir else "N/D"

    await _send_with_retry(lambda: update.effective_message.reply_text(
        f"Attività in corso: {kind} ({folder_name})",
        message_thread_id=thread_id,
    ))


async def handle_recall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/recall lanciato da Telegram: usa, in ordine, (1) l'override esplicito per la materia
    di questo topic in config/telegram/recall_lessons.yaml se presente, altrimenti (2) l'ultima
    lezione con build completata su questo topic (tracciata automaticamente da
    notify_build_completed). Nessun argomento richiesto — non è un indice/browser di lezioni."""
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message else None

    from rt.core.config import load_config
    from rt.telegram.recall_lessons import get_lesson_override
    from rt.telegram.last_lesson import get_last_lesson

    lesson_dir = None
    runtime_cfg = load_config().telegram
    materia = next((m for m, tid in (runtime_cfg.topics or {}).items() if tid == thread_id), None)
    if materia:
        override = get_lesson_override(materia)
        if override and os.path.isdir(override):
            lesson_dir = override

    if not lesson_dir:
        auto = get_last_lesson(state_dir, chat_id, thread_id)
        if auto and os.path.isdir(auto):
            lesson_dir = auto

    if not lesson_dir:
        await _send_with_retry(lambda: update.effective_message.reply_text(
            "Nessuna lezione trovata per questo topic. Il bot ricorda automaticamente solo "
            "l'ULTIMA lezione con build completata fatta in questo topic (non è un indice: "
            "serve almeno una build qui prima che /recall funzioni). Nel frattempo puoi "
            "avviare il recall da terminale con: rt recall \"<cartella>\" --channel telegram\n\n"
            "Per fissare esplicitamente quale lezione usare per questa materia, aggiungi una "
            "entry a config/telegram/recall_lessons.yaml (vedi docs/CONFIGURATION_REFERENCE.md).",
            message_thread_id=thread_id,
        ))
        return

    loop = asyncio.get_running_loop()
    from rt.pipeline.recall_session import start_recall_via_telegram
    await loop.run_in_executor(None, start_recall_via_telegram, lesson_dir, "alternato", None, False)


async def handle_stile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stile: propone i 3 stili di domanda con dei bottoni, nessun argomento da digitare."""
    state_dir = context.bot_data["state_dir"]
    thread_id = update.effective_message.message_thread_id if update.effective_message else None
    from rt.telegram import recall_preferences, formatting as tg_fmt

    current = recall_preferences.get_active_style(state_dir)
    keyboard = tg_fmt.build_stile_keyboard(current)
    await _send_with_retry(lambda: update.effective_message.reply_text(
        f"Stile attivo: {current}\nScegli lo stile per la prossima domanda di recall:",
        reply_markup=keyboard,
        message_thread_id=thread_id,
    ))


async def _handle_stile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, style: str) -> None:
    state_dir = context.bot_data["state_dir"]
    from rt.telegram import recall_preferences

    if style not in recall_preferences.VALID_STYLES:
        await update.callback_query.answer("Stile non valido.", show_alert=True)
        return
    recall_preferences.set_active_style(state_dir, style)
    await update.callback_query.answer(f"Stile impostato: {style}")
    try:
        await update.callback_query.edit_message_text(f"Stile attivo: {style} ✅")
    except Exception:
        pass


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    if ":" not in data:
        await query.answer()
        return
    prefix, short_id = data.split(":", 1)
    if prefix in ("rtappr", "rtedit"):
        await _handle_outline_callback(update, context, prefix, short_id)
    elif prefix in ISSUE_ACTIONS:
        await _handle_issue_callback(update, context, prefix, short_id)
    elif prefix == "ivr":
        await _handle_start_review_callback(update, context, short_id)
    elif prefix in RECALL_ACTION_ACTIONS:
        await _handle_recall_callback(update, context, prefix, short_id)
    elif prefix in RECALL_POST_ANSWER_ACTIONS:
        await _handle_post_answer_callback(update, context, prefix, short_id)
    elif prefix == "stile":
        await _handle_stile_callback(update, context, short_id)
    else:
        await query.answer()


async def _send_post_answer_result(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, thread_id, lesson_dir: str,
    question_id: str, esito_text: str, state_dir: str,
) -> None:
    """Manda il testo dell'esito con la tastiera post-risposta (⏭️ prossima / 📖 unità /
    🔊 audio), SENZA avanzare automaticamente: l'avanzamento avviene solo al click di ⏭️
    (vedi _handle_post_answer_callback). Centralizzata perché usata da ogni punto che
    conclude una domanda di recall (poll, 'non lo so', risposta testuale, risposta vocale)."""
    from rt.telegram import formatting as tg_fmt
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="recall_post_answer", state_dir=state_dir,
        message_thread_id=thread_id, extra={"question_id": question_id},
    )
    keyboard = tg_fmt.build_post_answer_keyboard(short_id)
    await _send_with_retry(lambda: context.bot.send_message(
        chat_id=chat_id, text=esito_text, reply_markup=keyboard, message_thread_id=thread_id,
    ))


async def _handle_recall_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, short_id: str) -> None:
    """'Non lo so' (rivela subito risposta/spiegazione) e 'Skip' (passa oltre senza
    registrare nulla) sulla domanda di recall corrente. Il voto sulla qualità della
    domanda non passa da qui: si vota reagendo al messaggio (handle_message_reaction)."""
    state_dir = context.bot_data["state_dir"]
    entry = registry.resolve_pending(short_id, state_dir)
    if entry is None or entry.get("kind") != "recall_question":
        await update.callback_query.answer("Richiesta scaduta o non valida.", show_alert=True)
        return
    lesson_dir = entry["lesson_dir"]
    question_id = entry["question_id"]
    thread_id = entry.get("message_thread_id")

    loop = asyncio.get_running_loop()

    if action == "rsk":
        await update.callback_query.answer("⏭ Saltato.")
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        from rt.pipeline.recall import skip_recall_question
        await loop.run_in_executor(None, skip_recall_question, lesson_dir, question_id)
        from rt.pipeline.recall_session import send_current_recall_question
        await loop.run_in_executor(None, send_current_recall_question, lesson_dir, None, question_id)
        return

    # rns: "Non lo so" — rivela la risposta/spiegazione, registra un tentativo vuoto.
    # L'unità didattica non viene più allegata automaticamente: è disponibile su richiesta
    # tramite il bottone 📖 della tastiera post-risposta (vedi _send_post_answer_result).
    from rt.pipeline.recall import load_recall_bank, record_recall_answer
    bank = await loop.run_in_executor(None, load_recall_bank, lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None:
        await update.callback_query.answer("Domanda non più disponibile.", show_alert=True)
        return

    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if question.type.value == "quiz":
        poll_message_id = entry.get("poll_message_id")
        if poll_message_id is not None:
            from rt.telegram.config import load_telegram_config, TelegramConfigError
            from rt.telegram.client import stop_poll
            try:
                tg_cfg = load_telegram_config()
                await loop.run_in_executor(None, stop_poll, tg_cfg, poll_message_id)
            except TelegramConfigError:
                pass
            except Exception:
                pass
        await loop.run_in_executor(
            None, record_recall_answer, lesson_dir, question_id, "[Non risposto]", False, question.pregenerated_material, None
        )
        esito = "🤷 Nessuna risposta."
        if question.pregenerated_material:
            esito += f"\n\n{question.pregenerated_material}"
    else:
        from rt.pipeline.recall_session import handle_recall_answer
        evaluation = await loop.run_in_executor(None, handle_recall_answer, lesson_dir, question_id, "[Non lo so]", False)
        esito = evaluation or "🤷 Nessuna risposta."

    await _send_post_answer_result(context, update.effective_chat.id, thread_id, lesson_dir, question_id, esito, state_dir)


async def _handle_post_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, short_id: str) -> None:
    """Bottoni dopo un esito di recall: ⏭️ avanza (rnx — l'UNICO che rimuove la tastiera e fa
    proseguire la sessione: niente più avanzamento automatico), 📖 mostra il testo dell'unità
    (rut) e 🔊 manda il suo audio (rua) — questi due lasciano la tastiera attiva, l'utente può
    ripeterli o passare a ⏭️ quando vuole."""
    state_dir = context.bot_data["state_dir"]
    entry = registry.resolve_pending(short_id, state_dir)
    if entry is None or entry.get("kind") != "recall_post_answer":
        await update.callback_query.answer("Richiesta scaduta o non valida.", show_alert=True)
        return
    lesson_dir = entry["lesson_dir"]
    question_id = entry["question_id"]
    thread_id = entry.get("message_thread_id")
    loop = asyncio.get_running_loop()

    if action == "rnx":
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        from rt.pipeline.recall_session import send_current_recall_question
        await loop.run_in_executor(None, send_current_recall_question, lesson_dir)
        return

    from rt.pipeline.recall import load_recall_bank
    bank = await loop.run_in_executor(None, load_recall_bank, lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None:
        await update.callback_query.answer("Domanda non più disponibile.", show_alert=True)
        return

    if action == "rut":
        await update.callback_query.answer()
        from rt.pipeline.recall_session import format_unit_reference
        text = await loop.run_in_executor(None, format_unit_reference, lesson_dir, question)
        text = text.strip() or "⚠️ Nessun contenuto disponibile per questa unità."
        await _send_with_retry(lambda: context.bot.send_message(
            chat_id=update.effective_chat.id, text=text, message_thread_id=thread_id,
        ))
        return

    # rua: manda l'audio di ciascuna unità della domanda (sendAudio, stile playlist)
    await update.callback_query.answer("🔊 Preparo l'audio...")
    from rt.pipeline.recall_session import send_unit_audio
    try:
        await loop.run_in_executor(None, send_unit_audio, lesson_dir, question, thread_id)
    except Exception as e:
        await _send_with_retry(lambda: context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"⚠️ Impossibile inviare l'audio: {e}", message_thread_id=thread_id,
        ))


async def handle_message_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Voto sulla qualità di una domanda di recall: l'utente reagisce al messaggio della
    domanda (testo mirata/vasta, o il poll nativo per i quiz) con 👍/👎/⚡ invece di
    premere un bottone. Il message_id è mappato a question_id in
    rt.telegram.registry (kind='recall_question_message'), registrato quando la
    domanda viene inviata (vedi send_current_recall_question)."""
    reaction_update = update.message_reaction
    if reaction_update is None or not reaction_update.new_reaction:
        return

    state_dir = context.bot_data["state_dir"]
    entry = registry.resolve_pending(str(reaction_update.message_id), state_dir)
    if entry is None or entry.get("kind") != "recall_question_message":
        return
    lesson_dir = entry["lesson_dir"]
    question_id = entry["question_id"]

    last_reaction = reaction_update.new_reaction[-1]
    emoji = getattr(last_reaction, "emoji", None)
    vote = RECALL_REACTION_VOTE_MAP.get(emoji)
    if vote is None:
        return

    from rt.pipeline.recall import load_recall_bank, record_recall_vote, record_fewshot_vote
    loop = asyncio.get_running_loop()
    bank = await loop.run_in_executor(None, load_recall_bank, lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    await loop.run_in_executor(None, record_recall_vote, lesson_dir, question_id, vote)
    if question is not None:
        await loop.run_in_executor(None, record_fewshot_vote, question.type, question.question_text, vote, state_dir)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risposta a un quiz nativo Telegram (sendPoll type=quiz). Il poll_id fa da chiave
    nel registry (vedi rt.telegram.registry.register_with_key), assegnata al momento
    dell'invio in send_current_recall_question."""
    state_dir = context.bot_data["state_dir"]
    poll_answer = update.poll_answer
    if not poll_answer or not poll_answer.option_ids:
        return  # voto ritirato o poll non pertinente

    entry = registry.resolve_pending(poll_answer.poll_id, state_dir)
    if entry is None or entry.get("kind") != "recall_quiz_poll":
        return
    lesson_dir = entry["lesson_dir"]
    question_id = entry["question_id"]
    poll_message_id = entry.get("message_id")
    thread_id = entry.get("message_thread_id")
    idx_choice = poll_answer.option_ids[0]

    from rt.pipeline.recall import load_recall_bank, record_recall_answer

    loop = asyncio.get_running_loop()
    bank = await loop.run_in_executor(None, load_recall_bank, lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None or not question.options or idx_choice >= len(question.options):
        return

    is_correct = (question.correct_index == idx_choice)
    await loop.run_in_executor(
        None, record_recall_answer, lesson_dir, question_id, question.options[idx_choice], False, question.pregenerated_material, None
    )

    from rt.telegram.config import load_telegram_config, TelegramConfigError
    from rt.telegram.client import stop_poll
    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError:
        return

    if poll_message_id is not None:
        try:
            await loop.run_in_executor(None, stop_poll, tg_cfg, poll_message_id)
        except Exception:
            pass

    esito_msg = "✔ Corretto!" if is_correct else "❌ Sbagliato."
    if question.pregenerated_material:
        esito_msg += f"\n\n{question.pregenerated_material}"
    await _send_post_answer_result(context, tg_cfg.chat_id, thread_id, lesson_dir, question_id, esito_msg, state_dir)


async def _handle_outline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, prefix: str, short_id: str) -> None:
    query = update.callback_query
    state_dir = context.bot_data["state_dir"]
    action = prefix[2:]

    entry = registry.resolve_pending(short_id, state_dir)
    if entry is None:
        await query.answer("Richiesta scaduta o non valida.", show_alert=True)
        return
    lesson_dir = entry["lesson_dir"]

    state = tg_pending.load_pending(lesson_dir)
    if state is None or state.short_id != short_id or state.status != "pending":
        await query.answer("Questa richiesta non è più valida (outline già aggiornata).", show_alert=True)
        return

    if action == "appr":
        tg_pending.mark_responded(lesson_dir, status="approved", responded_via="telegram")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.answer("Outline approvata ✅")
    elif action == "edit":
        convo.set_awaiting_feedback(state_dir, chat_id=update.effective_chat.id, short_id=short_id, lesson_dir=lesson_dir)
        try:
            await query.answer()
        except Exception:
            pass
        await _send_with_retry(lambda: context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Scrivi il tuo feedback in un messaggio di testo per rigenerare l'outline.",
            message_thread_id=update.effective_message.message_thread_id,
        ))


async def _handle_issue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, short_id: str) -> None:
    state_dir = context.bot_data["state_dir"]
    entry = registry.resolve_pending(short_id, state_dir)
    if entry is None or entry.get("kind") != "issue_review":
        await update.callback_query.answer("Richiesta scaduta o non valida.", show_alert=True)
        return
    lesson_dir = entry["lesson_dir"]
    issue_id = entry["issue_id"]
    issue_type = entry["issue_type"]

    if action == "iq":
        try:
            await update.callback_query.answer("Revisione interrotta.")
        except Exception:
            pass
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _send_with_retry(lambda: context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⏹ Revisione interrotta. I progressi finora sono stati salvati.",
            message_thread_id=update.effective_message.message_thread_id,
        ))
        tg_session.end_session(state_dir, update.effective_chat.id, update.effective_message.message_thread_id)
        return

    if action == "ib":
        from rt.telegram import issue_queue as tg_queue
        from rt.pipeline.ledger import revert_last_decision
        from rt.pipeline.issue_review import send_current_issue

        queue = tg_queue.load_queue(lesson_dir)
        if queue is None or queue.current_index <= 0:
            await update.callback_query.answer("Sei già alla prima issue.", show_alert=True)
            return

        queue.current_index -= 1
        tg_queue._save(queue, lesson_dir)

        prev_issue_id = queue.issue_ids[queue.current_index]
        revert_last_decision(lesson_dir, prev_issue_id)

        await update.callback_query.answer("◀️ Tornato alla issue precedente.")
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send_current_issue, lesson_dir)
        return

    if action == "ie":
        convo.set_awaiting_feedback(
            state_dir, chat_id=update.effective_chat.id, short_id=short_id, lesson_dir=lesson_dir,
            kind="issue_edit", extra={"issue_id": issue_id, "issue_type": issue_type}
        )
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        await _send_with_retry(lambda: context.bot.send_message(
            chat_id=update.effective_chat.id, text="Scrivi il testo corretto.",
            message_thread_id=update.effective_message.message_thread_id,
        ))
        return

    if action == "is":
        await update.callback_query.answer("Saltata.")
    else:
        from rt.pipeline.ledger import (
            record_decision, find_asr_issue_by_id, find_science_issue_by_id,
            resolve_asr_accept_text, resolve_asr_reject_text,
            resolve_science_accept_text, resolve_science_reject_text,
        )
        if issue_type == "asr":
            issue = find_asr_issue_by_id(lesson_dir, issue_id)
            resolved = resolve_asr_accept_text(issue) if action == "ia" else resolve_asr_reject_text(issue)
        else:
            issue = find_science_issue_by_id(lesson_dir, issue_id)
            resolved = resolve_science_accept_text(issue) if action == "ia" else resolve_science_reject_text(issue)
        record_decision(lesson_dir, issue_id, "accepted" if action == "ia" else "rejected", resolved_text=resolved)
        await update.callback_query.answer("✔ Registrato." if action == "ia" else "Registrato (mantenuto originale).")

    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    from rt.telegram import issue_queue as tg_queue
    from rt.pipeline.issue_review import send_current_issue
    tg_queue.advance(lesson_dir)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, send_current_issue, lesson_dir)


async def _handle_start_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, short_id: str) -> None:
    state_dir = context.bot_data["state_dir"]
    entry = registry.resolve_pending(short_id, state_dir)
    if entry is None:
        await update.callback_query.answer("Richiesta scaduta.", show_alert=True)
        return
    lesson_dir = entry["lesson_dir"]
    await update.callback_query.answer("Avvio la review...")
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    from rt.pipeline.ledger import get_pending_issues
    from rt.pipeline.issue_review import start_review_via_telegram
    asr_to_review, sci_to_review = get_pending_issues(lesson_dir)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_review_via_telegram, lesson_dir, asr_to_review, sci_to_review)


async def _handle_recall_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_dir: str) -> None:
    """Testo libero ricevuto mentre una sessione di recall è attiva sul topic: trattalo come
    risposta alla domanda corrente (mirata/vasta). I quiz si rispondono con i bottoni."""
    state_dir = context.bot_data["state_dir"]
    thread_id = update.effective_message.message_thread_id if update.effective_message else None
    from rt.pipeline.recall_session import load_recall_session_state, handle_recall_answer

    session_state = load_recall_session_state(lesson_dir)
    question_id = session_state.get("current_question_id")
    if not question_id:
        return

    loop = asyncio.get_running_loop()
    evaluation = await loop.run_in_executor(None, handle_recall_answer, lesson_dir, question_id, update.message.text, False)
    if evaluation is None:
        await _send_with_retry(lambda: update.message.reply_text(
            "Nessuna domanda mirata/vasta in attesa di risposta (i quiz si rispondono con i bottoni).",
            message_thread_id=thread_id,
        ))
        return

    await _send_post_answer_result(context, update.effective_chat.id, thread_id, lesson_dir, question_id, evaluation, state_dir)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Risposta vocale a una domanda di recall: scarica, trascrive con MacWhisper, valuta."""
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message else None

    active = tg_session.get_active_session(state_dir, chat_id, thread_id)
    if active is None or active.get("kind") != "recall":
        return
    lesson_dir = active["lesson_dir"]

    from rt.pipeline.recall_session import load_recall_session_state, handle_recall_answer
    from rt.pipeline.recall import load_recall_bank
    from rt.core.models import RecallQuestionType

    session_state = load_recall_session_state(lesson_dir)
    question_id = session_state.get("current_question_id")
    if not question_id:
        return

    loop = asyncio.get_running_loop()
    bank = await loop.run_in_executor(None, load_recall_bank, lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None:
        return
    if question.type == RecallQuestionType.QUIZ:
        await _send_with_retry(lambda: update.message.reply_text(
            "I quiz si rispondono con i bottoni, non con un vocale.",
            message_thread_id=thread_id,
        ))
        return

    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".oga")
    os.close(tmp_fd)
    try:
        from rt.telegram.config import load_telegram_config
        from rt.telegram.client import download_voice
        from rt.core.recall_stt import transcribe_voice_answer
        from rt.core.config import load_config

        tg_cfg = load_telegram_config()
        stt_engine = load_config().telegram.recall.stt_engine
        file_id = update.message.voice.file_id

        await loop.run_in_executor(None, download_voice, tg_cfg, file_id, tmp_path)

        try:
            answer_text = await loop.run_in_executor(None, transcribe_voice_answer, tmp_path, stt_engine)
        except Exception as e:
            await _send_with_retry(lambda: update.message.reply_text(
                f"⚠️ Trascrizione non riuscita: {e}. Riprova a voce o rispondi a testo.",
                message_thread_id=thread_id,
            ))
            return

        if not answer_text:
            await _send_with_retry(lambda: update.message.reply_text(
                "⚠️ Non ho capito nulla dal vocale, riprova.",
                message_thread_id=thread_id,
            ))
            return

        evaluation = await loop.run_in_executor(None, handle_recall_answer, lesson_dir, question_id, answer_text, True)
        if evaluation is None:
            return
        esito = f"🗣 Trascritto: \"{answer_text}\"\n\n{evaluation}"
        await _send_post_answer_result(context, chat_id, thread_id, lesson_dir, question_id, esito, state_dir)
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message else None
    awaiting = convo.get_awaiting_feedback(state_dir, chat_id)

    if awaiting is None:
        active = tg_session.get_active_session(state_dir, chat_id, thread_id)
        if active is not None and active.get("kind") == "recall":
            await _handle_recall_text_answer(update, context, active["lesson_dir"])
        return

    kind = awaiting.get("kind", "outline_feedback")
    lesson_dir = awaiting["lesson_dir"]

    if kind == "issue_edit":
        issue_id = awaiting["extra"]["issue_id"]
        from rt.pipeline.ledger import record_decision
        record_decision(lesson_dir, issue_id, "edited", resolved_text=update.message.text)
        convo.clear_awaiting_feedback(state_dir, chat_id)
        await _send_with_retry(lambda: update.message.reply_text(
            "✏️ Modifica registrata.",
            message_thread_id=update.effective_message.message_thread_id,
        ))
        from rt.telegram import issue_queue as tg_queue
        from rt.pipeline.issue_review import send_current_issue
        tg_queue.advance(lesson_dir)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send_current_issue, lesson_dir)
        return

    # kind == "outline_feedback": feedback per rigenerazione outline
    short_id = awaiting["short_id"]
    state = tg_pending.load_pending(lesson_dir)
    if state is None or state.short_id != short_id or state.status != "pending":
        await _send_with_retry(lambda: update.message.reply_text(
            "Questa richiesta non è più valida.",
            message_thread_id=update.effective_message.message_thread_id,
        ))
        convo.clear_awaiting_feedback(state_dir, chat_id)
        return

    tg_pending.mark_responded(lesson_dir, status="changes_requested", feedback_text=update.message.text, responded_via="telegram")
    convo.clear_awaiting_feedback(state_dir, chat_id)
    await _send_with_retry(lambda: update.message.reply_text(
        "Feedback ricevuto, l'outline verrà rigenerata a breve.",
        message_thread_id=update.effective_message.message_thread_id,
    ))


def run_daemon(state_dir: str = None) -> None:
    cfg = load_telegram_config()
    runtime_cfg = load_config().telegram
    resolved_state_dir = state_dir or runtime_cfg.state_dir

    application = Application.builder().token(cfg.bot_token).build()
    application.bot_data["state_dir"] = resolved_state_dir

    application.add_handler(CommandHandler("quit", handle_quit))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(CommandHandler("stile", handle_stile))
    application.add_handler(CommandHandler("recall", handle_recall_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    application.add_handler(MessageReactionHandler(handle_message_reaction))
    application.job_queue.run_repeating(_write_heartbeat, interval=15, first=0)

    print(f"🤖 RT Telegram daemon in ascolto (state_dir='{resolved_state_dir}')...", file=sys.stderr)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
