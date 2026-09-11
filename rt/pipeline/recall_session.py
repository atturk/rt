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
from typing import Optional, List

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
    from rt.pipeline.ledger import load_resolved_draft
    try:
        draft = load_resolved_draft(lesson_dir)
    except Exception:
        return ""
    units = [u for u in draft.units if u.unit_id in question.unit_ids]
    if not units:
        return ""
    parts = []
    for u in units:
        parts.append(f"\n\n📚 Unità {u.unit_id} - {u.title}:\n{u.content}")
    return "".join(parts)


def send_unit_audio(lesson_dir: str, question, message_thread_id: Optional[int] = None) -> List[int]:
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
    os.makedirs(clips_dir, exist_ok=True)
    ext = os.path.splitext(audio_path)[1] or ".mp3"

    sent_msg_ids: List[int] = []
    for u in units:
        clip_path = os.path.join(clips_dir, f"{u.unit_id}{ext}")
        if not os.path.isfile(clip_path):
            start_s, end_s = resolve_unit_time_range(u, segments)
            tmp_clip = cut_clip(audio_path, start_s, end_s)
            shutil.move(tmp_clip, clip_path)
        res = send_audio(tg_cfg, clip_path, title=f"{u.unit_id} - {u.title}", message_thread_id=message_thread_id)
        msg_id = res.get("message_id") if isinstance(res, dict) else getattr(res, "message_id", None)
        if isinstance(msg_id, int):
            sent_msg_ids.append(msg_id)
    return sent_msg_ids


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
        res = {
            "order": data.get("order", "alternato"),
            "unit_cursor": data.get("unit_cursor"),
            "current_question_id": data.get("current_question_id"),
            "force_mock": data.get("force_mock", False),
        }
        if "current_question_message_id" in data:
            res["current_question_message_id"] = data["current_question_message_id"]
        if "current_post_answer_short_id" in data:
            res["current_post_answer_short_id"] = data["current_post_answer_short_id"]
        if "current_post_answer_message_id" in data:
            res["current_post_answer_message_id"] = data["current_post_answer_message_id"]
        return res
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
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics, runtime_cfg.misc_topic_id)

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
    save_recall_session_state(lesson_dir, session_state)

    from rt.pipeline.recall import _compute_units_fingerprint
    current_fp = _compute_units_fingerprint(lesson_dir, question.unit_ids)
    is_stale = (
        question.content_fingerprint is not None
        and current_fp is not None
        and current_fp != question.content_fingerprint
    )
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
                session_state["current_question_message_id"] = poll_msg_id
                save_recall_session_state(lesson_dir, session_state)
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
                save_recall_session_state(lesson_dir, session_state)
                tg_registry.update_pending(short_id, {"message_id": msg_id}, state_dir)
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


def run_stale_recall_check(lesson_dir: str, state_dir: Optional[str] = None) -> None:
    """Revisione interattiva da terminale delle domande stale il cui content_fingerprint
    non corrisponde più al contenuto attuale delle unità didattiche."""
    from rt.core.config import load_config
    from rt.telegram import session as tg_session
    if not state_dir:
        state_dir = load_config().telegram.state_dir
    active = tg_session.get_active_session_for_lesson(state_dir, lesson_dir, kind="recall")
    if active is not None:
        print("ℹ️ C'è già una sessione Telegram attiva di recall per questa lezione. Usa /quit su Telegram per chiuderla prima di eseguire --check.")
        return

    from rt.pipeline.recall import load_recall_bank, save_recall_bank, _compute_units_fingerprint
    bank = load_recall_bank(lesson_dir)
    stale_questions = []
    for q in bank.questions:
        if q.content_fingerprint is not None:
            current_fp = _compute_units_fingerprint(lesson_dir, q.unit_ids)
            if current_fp is not None and current_fp != q.content_fingerprint:
                stale_questions.append(q)

    if not stale_questions:
        print("Nessuna domanda da rivedere.")
        return

    if not sys.stdin.isatty():
        print(f"⚠️  [HUMAN REVIEW REQUIRED] Ci sono {len(stale_questions)} domande stale che richiedono revisione umana.")
        return

    print(f"\n🔍 REVISIONE DOMANDE STALE ({len(stale_questions)} da rivedere)")
    print("=" * 60)

    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rt.core.keyboard import read_single_key, raw_mode
    from rt.core.encoding import fix_mojibake

    console = Console()
    total_count = len(stale_questions)
    idx = 0
    history_stack = []
    kept_count = 0
    deleted_count = 0
    skipped_count = 0
    last_status: Optional[str] = None
    interrupted = False

    def _build_stale_panel(idx: int, total_count: int, q, bank, last_status: Optional[str] = None):
        lines = [
            f"[{idx + 1}/{total_count}] STALE RECALL QUESTION ({q.type.value.upper()}) - ID: {q.id}",
            f"  📚 Unità: {', '.join(q.unit_ids)}",
            f"  📌 Stato: {q.status.value}",
            f"  ❓ Domanda: \"{fix_mojibake(q.question_text)}\"",
        ]
        if q.type == RecallQuestionType.QUIZ and q.options:
            lines.append("  📝 Opzioni:")
            for opt in q.options:
                lines.append(f"    - {fix_mojibake(opt)}")
        if q.pregenerated_material:
            lines.append(f"  💡 Spiegazione: {fix_mojibake(q.pregenerated_material)}")
        answers = [a for a in bank.answers if a.question_id == q.id]
        if answers:
            last_ans = answers[-1]
            lines.append(f"  💬 Ultima risposta registrata: \"{fix_mojibake(last_ans.answer_text)}\"")
            if last_ans.evaluation:
                lines.append(f"  ⭐ Ultima valutazione: {fix_mojibake(last_ans.evaluation)}")

        if last_status:
            lines.append(f"\n  {last_status}")

        lines.append("\n  Azione [M=Mantieni (aggiorna fingerprint) / E=Elimina domanda+risposte / S=Salta / B=Indietro / Q=Esci]: ")
        content = "\n".join(lines)
        return Panel(Text(content), title=f"Stale Recall Check [{idx + 1}/{total_count}]", border_style="yellow")

    try:
        with raw_mode() as is_raw, Live(console=console, auto_refresh=False, transient=False, vertical_overflow="visible") as live:
            while idx < total_count:
                q = stale_questions[idx]
                bank = load_recall_bank(lesson_dir)
                panel = _build_stale_panel(idx, total_count, q, bank, last_status)
                live.update(panel, refresh=True)

                while True:
                    raw_key = read_single_key(already_raw=is_raw)
                    choice = raw_key.strip().lower()

                    if choice in ("m", "mantieni"):
                        old_fp = q.content_fingerprint
                        cur_fp = _compute_units_fingerprint(lesson_dir, q.unit_ids)
                        b = load_recall_bank(lesson_dir)
                        bq = next((item for item in b.questions if item.id == q.id), None)
                        if bq:
                            bq.content_fingerprint = cur_fp
                            save_recall_bank(b, lesson_dir)
                        history_stack.append(("kept", q.id, old_fp))
                        kept_count += 1
                        last_status = f"✔ Mantenuta domanda {q.id} (fingerprint aggiornato)."
                        idx += 1
                        break
                    elif choice in ("e", "elimina"):
                        b = load_recall_bank(lesson_dir)
                        q_to_del = next((item for item in b.questions if item.id == q.id), None)
                        a_to_del = [a for a in b.answers if a.question_id == q.id]
                        b.questions = [item for item in b.questions if item.id != q.id]
                        b.answers = [a for a in b.answers if a.question_id != q.id]
                        save_recall_bank(b, lesson_dir)
                        history_stack.append(("deleted", q_to_del or q, a_to_del))
                        deleted_count += 1
                        last_status = f"🗑 Eliminata domanda {q.id} e relative risposte."
                        idx += 1
                        break
                    elif choice in ("s", "salta", "skip", "right", "RIGHT"):
                        history_stack.append(("skipped", q.id, None))
                        skipped_count += 1
                        last_status = "⏭ Saltato."
                        idx += 1
                        break
                    elif choice in ("b", "indietro", "back", "left", "LEFT"):
                        if idx == 0:
                            last_status = "⚠️  Sei già al primo elemento, impossibile tornare oltre."
                            panel = _build_stale_panel(idx, total_count, q, bank, last_status)
                            live.update(panel, refresh=True)
                            continue
                        else:
                            idx -= 1
                            action_type, hist_q, hist_extra = history_stack.pop()
                            b = load_recall_bank(lesson_dir)
                            if action_type == "kept":
                                bq = next((item for item in b.questions if item.id == hist_q), None)
                                if bq:
                                    bq.content_fingerprint = hist_extra
                                    save_recall_bank(b, lesson_dir)
                                kept_count -= 1
                            elif action_type == "deleted":
                                if not any(item.id == hist_q.id for item in b.questions):
                                    b.questions.append(hist_q)
                                for a in hist_extra:
                                    b.answers.append(a)
                                save_recall_bank(b, lesson_dir)
                                deleted_count -= 1
                            elif action_type == "skipped":
                                skipped_count -= 1
                            prev_q = stale_questions[idx]
                            last_status = f"◀️ Tornato alla domanda precedente ({prev_q.id})."
                            break
                    elif choice in ("q", "esci", "quit"):
                        last_status = "⏹ Revisione interrotta."
                        interrupted = True
                        break
                    else:
                        continue

                if interrupted:
                    break
    except KeyboardInterrupt:
        print("\n  ⏹ Sessione interrotta.")

    print(f"\n📊 Riepilogo revisione stale: {kept_count} mantenute, {deleted_count} eliminate, {skipped_count} saltate.")
