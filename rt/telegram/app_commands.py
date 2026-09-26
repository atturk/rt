"""
rt.telegram.app_commands
Richieste della web app al bot (tabella telegram_commands, vedi rt.services.recall_sessions):
avviare una sessione di recall nel topic della materia o interromperla. Il daemon le esegue
con process_pending_commands() a intervalli regolari e ne scrive l'esito.
"""
from typing import Optional

from rt.services import recall_sessions


def _start_recall(cmd: recall_sessions.Command, force_mock: bool) -> Optional[str]:
    from rt.core.config import load_config
    from rt.telegram import recall_preferences
    from rt.telegram.recall_channel import start_recall_via_telegram
    qtype = cmd.payload.get("qtype") or recall_preferences.DEFAULT_STYLE
    if qtype not in recall_preferences.VALID_STYLES:
        return f"Tipo di domanda non valido: {qtype}."
    recall_preferences.set_active_style(load_config().telegram.state_dir, qtype)
    return start_recall_via_telegram(cmd.lesson_path, "alternato", None,
                                     bool(cmd.payload.get("mock")) or force_mock)


def _stop_recall(cmd: recall_sessions.Command) -> Optional[str]:
    """Chiude la sessione nel topic (come /quit) e lo scrive nel topic."""
    import os
    from rt.core.config import load_config
    from rt.telegram import client as tg_client, conversation_state as convo, session as tg_session
    from rt.telegram.config import TelegramConfigError, load_telegram_config
    state_dir = load_config().telegram.state_dir
    chat_id = cmd.payload.get("chat_id")
    raw_thread = cmd.payload.get("thread_id")
    thread_id = int(raw_thread) if raw_thread not in (None, "") else None
    active = tg_session.get_active_session(state_dir, chat_id, thread_id)
    if active is None or active.get("kind") != "recall" or \
            os.path.realpath(active.get("lesson_dir") or "") != os.path.realpath(cmd.lesson_path or ""):
        return None  # già chiusa da Telegram: niente da fare
    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError:
        tg_cfg = None
    if tg_cfg is not None and active.get("message_id") is not None:
        try:
            tg_client.edit_message_reply_markup(tg_cfg, int(active["message_id"]), None)
        except Exception:
            pass
    convo.clear_awaiting_feedback(state_dir, chat_id)
    tg_session.end_session(state_dir, chat_id, thread_id, ended_by="app")
    if tg_cfg is None:
        return "Il bot Telegram non è configurato: sessione chiusa senza avviso nel topic."
    tg_client.send_message(tg_cfg, text=recall_sessions.INTERRUPTED_MESSAGE, message_thread_id=thread_id)
    return None


def process_pending_commands(force_mock: bool = False) -> int:
    """Esegue i comandi in attesa, in ordine. force_mock: domande generate in mock (bot finto
    dei test end-to-end). Restituisce quanti comandi ha eseguito."""
    done = 0
    while True:
        cmd = recall_sessions.claim_next_command()
        if cmd is None:
            return done
        try:
            if cmd.kind == recall_sessions.START_RECALL:
                error = _start_recall(cmd, force_mock)
            elif cmd.kind == recall_sessions.STOP_RECALL:
                error = _stop_recall(cmd)
            else:
                error = f"Richiesta sconosciuta: {cmd.kind}."
        except Exception as exc:  # l'esito va nel registro, il bot resta in piedi
            error = str(exc) or exc.__class__.__name__
        recall_sessions.finish_command(cmd.id, error)
        done += 1
