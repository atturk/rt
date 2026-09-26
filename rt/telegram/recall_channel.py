"""
rt.telegram.recall_channel
Sessione di Active Recall su Telegram: avvio, invio della domanda corrente (chiamato anche
dal daemon dopo ogni voto/risposta/salto) e invio dei clip audio delle unità. La logica di
sessione è in rt.services.recall_service.
"""
import os
import shutil
import sys
from typing import List, Optional

from rt.core.lesson_paths import lesson_path
from rt.core.models import RecallQuestionType
from rt.services import recall_service
from rt.storage import fs


def send_unit_audio(
    lesson_dir: str,
    question,
    message_thread_id: Optional[int] = None,
    reply_to_message_id: Optional[int] = None,
) -> List[int]:
    """Manda via sendAudio (stile 'file musicale', non sendVoice) il clip di ciascuna unità
    didattica della domanda. Il clip viene ritagliato una sola volta e messo in cache in
    <lesson_dir>/recall_audio_clips/<unit_id><ext> (stessa estensione del file audio originale,
    perché cut_clip usa -c copy: rinominare a .mp3 a prescindere sarebbe scorretto per sorgenti
    non-mp3), riusato ai click successivi invece di rigenerarlo. Solleva ValueError con un
    messaggio chiaro se manca il draft, l'audio originale, o la config Telegram."""
    from rt.telegram.config import load_telegram_config, TelegramConfigError
    from rt.telegram.client import send_audio
    from rt.core.audio_clip import resolve_audio_path, cut_clip, resolve_unit_time_range
    from rt.core.segments import load_segments_json
    from rt.pipeline.ledger import load_resolved_draft

    draft = load_resolved_draft(lesson_dir)
    units = [u for u in draft.units if u.unit_id in question.unit_ids]
    if not units:
        raise ValueError("Nessuna unità didattica trovata per questa domanda.")

    audio_path = resolve_audio_path(lesson_dir)
    if not audio_path:
        raise ValueError("Audio originale della lezione non trovato.")

    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError as e:
        raise ValueError(f"Telegram non configurato: {e}")

    segments = load_segments_json(lesson_path(lesson_dir, "segments.json")).segments
    clips_dir = lesson_path(lesson_dir, "recall_audio_clips")
    fs.makedirs(clips_dir, exist_ok=True)
    ext = os.path.splitext(audio_path)[1] or ".mp3"

    sent_msg_ids: List[int] = []
    for u in units:
        clip_path = os.path.join(clips_dir, f"{u.unit_id}{ext}")
        if not fs.isfile(clip_path):
            start_s, end_s = resolve_unit_time_range(u, segments)
            tmp_clip = cut_clip(audio_path, start_s, end_s)
            fs.move(tmp_clip, clip_path)
        res = send_audio(
            tg_cfg,
            fs.real_path(clip_path) or clip_path,
            title=f"{u.unit_id} - {u.title}",
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
        )
        msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
        if isinstance(msg_id, int):
            sent_msg_ids.append(msg_id)
    return sent_msg_ids


def _generate_initial_batch(lesson_dir: str, force_mock: bool) -> None:
    """Generazione del primo batch di domande: tramite la coda se c'è un worker vivo (il
    daemon resta libero), altrimenti in processo come prima."""
    from rt.services.jobs import run_job_or_inline
    run_job_or_inline("recall_generate", lesson_dir, {"force_mock": force_mock},
                      inline=lambda: recall_service.ensure_initial_batch(lesson_dir, force_mock=force_mock),
                      created_by="telegram")


def start_recall_via_telegram(lesson_dir: str, order: str = "alternato", style: Optional[str] = None, force_mock: bool = False) -> Optional[str]:
    """Avvia la sessione nel topic della materia. Restituisce None se la sessione è partita (o
    era già in corso per questa lezione), altrimenti il motivo per cui non è partita."""
    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id, TelegramConfigError
        from rt.telegram import client as tg_client, session as tg_session, recall_preferences
        from rt.core.config import load_config

        tg_cfg = load_telegram_config()
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)

        active = tg_session.get_active_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id)
        if active is not None:
            if active.get("kind") != "recall" or os.path.abspath(active.get("lesson_dir", "")) != os.path.abspath(lesson_dir):
                busy_msg = f"C'è già un'attività in corso in questo topic ({active.get('kind')}). Usa /quit per chiuderla prima."
                tg_client.send_message(tg_cfg, text=busy_msg, message_thread_id=thread_id)
                print(f"⚠️  {busy_msg}")
                return f"C'è già un'altra attività in corso nel topic della materia ({active.get('kind')})."
            else:
                reminder_msg = "ℹ️ Sessione di recall già in corso per questa lezione su questo topic. Continua dal messaggio precedente, oppure usa /quit per annullarla."
                # sessione nata prima del registro condiviso: la web app deve vederla
                tg_session.start_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id, "recall", lesson_dir)
                tg_client.send_message(tg_cfg, text=reminder_msg, message_thread_id=thread_id)
                print(f"ℹ️  {reminder_msg}")
                return None

        tg_session.start_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id, "recall", lesson_dir)
        if style:
            recall_preferences.set_active_style(runtime_cfg.state_dir, style)

        gen_msg = tg_client.send_message(
            tg_cfg,
            text="⏳ Sto generando le domande per il recall, ti avviso appena il primo batch è pronto.",
            message_thread_id=thread_id,
        )
        gen_msg_id = gen_msg.get("message_id") if isinstance(gen_msg, dict) else getattr(gen_msg, "message_id", None)
    except TelegramConfigError:
        print("⚠️  Telegram non configurato: impossibile avviare il recall su Telegram. Usa --channel terminal.")
        return "Il bot Telegram non è configurato."
    except Exception as e:
        print(f"⚠️  Impossibile avviare la sessione Telegram: {e}")
        return f"Impossibile avviare la sessione su Telegram: {e}"

    recall_service.save_recall_session_state(lesson_dir, {"order": order, "unit_cursor": None, "current_question_id": None, "force_mock": force_mock})
    _generate_initial_batch(lesson_dir, force_mock)

    print(f"📤 Sessione di recall avviata su Telegram (ordine: {order}).")
    send_current_recall_question(lesson_dir, force_mock=force_mock)
    print("   Continua dal telefono quando vuoi.")

    if gen_msg_id:
        try:
            tg_client.delete_message(tg_cfg, gen_msg_id)
        except Exception:
            pass
    return None


def send_current_recall_question(lesson_dir: str, force_mock: Optional[bool] = None, exclude_id: Optional[str] = None) -> None:
    """force_mock=None (default) risolve dal flag persistito in telegram_recall_session.json
    (vedi handle_recall_answer): il daemon, chiamando questa funzione dopo ogni risposta/voto/
    rifornimento, deve rispettare il --mock con cui la sessione è stata avviata da terminale.

    exclude_id: se specificato (tipicamente la domanda appena skippata), viene passato a
    get_next_pending_question per evitare di riproporla immediatamente come prossima."""
    from rt.telegram.config import load_telegram_config, TelegramConfigError, resolve_topic_id
    from rt.telegram import client as tg_client, registry as tg_registry, formatting as tg_fmt, session as tg_session, recall_preferences
    from rt.core.config import load_config

    runtime_cfg = load_config().telegram
    state_dir = runtime_cfg.state_dir
    active_style = recall_preferences.get_active_style(state_dir)
    qtype = RecallQuestionType(active_style)

    session_state = recall_service.load_recall_session_state(lesson_dir)
    order = session_state.get("order", "alternato")
    unit_cursor = session_state.get("unit_cursor")
    if force_mock is None:
        force_mock = session_state.get("force_mock", False)

    question = recall_service.next_question(
        lesson_dir, qtype, order, unit_cursor, exclude_id,
        runtime_cfg.recall.refill_batch_size, state_dir, force_mock=force_mock,
    )

    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError:
        print("⚠️  Telegram non configurato: impossibile inviare la domanda.")
        return

    thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)

    if question is None:
        try:
            tg_session.end_session(state_dir, tg_cfg.chat_id, thread_id)
            tg_client.send_message(
                tg_cfg,
                text=f"✨ Nessuna domanda '{active_style}' disponibile al momento. Cambia stile con /stile oppure riprova più tardi.",
                message_thread_id=thread_id,
            )
        except Exception:
            pass
        return

    session_state["current_question_id"] = question.id
    if order == "alternato":
        session_state["unit_cursor"] = question.unit_ids[0]
    recall_service.save_recall_session_state(lesson_dir, session_state)

    is_stale = recall_service.is_question_stale(lesson_dir, question)
    unit_ids_str = ", ".join(question.unit_ids)
    stale_warning = f"⚠️ L'unità {unit_ids_str} da cui è tratta questa domanda è stata modificata dopo la generazione di questa domanda.\n\n"

    if question.type == RecallQuestionType.QUIZ:
        if is_stale:
            try:
                tg_client.send_message(
                    tg_cfg,
                    text=f"⚠️ L'unità {unit_ids_str} da cui è tratta questa domanda è stata modificata dopo la generazione di questa domanda.",
                    message_thread_id=thread_id,
                )
            except Exception:
                pass
        # Poll nativo Telegram: la tastiera ("Non lo so"/"Skip") viene allegata direttamente
        # al messaggio del poll tramite reply_markup di sendPoll (API Telegram supporta reply_markup).
        # Troncamento difensivo: opzioni >100 caratteri e domanda >290 caratteri (limite API sendPoll).
        poll_msg_id = None
        # Riferimento all'unità solo se la domanda deriva da una sola unità (come le domande
        # mirate): le domande vaste spaziano su più unità, un singolo riferimento sarebbe fuorviante.
        unit_prefix = f"📌 Unità: {question.unit_ids[0]}\n\n" if len(question.unit_ids) == 1 else ""
        raw_text = question.question_text
        max_text_len = 290 - len(unit_prefix)
        if len(raw_text) > max_text_len:
            print(f"⚠️  [recall] Domanda quiz troncata ({len(raw_text)} chars > {max_text_len}): {raw_text[:60]}...", file=sys.stderr)
            raw_text = raw_text[:max_text_len - 1] + "…"
        q_text = unit_prefix + raw_text
        safe_options = []
        for opt in (question.options or []):
            if len(opt) > 100:
                print(f"⚠️  [recall] Opzione quiz troncata ({len(opt)} chars > 100): {opt[:40]}...", file=sys.stderr)
                safe_options.append(opt[:97] + "…")
            else:
                safe_options.append(opt)
        try:
            action_short_id = tg_registry.register_pending(
                lesson_dir, round_=0, kind="recall_question", state_dir=state_dir,
                message_thread_id=thread_id, extra={"question_id": question.id, "qtype": "quiz", "poll_message_id": None},
            )
            action_keyboard = tg_fmt.build_recall_action_keyboard(action_short_id)
            poll_res = tg_client.send_poll(
                tg_cfg, question=q_text, options=safe_options,
                correct_option_id=question.correct_index, message_thread_id=thread_id,
                reply_markup=action_keyboard,
            )
            poll_id = poll_res.get("poll", {}).get("id")
            poll_msg_id = poll_res.get("message_id")
            if poll_id:
                tg_registry.register_with_key(
                    poll_id, lesson_dir, kind="recall_quiz_poll", state_dir=state_dir,
                    message_thread_id=thread_id, extra={"question_id": question.id, "message_id": poll_msg_id},
                )
            if poll_msg_id is not None:
                session_state["current_question_message_id"] = poll_msg_id
                recall_service.save_recall_session_state(lesson_dir, session_state)
                tg_registry.register_with_key(
                    str(poll_msg_id), lesson_dir, kind="recall_question_message", state_dir=state_dir,
                    message_thread_id=thread_id, extra={"question_id": question.id},
                )
                tg_session.update_session_message(state_dir, tg_cfg.chat_id, thread_id, poll_msg_id)
            # Aggiorna poll_message_id nell'entry recall_question già registrata
            tg_registry.register_with_key(
                action_short_id, lesson_dir, kind="recall_question", state_dir=state_dir,
                message_thread_id=thread_id, extra={"question_id": question.id, "qtype": "quiz", "poll_message_id": poll_msg_id, "message_id": poll_msg_id},
            )
        except tg_client.TelegramAPIError as e:
            print(f"⚠️  Invio quiz a Telegram fallito: {e}")
    else:
        text = (stale_warning if is_stale else "") + tg_fmt.render_recall_question_text(question)
        short_id = tg_registry.register_pending(
            lesson_dir, round_=0, kind="recall_question", state_dir=state_dir,
            message_thread_id=thread_id, extra={"question_id": question.id, "qtype": question.type.value}
        )
        keyboard = tg_fmt.build_recall_action_keyboard(short_id)
        try:
            res = tg_client.send_message(tg_cfg, text=text, reply_markup=keyboard, message_thread_id=thread_id)
            msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
            if isinstance(msg_id, int):
                session_state["current_question_message_id"] = msg_id
                recall_service.save_recall_session_state(lesson_dir, session_state)
                tg_registry.update_pending(short_id, {"message_id": msg_id}, state_dir)
                tg_session.update_session_message(state_dir, tg_cfg.chat_id, thread_id, msg_id)
                tg_registry.register_with_key(
                    str(msg_id), lesson_dir, kind="recall_question_message", state_dir=state_dir,
                    message_thread_id=thread_id, extra={"question_id": question.id},
                )
        except tg_client.TelegramAPIError as e:
            print(f"⚠️  Invio domanda a Telegram fallito: {e}")

    # Rifornimento se la riserva del tipo attivo è sotto soglia (non blocca l'invio già avvenuto sopra)
    recall_service.refill_if_low(
        lesson_dir, qtype, runtime_cfg.recall.refill_threshold,
        runtime_cfg.recall.refill_batch_size, state_dir, force_mock=force_mock,
    )
