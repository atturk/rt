"""
rt.telegram.notify
Notifiche one-shot che non devono mai far fallire la pipeline chiamante.
"""
import sys
from typing import Dict, Any


def notify_build_completed(lesson_dir: str, build_result: Dict[str, Any], lesson_title: str) -> None:
    from rt.telegram.config import load_telegram_config, resolve_topic_id, TelegramConfigError
    from rt.telegram.client import send_message
    from rt.telegram.formatting import escape_html
    from rt.core.config import load_config

    try:
        cfg = load_telegram_config()
    except TelegramConfigError:
        return

    try:
        runtime_cfg = load_config().telegram
        message_thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)
        text = (
            f"✅ <b>Build completata</b>\n"
            f"{escape_html(lesson_title)}\n"
            f"📄 {escape_html(str(build_result.get('rielaborato', '')))}"
        )
        send_message(cfg, text=text, message_thread_id=message_thread_id)

        from rt.telegram.last_lesson import record_last_lesson
        record_last_lesson(runtime_cfg.state_dir, cfg.chat_id, message_thread_id, lesson_dir)
    except Exception as e:
        print(f"⚠️  Notifica Telegram di build non inviata: {e}", file=sys.stderr)


def notify_issues_ready(lesson_dir: str, issue_type: str, count: int) -> None:
    """issue_type: 'asr' | 'science'. Fire-and-forget: non deve mai bloccare né
    far fallire il comando chiamante. Se count == 0 manda un messaggio di conferma senza bottoni."""
    import os
    from rt.telegram.config import load_telegram_config, resolve_topic_id, TelegramConfigError
    from rt.telegram import client as tg_client, registry as tg_registry, formatting as tg_fmt, session as tg_session
    from rt.core.config import load_config

    try:
        cfg = load_telegram_config()
    except TelegramConfigError:
        return

    try:
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)
        label = "ASR" if issue_type == "asr" else "scientifiche"

        if count <= 0:
            tg_client.send_message(
                cfg,
                text=f"✅ Nessuna issue {label} trovata.",
                message_thread_id=thread_id,
            )
            return

        active = tg_session.get_active_session(runtime_cfg.state_dir, cfg.chat_id, thread_id)
        if active is not None:
            if active.get("kind") != "issue_review" or os.path.abspath(active.get("lesson_dir", "")) != os.path.abspath(lesson_dir):
                busy_msg = f"C'è già un'attività in corso in questo topic ({active.get('kind')}). Usa /quit per chiuderla prima."
                tg_client.send_message(cfg, text=busy_msg, message_thread_id=thread_id)
                return
            else:
                tg_client.send_message(
                    cfg,
                    text="ℹ️ Review già pronta per questo topic. Clicca su 'Inizia review' nel messaggio precedente, oppure usa /quit per annullare.",
                    message_thread_id=thread_id,
                )
                return

        tg_session.start_session(runtime_cfg.state_dir, cfg.chat_id, thread_id, "issue_review", lesson_dir)
        short_id = tg_registry.register_pending(
            lesson_dir, round_=1, kind="start_issue_review", state_dir=runtime_cfg.state_dir, message_thread_id=thread_id
        )
        keyboard = tg_fmt.build_start_review_keyboard(short_id)
        res = tg_client.send_message(
            cfg,
            text=f"🔎 {count} issue {label} pronte per la review.",
            reply_markup=keyboard,
            message_thread_id=thread_id
        )
        msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
        if msg_id is not None:
            tg_session.update_session_message(runtime_cfg.state_dir, cfg.chat_id, thread_id, msg_id)
    except Exception as e:
        print(f"⚠️  Notifica Telegram issue pronte non inviata: {e}", file=sys.stderr)


