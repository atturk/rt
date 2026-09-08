"""
rt.pipeline.outline_review
Loop di conferma/revisione outline: blocca fino ad approvazione, via terminale o
Telegram a seconda del canale scelto per la sessione. Nessuna conferma per singola
unità di rewrite: una volta approvata l'outline, il resto della pipeline procede
automaticamente (comportamento invariato).
"""
import os
import time
from rt.core.idempotency import check_phase_status, PhaseStatus
from rt.pipeline.outline import load_outline, run_outline_revision
from rt.telegram import formatting as tg_fmt


def confirm_or_revise_outline(lesson_dir: str, channel: str, force: bool = False, force_mock: bool = False) -> None:
    """Punto di ingresso unico, chiamato da cmd_run() tra OUTLINE e REWRITE.

    Regola di gating (per evitare due bug distinti: ri-chiedere conferma ad ogni
    re-run idempotente quando il rewrite è già stato fatto, oppure saltarla dopo
    un Ctrl+C se l'outline risultava "già valida" al riavvio): si entra nel loop
    di conferma solo se la fase 'rewrite' NON è già VALID, oppure se force=True.
    """
    if not force:
        phase_status, _ = check_phase_status(lesson_dir, "rewrite")
        if phase_status == PhaseStatus.VALID:
            return

    if channel == "telegram":
        _confirm_via_telegram(lesson_dir, force_mock)
    else:
        _confirm_via_terminal(lesson_dir, force_mock)


def _confirm_via_terminal(lesson_dir: str, force_mock: bool) -> None:
    while True:
        outline = load_outline(lesson_dir)
        print("\n" + "=" * 60)
        print("📋 OUTLINE GENERATA — in attesa di conferma")
        print("=" * 60)
        print(tg_fmt.render_outline_summary_text(outline))

        choice = input("\nAzione [A=Approva / M=Richiedi modifiche]: ").strip().lower()
        if choice in ("a", "approva", ""):
            print("✔ Outline approvata.")
            return
        elif choice in ("m", "modifiche"):
            feedback = input("Descrivi le modifiche desiderate: ").strip()
            if not feedback:
                print("Nessun feedback inserito, outline mantenuta invariata.")
                continue
            print("⏳ Rigenerazione outline in corso...")
            run_outline_revision(lesson_dir, feedback=feedback, force_mock=force_mock)
            continue
        else:
            print("Scelta non valida.")


def _warn_if_daemon_inactive(runtime_cfg) -> None:
    import os
    import json
    path = os.path.join(runtime_cfg.state_dir, "daemon_heartbeat.json")
    stale_after = max(30.0, runtime_cfg.poll_interval_seconds * 5)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        from datetime import datetime
        last_seen = datetime.fromisoformat(data["last_seen"])
        age = (datetime.now() - last_seen).total_seconds()
        if age > stale_after:
            print(f"⚠️  Il daemon Telegram non risulta attivo da {age:.0f}s: i bottoni non funzioneranno finché non lo avvii con 'rt telegram-daemon'.")
    except Exception:
        print("⚠️  Il daemon Telegram non sembra attivo: avvialo con 'rt telegram-daemon' in un altro terminale, altrimenti i bottoni non funzioneranno.")


def _confirm_via_telegram(lesson_dir: str, force_mock: bool) -> None:
    from rt.telegram.config import load_telegram_config, TelegramConfigError, resolve_topic_id
    from rt.telegram import client as tg_client, pending as tg_pending, registry as tg_registry, session as tg_session
    from rt.core.config import load_config

    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError as e:
        print(f"⚠️  Telegram non configurato ({e}). Passaggio a conferma da terminale.")
        return _confirm_via_terminal(lesson_dir, force_mock)

    runtime_cfg = load_config().telegram
    message_thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)

    active = tg_session.get_active_session(runtime_cfg.state_dir, tg_cfg.chat_id, message_thread_id)
    if active is not None:
        if active.get("kind") != "outline_confirmation" or os.path.abspath(active.get("lesson_dir", "")) != os.path.abspath(lesson_dir):
            busy_msg = f"C'è già un'attività in corso in questo topic ({active.get('kind')}). Usa /quit per chiuderla prima."
            print(f"⚠️  {busy_msg}")
            try:
                tg_client.send_message(tg_cfg, text=busy_msg, message_thread_id=message_thread_id)
            except Exception:
                pass
            return

    tg_session.start_session(runtime_cfg.state_dir, tg_cfg.chat_id, message_thread_id, "outline_confirmation", lesson_dir)
    existing = tg_pending.load_pending(lesson_dir)

    if existing and existing.status == "changes_requested":
        # Il daemon aveva già registrato un feedback prima che questo processo
        # venisse interrotto (Ctrl+C, crash, terminale chiuso) senza fare in tempo
        # a consumarlo: applicarlo subito, invece di ripartire da un nuovo round con
        # l'outline non rivista, che perderebbe silenziosamente il feedback. Non si
        # ricorsa qui: run_outline_revision() non tocca telegram_pending.json, quindi
        # 'existing.status' resterebbe "changes_requested" per sempre e la ricorsione
        # non terminerebbe mai. Si lascia invece il flusso proseguire nel ramo 'else'
        # sottostante (existing.status non è "pending"), che genera un nuovo round
        # pulito con l'outline appena rivista e resetta lo stato a "pending".
        print(f"↻ Ripresa: feedback già ricevuto in una sessione precedente ({existing.feedback_text!r}), rigenerazione outline...")
        run_outline_revision(lesson_dir, feedback=existing.feedback_text, force_mock=force_mock)

    if existing and existing.status == "pending":
        print(f"↻ Ripresa attesa conferma outline (round {existing.round}) da Telegram...")
        short_id = existing.short_id
    else:
        outline = load_outline(lesson_dir)
        summary_text = tg_fmt.render_outline_summary_text(outline)
        next_round = (existing.round + 1) if existing else 1
        short_id = tg_registry.register_pending(lesson_dir, round_=next_round, kind="outline_confirmation", state_dir=runtime_cfg.state_dir, message_thread_id=message_thread_id)
        keyboard = tg_fmt.build_outline_decision_keyboard(short_id)
        try:
            res = tg_client.send_message(tg_cfg, text=summary_text, reply_markup=keyboard, message_thread_id=message_thread_id)
            msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
            if msg_id is not None:
                tg_session.update_session_message(runtime_cfg.state_dir, tg_cfg.chat_id, message_thread_id, msg_id)
        except tg_client.TelegramAPIError as e:
            print(f"⚠️  Invio a Telegram fallito ({e}). Passaggio a conferma da terminale.")
            tg_session.end_session(runtime_cfg.state_dir, tg_cfg.chat_id, message_thread_id)
            return _confirm_via_terminal(lesson_dir, force_mock)
        tg_pending.create_pending(lesson_dir, round_=next_round, short_id=short_id, outline_summary_text=summary_text)
        _warn_if_daemon_inactive(runtime_cfg)

    print("⏳ In attesa di conferma da Telegram (Ctrl+C per interrompere e riprendere più tardi rilanciando lo stesso comando)...")
    try:
        while True:
            time.sleep(runtime_cfg.poll_interval_seconds)
            state = tg_pending.load_pending(lesson_dir)
            if state is None or state.short_id != short_id:
                continue
            if state.status == "approved":
                print("✔ Outline approvata da Telegram.")
                tg_session.end_session(runtime_cfg.state_dir, tg_cfg.chat_id, message_thread_id)
                return
            if state.status == "cancelled":
                print("Conferma annullata da Telegram. Rilancia lo stesso comando per ricominciare.")
                tg_session.end_session(runtime_cfg.state_dir, tg_cfg.chat_id, message_thread_id)
                return
            if state.status == "changes_requested":
                print(f"✏️  Feedback ricevuto: {state.feedback_text}")
                print("⏳ Rigenerazione outline in corso...")
                run_outline_revision(lesson_dir, feedback=state.feedback_text, force_mock=force_mock)
                return _confirm_via_telegram(lesson_dir, force_mock)
    except KeyboardInterrupt:
        print("\n⏹ Interrotto. Rilancia lo stesso comando sulla stessa cartella per riprendere l'attesa.")
        raise

