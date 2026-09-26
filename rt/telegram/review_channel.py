"""
rt.telegram.review_channel
Invio sequenziale delle issue scientifiche via Telegram e avanzamento della coda dopo ogni
decisione (implementazione Telegram della porta ReviewChannel di
rt.services.review_service). Non blocca mai il chiamante: avvia la coda, manda la prima
issue, ritorna. Il resto della coda viene avanzato dal daemon dopo ogni click/risposta
(vedi rt/telegram/daemon.py).
"""
import os
from typing import List, Optional, Sequence

from rt.core.audio_clip import resolve_audio_path, cut_clip
from rt.core.lesson_paths import lesson_path
from rt.core.models import ScienceIssue
from rt.services.review_service import issue_context
from rt.telegram import issue_queue as tg_queue
from rt.storage import fs


def start_review_via_telegram(
    lesson_dir: str,
    asr_to_review: Optional[List] = None,
    sci_to_review: Optional[List[ScienceIssue]] = None
) -> None:
    if sci_to_review is None and isinstance(asr_to_review, list):
        sci_to_review = asr_to_review
    sci_to_review = sci_to_review or []

    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id, TelegramConfigError
        from rt.telegram import client as tg_client, session as tg_session
        from rt.core.config import load_config

        tg_cfg = load_telegram_config()
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)

        active = tg_session.get_active_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id)
        if active is not None:
            if active.get("kind") != "issue_review" or os.path.abspath(active.get("lesson_dir", "")) != os.path.abspath(lesson_dir):
                busy_msg = f"C'è già un'attività in corso in questo topic ({active.get('kind')}). Usa /quit per chiuderla prima."
                tg_client.send_message(tg_cfg, text=busy_msg, message_thread_id=thread_id)
                print(f"⚠️  {busy_msg}")
                return
            else:
                reminder_msg = "ℹ️ Review già in corso per questa lezione su questo topic. Continua dal messaggio precedente, oppure usa /quit per annullarla."
                tg_client.send_message(tg_cfg, text=reminder_msg, message_thread_id=thread_id)
                print(f"ℹ️  {reminder_msg}")
                return

        tg_session.start_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id, "issue_review", lesson_dir)
    except TelegramConfigError:
        print("⚠️  Telegram non configurato: impossibile inviare l'issue. Usa 'rt review \"<cartella>\"' da terminale.")
        return
    except Exception as e:
        print(f"⚠️  Impossibile avviare la sessione Telegram: {e}")
        return

    issue_ids = [iss.id for iss in sci_to_review]
    issue_types = {iss.id: "science" for iss in sci_to_review}
    tg_queue.create_queue(lesson_dir, issue_ids=issue_ids, issue_types=issue_types)
    print(f"📤 {len(issue_ids)} issue in coda per la review su Telegram.")
    send_current_issue(lesson_dir)
    print("   Continua la review dal telefono quando vuoi. Esegui 'rt build \"<cartella>\"' una volta finita.")


def send_current_issue(lesson_dir: str) -> None:
    """Invia l'issue corrente della coda (se resta). Chiamata sia dal trigger
    iniziale sia dal daemon dopo ogni decisione/salto. Esegue I/O bloccante
    (rete + disco): il chiamante asincrono (daemon.py) deve invocarla dentro
    un executor, mai direttamente nell'event loop."""
    from rt.telegram.config import load_telegram_config, TelegramConfigError, resolve_topic_id
    from rt.telegram import client as tg_client, registry as tg_registry, formatting as tg_fmt
    from rt.core.config import load_config
    from rt.core.state import transition_to, WorkflowState
    from rt.pipeline.ledger import find_science_issue_by_id

    queue = tg_queue.load_queue(lesson_dir)
    if queue is None:
        return

    if queue.current_index >= len(queue.issue_ids):
        try:
            tg_cfg = load_telegram_config()
            runtime_cfg = load_config().telegram
            thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)
            from rt.telegram import session as tg_session
            tg_session.end_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id)
            tg_client.send_message(tg_cfg, text="✨ Review completata. Esegui 'rt build' quando vuoi.", message_thread_id=thread_id)
        except TelegramConfigError:
            pass
        except Exception:
            pass
        yaml_path = lesson_path(lesson_dir, "info.yaml")
        if fs.isfile(yaml_path):
            try:
                transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
            except Exception:
                pass
        return

    issue_id = queue.issue_ids[queue.current_index]
    issue_type = queue.issue_types[issue_id]
    issue = find_science_issue_by_id(lesson_dir, issue_id)
    if issue is None:
        # issue non più trovata (caso limite, es. rigenerata nel frattempo): salta.
        tg_queue.advance(lesson_dir)
        return send_current_issue(lesson_dir)

    ctx = issue_context(lesson_dir, issue)
    text = tg_fmt.render_science_issue_text(issue, ctx["unit_info"], ctx["timecode"])

    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError:
        print(f"⚠️  Telegram non configurato: impossibile inviare l'issue. Usa 'rt review \"<cartella>\"' da terminale.")
        return

    runtime_cfg = load_config().telegram
    thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)
    short_id = tg_registry.register_pending(
        lesson_dir, round_=queue.current_index, kind="issue_review", state_dir=runtime_cfg.state_dir,
        message_thread_id=thread_id, extra={"issue_id": issue_id, "issue_type": issue_type}
    )
    keyboard = tg_fmt.build_issue_keyboard(short_id, issue_type)
    try:
        res = tg_client.send_message(tg_cfg, text=text, reply_markup=keyboard, message_thread_id=thread_id)
        msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
        if msg_id is not None:
            from rt.telegram import session as tg_session
            tg_session.update_session_message(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id, msg_id)
    except tg_client.TelegramAPIError as e:
        print(f"⚠️  Invio issue a Telegram fallito: {e}")

    # Invio / Deduplica clip audio
    audio_path = resolve_audio_path(lesson_dir)
    start_seg = ctx.get("start_segment_id")
    end_seg = ctx.get("end_segment_id")
    start_s = ctx.get("start_s")
    end_s = ctx.get("end_s")

    if audio_path and start_seg and end_seg and start_s is not None and end_s is not None:
        from rt.telegram.audio_sent import get_sent_audio, record_sent_audio
        sent = get_sent_audio(lesson_dir, start_seg, end_seg)
        if sent and "message_id" in sent:
            try:
                tg_client.send_message(
                    tg_cfg,
                    text="🔊 Audio già inviato qui sopra ⬆️ per questa unità.",
                    reply_to_message_id=sent["message_id"],
                    message_thread_id=thread_id,
                )
            except Exception as e:
                print(f"⚠️  Invio reply audio a Telegram fallito: {e}")
        else:
            tmp_clip = None
            try:
                tmp_clip = cut_clip(audio_path, start_s, end_s)
                caption = f"🎧 Audio {issue_type.upper()}: {issue_id}"
                voice_res = tg_client.send_voice(
                    tg_cfg,
                    voice_path=tmp_clip,
                    caption=caption,
                    message_thread_id=thread_id,
                )
                v_msg_id = voice_res.get("message_id") if isinstance(voice_res, dict) else getattr(voice_res, "message_id", None)
                if v_msg_id is not None:
                    record_sent_audio(lesson_dir, start_seg, end_seg, v_msg_id)
            except Exception as e:
                print(f"⚠️  Invio clip audio a Telegram fallito: {e}")
            finally:
                if tmp_clip and fs.exists(tmp_clip):
                    try:
                        fs.remove(tmp_clip)
                    except Exception:
                        pass


class TelegramReviewChannel:
    """ReviewChannel su Telegram."""

    def start_review(self, lesson_dir: str, issues: Sequence[ScienceIssue]) -> None:
        start_review_via_telegram(lesson_dir, sci_to_review=list(issues))

    def send_current_issue(self, lesson_dir: str) -> None:
        send_current_issue(lesson_dir)
