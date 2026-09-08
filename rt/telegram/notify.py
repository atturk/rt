"""
rt.telegram.notify
Notifiche one-shot che non devono mai far fallire la pipeline chiamante.
"""
import sys
from typing import Dict, Any


def notify_build_completed(lesson_dir: str, build_result: Dict[str, Any], lesson_title: str) -> None:
    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id
        from rt.telegram.client import send_message
        from rt.telegram.formatting import escape_html
        from rt.core.config import load_config

        cfg = load_telegram_config()
        topics = load_config().telegram.topics
        message_thread_id = resolve_topic_id(lesson_dir, topics)
        text = (
            f"✅ <b>Build completata</b>\n"
            f"{escape_html(lesson_title)}\n"
            f"📄 {escape_html(str(build_result.get('rielaborato', '')))}"
        )
        send_message(cfg, text=text, message_thread_id=message_thread_id)
    except Exception as e:
        print(f"⚠️  Notifica Telegram di build non inviata: {e}", file=sys.stderr)


def notify_issues_ready(lesson_dir: str, issue_type: str, count: int) -> None:
    """issue_type: 'asr' | 'science'. Fire-and-forget: non deve mai bloccare né
    far fallire il comando chiamante. Non-op se count == 0 (nulla da notificare)."""
    if count <= 0:
        return
    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id
        from rt.telegram import client as tg_client, registry as tg_registry, formatting as tg_fmt
        from rt.core.config import load_config

        cfg = load_telegram_config()
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)
        label = "ASR" if issue_type == "asr" else "scientifiche"
        short_id = tg_registry.register_pending(
            lesson_dir, round_=1, kind="start_issue_review", state_dir=runtime_cfg.state_dir, message_thread_id=thread_id
        )
        keyboard = tg_fmt.build_start_review_keyboard(short_id)
        tg_client.send_message(cfg, text=f"🔎 {count} issue {label} pronte per la review.", reply_markup=keyboard, message_thread_id=thread_id)
    except Exception as e:
        print(f"⚠️  Notifica Telegram issue pronte non inviata: {e}", file=sys.stderr)

