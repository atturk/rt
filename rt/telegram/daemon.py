"""
rt.telegram.daemon
Processo persistente in polling: unico componente che riceve bottoni cliccati e
messaggi di feedback. Risolve short_id -> lesson_dir tramite rt.telegram.registry
e scrive le risposte in telegram_pending.json tramite rt.telegram.pending.
"""
import os
import re
import sys
import json
import time
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, ContextTypes, filters

from rt.core.config import load_config
from rt.telegram.config import load_telegram_config
from rt.telegram import registry, pending as tg_pending, conversation_state as convo

CALLBACK_PATTERN = re.compile(r"^rt(appr|edit):(.+)$")


def _heartbeat_path(state_dir: str) -> str:
    return os.path.join(state_dir, "daemon_heartbeat.json")


async def _write_heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    os.makedirs(state_dir, exist_ok=True)
    tmp_path = _heartbeat_path(state_dir) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"last_seen": datetime.now().isoformat()}, f)
    os.replace(tmp_path, _heartbeat_path(state_dir))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    state_dir = context.bot_data["state_dir"]
    m = CALLBACK_PATTERN.match(query.data or "")
    if not m:
        await query.answer()
        return
    action, short_id = m.group(1), m.group(2)

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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_dir = context.bot_data["state_dir"]
    chat_id = update.effective_chat.id
    awaiting = convo.get_awaiting_feedback(state_dir, chat_id)
    if awaiting is None:
        return  # nessuna richiesta di feedback in sospeso per questa chat, ignora

    lesson_dir = awaiting["lesson_dir"]
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

    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.job_queue.run_repeating(_write_heartbeat, interval=15, first=0)

    print(f"🤖 RT Telegram daemon in ascolto (state_dir='{resolved_state_dir}')...", file=sys.stderr)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
