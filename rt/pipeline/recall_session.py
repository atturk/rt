"""
rt.pipeline.recall_session
Orchestrazione di una sessione di Active Recall (Fase D2/D3): avvio su Telegram
o da terminale, invio/selezione della domanda corrente, cattura e valutazione
delle risposte. Riusa il motore D1 (rt.pipeline.recall) per storage/generazione,
senza toccarne la logica.
"""
import os
import json
import sys
import shutil
from typing import Optional

from rt.core.models import RecallQuestionType
from rt.core.lesson_paths import lesson_path

# -----------------------------------------------------------------------
# Riferimento all'unità didattica di una domanda (allegato a ogni esito/valutazione)
# -----------------------------------------------------------------------

def format_unit_reference(lesson_dir: str, question) -> str:
    """Blocco testuale (testo semplice, no HTML: i messaggi del daemon non impostano
    parse_mode) con il contenuto completo di tutte le unità didattiche della domanda.
    Mostra sempre il contenuto intero di ogni unità in question.unit_ids, separandole
    con un'intestazione per unità (es. per vasta che può averne più).
    Usata dal bottone 📖 (richiesta esplicita), non più incollata automaticamente agli esiti."""
    from rt.pipeline.rewrite import load_draft
    try:
        draft = load_draft(lesson_dir)
    except Exception:
        return ""
    units = [u for u in draft.units if u.unit_id in question.unit_ids]
    if not units:
        return ""
    parts = []
    for u in units:
        parts.append(f"\n\n📚 Unità {u.unit_id} - {u.title}:\n{u.content}")
    return "".join(parts)


def send_unit_audio(lesson_dir: str, question, message_thread_id: Optional[int] = None) -> None:
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
    from rt.pipeline.rewrite import load_draft

    draft = load_draft(lesson_dir)
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
    os.makedirs(clips_dir, exist_ok=True)
    ext = os.path.splitext(audio_path)[1] or ".mp3"

    for u in units:
        clip_path = os.path.join(clips_dir, f"{u.unit_id}{ext}")
        if not os.path.isfile(clip_path):
            start_s, end_s = resolve_unit_time_range(u, segments)
            tmp_clip = cut_clip(audio_path, start_s, end_s)
            shutil.move(tmp_clip, clip_path)
        send_audio(tg_cfg, clip_path, title=f"{u.unit_id} - {u.title}", message_thread_id=message_thread_id)


# -----------------------------------------------------------------------
# Stato di sessione per lezione (ordine scelto, cursore round-robin)
# -----------------------------------------------------------------------

def get_recall_session_state_path(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "telegram_recall_session.json")


def load_recall_session_state(lesson_dir: str) -> dict:
    path = get_recall_session_state_path(lesson_dir)
    if not os.path.isfile(path):
        return {"order": "alternato", "unit_cursor": None, "current_question_id": None, "force_mock": False}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "order": data.get("order", "alternato"),
            "unit_cursor": data.get("unit_cursor"),
            "current_question_id": data.get("current_question_id"),
            "force_mock": data.get("force_mock", False),
        }
    except Exception:
        return {"order": "alternato", "unit_cursor": None, "current_question_id": None, "force_mock": False}


def save_recall_session_state(lesson_dir: str, state: dict) -> None:
    path = get_recall_session_state_path(lesson_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


# -----------------------------------------------------------------------
# Batch iniziale (tutti e 3 i tipi, solo se il bank è ancora vuoto)
# -----------------------------------------------------------------------

def _ensure_initial_batch(lesson_dir: str, force_mock: bool = False) -> None:
    from rt.core.config import load_config
    from rt.pipeline.recall import load_recall_bank, generate_recall_batch, load_fewshot_examples

    bank = load_recall_bank(lesson_dir)
    if bank.questions:
        return

    cfg = load_config()
    state_dir = cfg.telegram.state_dir
    for qtype_str, count in cfg.telegram.recall.reserve_targets.items():
        qtype = RecallQuestionType(qtype_str)
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, count, examples, force_mock=force_mock)


# -----------------------------------------------------------------------
# Cattura risposta (testo o vocale già trascritto): salva + valuta se serve
# -----------------------------------------------------------------------

def handle_recall_answer(lesson_dir: str, question_id: str, answer_text: str, is_voice: bool = False, force_mock: Optional[bool] = None) -> Optional[str]:
    """Salva la risposta a una domanda mirata/vasta e la valuta con l'LLM.
    Ritorna il testo di valutazione, o None se la domanda non esiste o è un quiz
    (i quiz si rispondono con un bottone, gestiti a parte).

    force_mock=None (default) risolve dal flag persistito in telegram_recall_session.json:
    la sessione è stata avviata via terminale/CLI con --mock, e il daemon (processo separato,
    invocato più tardi per i rifornimenti/risposte) deve rispettarlo senza doverlo ripassare
    esplicitamente ad ogni chiamata."""
    from rt.pipeline.recall import load_recall_bank, record_recall_answer, evaluate_recall_answer

    bank = load_recall_bank(lesson_dir)
    question = next((q for q in bank.questions if q.id == question_id), None)
    if question is None or question.type == RecallQuestionType.QUIZ:
        return None

    if force_mock is None:
        force_mock = load_recall_session_state(lesson_dir).get("force_mock", False)

    evaluation = evaluate_recall_answer(lesson_dir, question_id, answer_text, force_mock=force_mock)
    record_recall_answer(lesson_dir, question_id, answer_text, is_voice=is_voice, evaluation=evaluation)
    return evaluation


# -----------------------------------------------------------------------
# Avvio sessione Telegram
# -----------------------------------------------------------------------

def start_recall_via_telegram(lesson_dir: str, order: str = "alternato", style: Optional[str] = None, force_mock: bool = False) -> None:
    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id, TelegramConfigError
        from rt.telegram import client as tg_client, session as tg_session, recall_preferences
        from rt.core.config import load_config

        tg_cfg = load_telegram_config()
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)

        active = tg_session.get_active_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id)
        if active is not None:
            if active.get("kind") != "recall" or os.path.abspath(active.get("lesson_dir", "")) != os.path.abspath(lesson_dir):
                busy_msg = f"C'è già un'attività in corso in questo topic ({active.get('kind')}). Usa /quit per chiuderla prima."
                tg_client.send_message(tg_cfg, text=busy_msg, message_thread_id=thread_id)
                print(f"⚠️  {busy_msg}")
                return
            else:
                reminder_msg = "ℹ️ Sessione di recall già in corso per questa lezione su questo topic. Continua dal messaggio precedente, oppure usa /quit per annullarla."
                tg_client.send_message(tg_cfg, text=reminder_msg, message_thread_id=thread_id)
                print(f"ℹ️  {reminder_msg}")
                return

        tg_session.start_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id, "recall", lesson_dir)
        if style:
            recall_preferences.set_active_style(runtime_cfg.state_dir, style)
    except TelegramConfigError:
        print("⚠️  Telegram non configurato: impossibile avviare il recall su Telegram. Usa --channel terminal.")
        return
    except Exception as e:
        print(f"⚠️  Impossibile avviare la sessione Telegram: {e}")
        return

    save_recall_session_state(lesson_dir, {"order": order, "unit_cursor": None, "current_question_id": None, "force_mock": force_mock})
    _ensure_initial_batch(lesson_dir, force_mock=force_mock)

    print(f"📤 Sessione di recall avviata su Telegram (ordine: {order}).")
    send_current_recall_question(lesson_dir, force_mock=force_mock)
    print("   Continua dal telefono quando vuoi.")


# -----------------------------------------------------------------------
# Invio della domanda corrente su Telegram (chiamata dal trigger iniziale
# e dal daemon dopo ogni voto/risposta/salto)
# -----------------------------------------------------------------------

def send_current_recall_question(lesson_dir: str, force_mock: Optional[bool] = None, exclude_id: Optional[str] = None) -> None:
    """force_mock=None (default) risolve dal flag persistito in telegram_recall_session.json
    (vedi handle_recall_answer): il daemon, chiamando questa funzione dopo ogni risposta/voto/
    rifornimento, deve rispettare il --mock con cui la sessione è stata avviata da terminale.

    exclude_id: se specificato (tipicamente la domanda appena skippata), viene passato a
    get_next_pending_question per evitare di riproporla immediatamente come prossima."""
    from rt.telegram.config import load_telegram_config, TelegramConfigError, resolve_topic_id
    from rt.telegram import client as tg_client, registry as tg_registry, formatting as tg_fmt, session as tg_session, recall_preferences
    from rt.core.config import load_config
    from rt.pipeline.recall import get_next_pending_question, get_reserve_count, generate_recall_batch, load_fewshot_examples

    runtime_cfg = load_config().telegram
    state_dir = runtime_cfg.state_dir
    active_style = recall_preferences.get_active_style(state_dir)
    qtype = RecallQuestionType(active_style)

    session_state = load_recall_session_state(lesson_dir)
    order = session_state.get("order", "alternato")
    unit_cursor = session_state.get("unit_cursor")
    if force_mock is None:
        force_mock = session_state.get("force_mock", False)

    question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)

    if question is None:
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, runtime_cfg.recall.refill_batch_size, examples, force_mock=force_mock)
        question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)

    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError:
        print("⚠️  Telegram non configurato: impossibile inviare la domanda.")
        return

    thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)

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
    save_recall_session_state(lesson_dir, session_state)

    if question.type == RecallQuestionType.QUIZ:
        # Poll nativo Telegram: la tastiera ("Non lo so"/"Skip") viene allegata direttamente
        # al messaggio del poll tramite reply_markup di sendPoll (API Telegram supporta reply_markup).
        # Troncamento difensivo: opzioni >100 caratteri e domanda >290 caratteri (limite API sendPoll).
        poll_msg_id = None
        q_text = question.question_text
        if len(q_text) > 290:
            print(f"⚠️  [recall] Domanda quiz troncata ({len(q_text)} chars > 290): {q_text[:60]}...", file=sys.stderr)
            q_text = q_text[:290] + "…"
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
                tg_registry.register_with_key(
                    str(poll_msg_id), lesson_dir, kind="recall_question_message", state_dir=state_dir,
                    message_thread_id=thread_id, extra={"question_id": question.id},
                )
                tg_session.update_session_message(state_dir, tg_cfg.chat_id, thread_id, poll_msg_id)
            # Aggiorna poll_message_id nell'entry recall_question già registrata
            tg_registry.register_with_key(
                action_short_id, lesson_dir, kind="recall_question", state_dir=state_dir,
                message_thread_id=thread_id, extra={"question_id": question.id, "qtype": "quiz", "poll_message_id": poll_msg_id},
            )
        except tg_client.TelegramAPIError as e:
            print(f"⚠️  Invio quiz a Telegram fallito: {e}")
    else:
        text = tg_fmt.render_recall_question_text(question)
        short_id = tg_registry.register_pending(
            lesson_dir, round_=0, kind="recall_question", state_dir=state_dir,
            message_thread_id=thread_id, extra={"question_id": question.id, "qtype": question.type.value}
        )
        keyboard = tg_fmt.build_recall_action_keyboard(short_id)
        try:
            res = tg_client.send_message(tg_cfg, text=text, reply_markup=keyboard, message_thread_id=thread_id)
            msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
            if msg_id is not None:
                tg_session.update_session_message(state_dir, tg_cfg.chat_id, thread_id, msg_id)
                tg_registry.register_with_key(
                    str(msg_id), lesson_dir, kind="recall_question_message", state_dir=state_dir,
                    message_thread_id=thread_id, extra={"question_id": question.id},
                )
        except tg_client.TelegramAPIError as e:
            print(f"⚠️  Invio domanda a Telegram fallito: {e}")

    # Rifornimento se la riserva del tipo attivo è sotto soglia (non blocca l'invio già avvenuto sopra)
    remaining = get_reserve_count(lesson_dir, qtype)
    if remaining < runtime_cfg.recall.refill_threshold:
        examples = load_fewshot_examples(qtype, state_dir=state_dir)
        generate_recall_batch(lesson_dir, qtype, runtime_cfg.recall.refill_batch_size, examples, force_mock=force_mock)


# -----------------------------------------------------------------------
# Sessione interattiva da terminale
# -----------------------------------------------------------------------

def run_recall_terminal_session(lesson_dir: str, order: str = "alternato", style: Optional[str] = None, force_mock: bool = False) -> None:
    from rt.core.keyboard import read_single_key, raw_mode
    from rt.core.editor_edit import edit_text_in_editor
    from rt.core.config import load_config
    from rt.telegram import recall_preferences
    from rt.pipeline.recall import (
        get_next_pending_question, get_reserve_count, generate_recall_batch,
        load_fewshot_examples, record_recall_answer, record_recall_vote,
        record_fewshot_vote, evaluate_recall_answer, skip_recall_question,
    )

    cfg = load_config()
    state_dir = cfg.telegram.state_dir
    if style:
        recall_preferences.set_active_style(state_dir, style)
    active_style = recall_preferences.get_active_style(state_dir)
    qtype = RecallQuestionType(active_style)

    if not sys.stdin.isatty():
        print("⚠️  Terminale non interattivo: il recall da terminale richiede un TTY. Usa --channel telegram.")
        return

    _ensure_initial_batch(lesson_dir, force_mock=force_mock)

    print(f"\n🧠 SESSIONE DI ACTIVE RECALL — stile: {active_style}, ordine: {order}")
    print("=" * 60)

    unit_cursor: Optional[str] = None
    exclude_id: Optional[str] = None
    interrupted = False

    try:
        with raw_mode() as is_raw:
            while not interrupted:
                question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)
                if question is None:
                    examples = load_fewshot_examples(qtype, state_dir=state_dir)
                    generate_recall_batch(lesson_dir, qtype, cfg.telegram.recall.refill_batch_size, examples, force_mock=force_mock)
                    question = get_next_pending_question(lesson_dir, qtype, order=order, unit_cursor=unit_cursor, exclude_id=exclude_id)
                exclude_id = None
                if question is None:
                    print(f"\n✨ Nessuna domanda '{active_style}' disponibile al momento. Cambia stile o riprova più tardi.")
                    break

                if order == "alternato":
                    unit_cursor = question.unit_ids[0]

                print(f"\n[{question.type.value.upper()}] Unità: {', '.join(question.unit_ids)}")
                print(f"  {question.question_text}")
                letters = ["A", "B", "C", "D"]
                if question.type == RecallQuestionType.QUIZ and question.options:
                    for i, opt in enumerate(question.options):
                        print(f"  {letters[i]}) {opt}")

                if question.type == RecallQuestionType.QUIZ:
                    print("\n  Azione [A/B/C/D=Scegli / 1=👍 / 2=👎 / 3=⚡ / S=Salta / Q=Esci]: ", end="", flush=True)
                else:
                    print("\n  Azione [R=Rispondi (editor) / 1=👍 / 2=👎 / 3=⚡ / S=Salta / Q=Esci]: ", end="", flush=True)

                while True:
                    raw_key = read_single_key(already_raw=is_raw)
                    choice = raw_key.strip().lower()

                    if question.type == RecallQuestionType.QUIZ and choice in ("a", "b", "c", "d"):
                        print(raw_key)
                        idx_choice = "abcd".index(choice)
                        is_correct = (question.correct_index == idx_choice)
                        record_recall_answer(
                            lesson_dir, question.id, question.options[idx_choice],
                            is_voice=False, evaluation=question.pregenerated_material,
                        )
                        esito = "✔ Corretto!" if is_correct else "❌ Sbagliato."
                        print(f"  {esito}")
                        if question.pregenerated_material:
                            print(f"  {question.pregenerated_material}")
                        break
                    elif choice in ("r", "rispondi") and question.type != RecallQuestionType.QUIZ:
                        print(raw_key)
                        initial = f"# Scrivi qui la tua risposta. La riga con # viene ignorata.\n# Domanda: {question.question_text}\n\n"
                        edited = edit_text_in_editor(initial)
                        lines = [l for l in edited.splitlines() if not l.strip().startswith("#")]
                        answer_text = "\n".join(lines).strip()
                        if not answer_text:
                            print("  ⚠️ Nessuna risposta inserita.")
                            continue
                        print("  ⏳ Valutazione in corso...")
                        evaluation = evaluate_recall_answer(lesson_dir, question.id, answer_text, force_mock=force_mock)
                        record_recall_answer(lesson_dir, question.id, answer_text, is_voice=False, evaluation=evaluation)
                        print(f"\n{evaluation}\n")
                        break
                    elif choice == "1":
                        record_recall_vote(lesson_dir, question.id, "up")
                        record_fewshot_vote(question.type, question.question_text, "up", state_dir=state_dir)
                        continue
                    elif choice == "2":
                        record_recall_vote(lesson_dir, question.id, "down")
                        record_fewshot_vote(question.type, question.question_text, "down", state_dir=state_dir)
                        continue
                    elif choice == "3":
                        record_recall_vote(lesson_dir, question.id, "lightning")
                        record_fewshot_vote(question.type, question.question_text, "lightning", state_dir=state_dir)
                        continue
                    elif choice in ("s", "salta", "skip"):
                        print(raw_key)
                        print("  ⏭ Saltato.")
                        skip_recall_question(lesson_dir, question.id)
                        exclude_id = question.id
                        break
                    elif choice in ("q", "esci", "quit"):
                        print(raw_key)
                        print("  ⏹ Sessione di recall interrotta.")
                        interrupted = True
                        break
                    else:
                        continue

                # Rifornimento proattivo se sotto soglia
                remaining = get_reserve_count(lesson_dir, qtype)
                if remaining < cfg.telegram.recall.refill_threshold:
                    examples = load_fewshot_examples(qtype, state_dir=state_dir)
                    generate_recall_batch(lesson_dir, qtype, cfg.telegram.recall.refill_batch_size, examples, force_mock=force_mock)
    except KeyboardInterrupt:
        print("\n  ⏹ Sessione di recall interrotta.")
