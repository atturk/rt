"""
rt.telegram.notify_log
Registro delle ultime notifiche inviate al gruppo (RT4-FA6): lezione pronta, issue da
rivedere, messaggi di prova dei topic. Un file JSONL nella cartella di stato Telegram, con le
ultime MAX_ENTRIES righe; la pagina Bot Telegram lo legge da GET /telegram/notifications.
Registrare non deve mai far fallire l'invio: gli errori si ignorano. Nessun token nel file.
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

FILE_NAME = "notifications.jsonl"
MAX_ENTRIES = 50
_lock = threading.Lock()


def _path(state_dir: Optional[str] = None) -> str:
    if state_dir is None:
        from rt.core.config import load_config
        state_dir = load_config().telegram.state_dir
    return os.path.join(state_dir, FILE_NAME)


def _plain(text: str) -> str:
    """Testo leggibile: niente tag HTML del parse_mode e al massimo 300 caratteri."""
    import html
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()[:300]


def record_notification(kind: str, text: str, topic_id: Optional[int], ok: bool = True,
                        state_dir: Optional[str] = None) -> None:
    try:
        path = _path(state_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entry = {"sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
                 "text": _plain(text), "topic_id": topic_id, "ok": ok}
        with _lock:
            lines: List[str] = []
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    lines = [line for line in f.read().splitlines() if line.strip()]
            lines = (lines + [json.dumps(entry, ensure_ascii=False)])[-MAX_ENTRIES:]
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - il registro non deve mai bloccare una notifica
        pass


def recent_notifications(limit: int = 20, state_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Le ultime notifiche, dalla più recente."""
    path = _path(state_dir)
    if not os.path.isfile(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
    return list(reversed(out))[:limit]
