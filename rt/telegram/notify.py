"""
rt.telegram.notify
Notifiche one-shot che non devono mai far fallire la pipeline chiamante.
"""
import sys
from typing import Dict, Any


def notify_build_completed(lesson_dir: str, build_result: Dict[str, Any], lesson_title: str) -> None:
    try:
        from rt.telegram.config import load_telegram_config
        from rt.telegram.client import send_message
        from rt.telegram.formatting import escape_html

        cfg = load_telegram_config()
        text = (
            f"✅ <b>Build completata</b>\n"
            f"{escape_html(lesson_title)}\n"
            f"📄 {escape_html(str(build_result.get('rielaborato', '')))}"
        )
        send_message(cfg, text=text)
    except Exception as e:
        print(f"⚠️  Notifica Telegram di build non inviata: {e}", file=sys.stderr)
