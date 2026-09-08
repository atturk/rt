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
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, CommandHandler, ContextTypes, filters

from rt.core.config import load_config
from rt.telegram.config import load_telegram_config
from rt.telegram import registry, pending as tg_pending, conversation_state as convo, session as tg_session

ISSUE_ACTIONS = {"ia", "ir", "ie", "is", "iq"}


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
        await update.effective_message.reply_text(
            "Nessuna attività in corso in questo topic.",
            message_thread_id=thread_id,
        )
        return

    kind = active.get("kind")
    lesson_dir = active.get("lesson_dir")

    convo.clear_awaiting_feedback(state_dir, chat_id)
    tg_session.end_session(state_dir, chat_id, thread_id)

    if kind == "issue_review":
        await update.effective_message.reply_text(
            "⏹ Revisione interrotta. I progressi finora sono stati salvati.",
            message_thread_id=thread_id,
        )
    elif kind == "outline_confirmation":
        if lesson_dir and os.path.exists(lesson_dir):
            try:
                tg_pending.mark_responded(lesson_dir, status="cancelled", responded_via="telegram")
            except Exception:
                pass
        await update.effective_message.reply_text(
            "⏹ Conferma outline annullata.",
            message_thread_id=thread_id,
        )
    else:
        await update.effective_message.reply_text(
            "⏹ Attività interrotta.",
            message_thread_id=thread_id,
        )


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id if update.effective_message else None

    active = tg_session.get_active_session(state_dir, chat_id, thread_id)
    if active is None:
        await update.effective_message.reply_text(
            "Nessuna attività in corso in questo topic.",
            message_thread_id=thread_id,
        )
        return

    kind = active.get("kind", "sconosciuto")
    lesson_dir = active.get("lesson_dir", "")
    folder_name = os.path.basename(os.path.normpath(lesson_dir)) if lesson_dir else "N/D"

    await update.effective_message.reply_text(
        f"Attività in corso: {kind} ({folder_name})",
        message_thread_id=thread_id,
    )


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
    else:
        await query.answer()


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
        await query.answer()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Scrivi il tuo feedback in un messaggio di testo per rigenerare l'outline.",
            message_thread_id=update.effective_message.message_thread_id,
        )


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
        await update.callback_query.answer("Revisione interrotta.")
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⏹ Revisione interrotta. I progressi finora sono stati salvati.",
            message_thread_id=update.effective_message.message_thread_id,
        )
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
        await update.callback_query.answer()
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Scrivi il testo corretto.",
            message_thread_id=update.effective_message.message_thread_id,
        )
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

    tg_session.start_session(state_dir, update.effective_chat.id, update.effective_message.message_thread_id, "issue_review", lesson_dir)

    from rt.pipeline.ledger import get_pending_issues
    from rt.pipeline.issue_review import start_review_via_telegram
    asr_to_review, sci_to_review = get_pending_issues(lesson_dir)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_review_via_telegram, lesson_dir, asr_to_review, sci_to_review)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    awaiting = convo.get_awaiting_feedback(state_dir, chat_id)
    if awaiting is None:
        return
    kind = awaiting.get("kind", "outline_feedback")
    lesson_dir = awaiting["lesson_dir"]

    if kind == "issue_edit":
        issue_id = awaiting["extra"]["issue_id"]
        from rt.pipeline.ledger import record_decision
        record_decision(lesson_dir, issue_id, "edited", resolved_text=update.message.text)
        convo.clear_awaiting_feedback(state_dir, chat_id)
        await update.message.reply_text("✏️ Modifica registrata.", message_thread_id=update.effective_message.message_thread_id)
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
        await update.message.reply_text(
            "Questa richiesta non è più valida.",
            message_thread_id=update.effective_message.message_thread_id,
        )
        convo.clear_awaiting_feedback(state_dir, chat_id)
        return

    tg_pending.mark_responded(lesson_dir, status="changes_requested", feedback_text=update.message.text, responded_via="telegram")
    convo.clear_awaiting_feedback(state_dir, chat_id)
    await update.message.reply_text(
        "Feedback ricevuto, l'outline verrà rigenerata a breve.",
        message_thread_id=update.effective_message.message_thread_id,
    )


def run_daemon(state_dir: str = None) -> None:
    cfg = load_telegram_config()
    runtime_cfg = load_config().telegram
    resolved_state_dir = state_dir or runtime_cfg.state_dir

    application = Application.builder().token(cfg.bot_token).build()
    application.bot_data["state_dir"] = resolved_state_dir

    application.add_handler(CommandHandler("quit", handle_quit))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.job_queue.run_repeating(_write_heartbeat, interval=15, first=0)

    print(f"🤖 RT Telegram daemon in ascolto (state_dir='{resolved_state_dir}')...", file=sys.stderr)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
