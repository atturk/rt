"""
rt.pipeline.issue_review
Invio sequenziale delle issue ASR/scientifiche via Telegram e avanzamento della
coda dopo ogni decisione. Non blocca mai il chiamante: avvia la coda, manda la
prima issue, ritorna. Il resto della coda viene avanzato dal daemon dopo ogni
click/risposta (vedi rt/telegram/daemon.py).
"""
import os
import re
import signal
import subprocess
from typing import List, Optional
from rt.core.models import ASRIssue, ScienceIssue
from rt.telegram import issue_queue as tg_queue
from rt.core.keyboard import read_single_key
from rt.core.audio_clip import resolve_audio_path, cut_clip, play_clip_background
from rt.core.editor_edit import edit_text_in_editor


def start_review_via_telegram(lesson_dir: str, asr_to_review: List[ASRIssue], sci_to_review: List[ScienceIssue]) -> None:
    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id, TelegramConfigError
        from rt.telegram import client as tg_client, session as tg_session
        from rt.core.config import load_config

        tg_cfg = load_telegram_config()
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)

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
        print("⚠️  Telegram non configurato: impossibile inviare l'issue. Usa 'rt review-asr \"<cartella>\"' o 'rt review-science' da terminale.")
        return
    except Exception as e:
        print(f"⚠️  Impossibile avviare la sessione Telegram: {e}")
        return

    issue_ids = [iss.id for iss in asr_to_review] + [iss.id for iss in sci_to_review]
    issue_types = {iss.id: "asr" for iss in asr_to_review}
    issue_types.update({iss.id: "science" for iss in sci_to_review})
    tg_queue.create_queue(lesson_dir, issue_ids=issue_ids, issue_types=issue_types)
    print(f"📤 {len(issue_ids)} issue in coda per la review su Telegram.")
    send_current_issue(lesson_dir)
    print("   Continua la review dal telefono quando vuoi. Esegui 'rt build \"<cartella>\"' una volta finita.")


def _prepare_issue_context(lesson_dir: str, issue, issue_type: str) -> dict:
    from rt.core.segments import load_segments_json
    from rt.pipeline.rewrite import load_draft, get_draft_path

    seg_data = load_segments_json(os.path.join(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in seg_data.segments} if seg_data else {}
    draft_path = get_draft_path(lesson_dir)
    draft = load_draft(lesson_dir) if os.path.isfile(draft_path) else None
    seg_to_unit, unit_by_id = {}, {}
    if draft:
        for u in draft.units:
            unit_by_id[u.unit_id] = u
            for sid in u.source_segment_ids:
                seg_to_unit[sid] = u

    if issue_type == "asr":
        seg = seg_by_id.get(issue.segment_id)
        target_unit = seg_to_unit.get(issue.segment_id)
        sentence = ""
        if target_unit:
            from rt.pipeline.ledger import extract_context_sentence
            sentence = extract_context_sentence(target_unit.content, issue.candidate, issue.source_text)
        start_s = max(0.0, seg.start_seconds - 5.0) if seg else None
        end_s = (seg.end_seconds + 5.0) if seg else None
        return {
            "timecode": seg.start_formatted if seg else "N/D",
            "listen_range": f"{seg.start_formatted} - {seg.end_formatted}" if seg else "N/D",
            "unit_info": f"{target_unit.unit_id} - {target_unit.title}" if target_unit else None,
            "sentence": sentence,
            "start_segment_id": issue.segment_id,
            "end_segment_id": issue.segment_id,
            "start_s": start_s,
            "end_s": end_s,
        }
    else:
        seg = seg_by_id.get(issue.segment_id) if issue.segment_id else None
        sci_unit = unit_by_id.get(issue.unit_id) if issue.unit_id else (seg_to_unit.get(issue.segment_id) if issue.segment_id else None)
        start_segment_id, end_segment_id = None, None
        start_s, end_s = None, None
        if sci_unit:
            start_segment_id = sci_unit.start_segment_id
            end_segment_id = sci_unit.end_segment_id
            s_seg = seg_by_id.get(sci_unit.start_segment_id)
            e_seg = seg_by_id.get(sci_unit.end_segment_id)
            if s_seg and e_seg:
                start_s = s_seg.start_seconds
                end_s = e_seg.end_seconds
        if start_segment_id is None and issue.segment_id:
            start_segment_id = issue.segment_id
            end_segment_id = issue.segment_id
            if seg:
                start_s = seg.start_seconds
                end_s = seg.end_seconds

        return {
            "timecode": seg.start_formatted if seg else "N/D",
            "unit_info": f"{sci_unit.unit_id} - {sci_unit.title}" if sci_unit else issue.unit_id,
            "start_segment_id": start_segment_id,
            "end_segment_id": end_segment_id,
            "start_s": start_s,
            "end_s": end_s,
        }


def send_current_issue(lesson_dir: str) -> None:
    """Invia l'issue corrente della coda (se resta). Chiamata sia dal trigger
    iniziale sia dal daemon dopo ogni decisione/salto. Esegue I/O bloccante
    (rete + disco): il chiamante asincrono (daemon.py) deve invocarla dentro
    un executor, mai direttamente nell'event loop."""
    from rt.telegram.config import load_telegram_config, TelegramConfigError, resolve_topic_id
    from rt.telegram import client as tg_client, registry as tg_registry, formatting as tg_fmt
    from rt.core.config import load_config
    from rt.core.state import transition_to, WorkflowState
    from rt.pipeline.ledger import find_asr_issue_by_id, find_science_issue_by_id

    queue = tg_queue.load_queue(lesson_dir)
    if queue is None:
        return

    if queue.current_index >= len(queue.issue_ids):
        try:
            tg_cfg = load_telegram_config()
            runtime_cfg = load_config().telegram
            thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)
            from rt.telegram import session as tg_session
            tg_session.end_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id)
            tg_client.send_message(tg_cfg, text="✨ Review completata. Esegui 'rt build' quando vuoi.", message_thread_id=thread_id)
        except TelegramConfigError:
            pass
        except Exception:
            pass
        yaml_path = os.path.join(lesson_dir, "info.yaml")
        if os.path.isfile(yaml_path):
            try:
                transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
            except Exception:
                pass
        return


    issue_id = queue.issue_ids[queue.current_index]
    issue_type = queue.issue_types[issue_id]
    issue = find_asr_issue_by_id(lesson_dir, issue_id) if issue_type == "asr" else find_science_issue_by_id(lesson_dir, issue_id)
    if issue is None:
        # issue non più trovata (caso limite, es. rigenerata nel frattempo): salta.
        tg_queue.advance(lesson_dir)
        return send_current_issue(lesson_dir)

    ctx = _prepare_issue_context(lesson_dir, issue, issue_type)
    text = (tg_fmt.render_asr_issue_text(issue, ctx["unit_info"], ctx["timecode"], ctx["listen_range"], ctx["sentence"])
            if issue_type == "asr" else
            tg_fmt.render_science_issue_text(issue, ctx["unit_info"], ctx["timecode"]))

    try:
        tg_cfg = load_telegram_config()
    except TelegramConfigError:
        print(f"⚠️  Telegram non configurato: impossibile inviare l'issue. Usa 'rt review-{issue_type} \"<cartella>\"' da terminale.")
        return

    runtime_cfg = load_config().telegram
    thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)
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
                if tmp_clip and os.path.exists(tmp_clip):
                    try:
                        os.remove(tmp_clip)
                    except Exception:
                        pass



def should_auto_accept_asr(iss: ASRIssue, auto_accept: Optional[str]) -> bool:
    """Valuta se auto-accettare una anomalia ASR in base ai flag CLI."""
    if not auto_accept:
        return False
    from rt.core.models import ASRLevel
    mode = str(auto_accept).lower()
    if mode in ("all", "true"):
        return True
    if mode == "yellow":
        return iss.level == ASRLevel.YELLOW
    if mode == "red":
        return iss.level == ASRLevel.RED
    return False


def should_auto_accept_science(iss: ScienceIssue, auto_accept: Optional[str]) -> bool:
    """Valuta se auto-accettare una critica scientifica in base ai flag CLI."""
    if not auto_accept:
        return False
    mode = str(auto_accept).lower()
    if mode in ("all", "true"):
        return True
    return False


def run_interactive_review(
    lesson_dir: str,
    issue_type: str,
    channel: Optional[str] = None,
    auto_accept: Optional[str] = None,
    history: bool = False
) -> bool:
    """
    Esegue la revisione interattiva di un singolo tipo di issue ('asr' o 'science').
    Supporta navigazione 'indietro' con indice mobile, cronologia (--history) e dispatch Telegram.
    Ritorna True se la revisione di questo tipo è completa e pronta per il build, False altrimenti.
    """
    import sys
    from rt.core.encoding import fix_mojibake
    from rt.core.state import transition_to, WorkflowState
    from rt.core.segments import load_segments_json
    from rt.pipeline.rewrite import load_draft, get_draft_path
    from rt.pipeline.ledger import (
        get_pending_issues,
        load_ledger,
        record_decision,
        revert_last_decision,
        sanitize_suggested_fix,
        extract_context_sentence,
    )
    from rt.pipeline.review_asr import load_asr_issues
    from rt.pipeline.review_science import load_science_issues
    from rt.core.models import ASRLevel

    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    if channel == "telegram" and history:
        print("⚠️  La modalità --history è disponibile solo da terminale. Procedo in modalità normale (solo pendenti).")
        history = False

    # 1. Carica le issue da revisionare
    if history:
        if issue_type == "asr":
            to_review = [iss for iss in load_asr_issues(lesson_dir) if iss.level in (ASRLevel.YELLOW, ASRLevel.RED)]
        else:
            to_review = list(load_science_issues(lesson_dir))
    else:
        pending_asr, pending_sci = get_pending_issues(lesson_dir)
        raw_issues = pending_asr if issue_type == "asr" else pending_sci

        to_review = []
        auto_accepted = []
        if issue_type == "asr":
            for iss in raw_issues:
                if should_auto_accept_asr(iss, auto_accept):
                    auto_accepted.append(iss)
                else:
                    to_review.append(iss)
            for iss in auto_accepted:
                record_decision(lesson_dir, iss.id, "accepted", resolved_text=iss.candidate, resolved_by="cli_auto")
        else:
            for iss in raw_issues:
                if should_auto_accept_science(iss, auto_accept):
                    auto_accepted.append(iss)
                else:
                    to_review.append(iss)
            for iss in auto_accepted:
                clean_fix = sanitize_suggested_fix(iss.suggested_fix)
                record_decision(lesson_dir, iss.id, "accepted", resolved_text=clean_fix, resolved_by="cli_auto")

        if auto_accepted:
            print(f"\n⚡ Auto-approvati {len(auto_accepted)} casi ({issue_type.upper()}) in base ai filtri CLI.")

    # 2. Se non resta nulla da rivedere
    if len(to_review) == 0:
        rem_asr, rem_sci = get_pending_issues(lesson_dir)
        if not rem_asr and not rem_sci:
            yaml_path = os.path.join(lesson_dir, "info.yaml")
            if os.path.isfile(yaml_path):
                try:
                    transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
                except Exception:
                    pass
        print(f"\n✨ Nessuna issue {issue_type.upper()} in attesa di revisione umana (tutte già risolte o auto-approvate).")
        return True

    # 3. Canale Telegram
    if channel == "telegram":
        if issue_type == "asr":
            start_review_via_telegram(lesson_dir, asr_to_review=to_review, sci_to_review=[])
        else:
            start_review_via_telegram(lesson_dir, asr_to_review=[], sci_to_review=to_review)
        return False

    # 4. Controllo TTY
    if not sys.stdin.isatty():
        print(f"\n⚠️  [HUMAN REVIEW REQUIRED] Ci sono {len(to_review)} issue {issue_type.upper()} che richiedono revisione umana.")
        print(f"Esegui 'rt review-{issue_type} \"{lesson_dir}\"' per completare la revisione (da un terminale interattivo, o con --channel telegram).")
        return False

    # 5. Sessione interattiva da terminale con indice mobile
    print(f"\n🔍 REVISIONE INTERATTIVA {issue_type.upper()} ({len(to_review)} casi{' [modalità history]' if history else ' pendenti'})")
    print("=" * 60)

    seg_data = load_segments_json(os.path.join(lesson_dir, "segments.json"))
    seg_by_id = {s.id: s for s in seg_data.segments}

    draft_path = get_draft_path(lesson_dir)
    draft = load_draft(lesson_dir) if os.path.isfile(draft_path) else None

    seg_to_unit = {}
    unit_by_id = {}
    if draft:
        for u in draft.units:
            unit_by_id[u.unit_id] = u
            for sid in u.source_segment_ids:
                seg_to_unit[sid] = u

    idx = 0
    total_count = len(to_review)
    interrupted = False
    decided_this_session = set()
    current_audio_proc: Optional[subprocess.Popen] = None
    audio_paused: bool = False
    temp_audio_clips: List[str] = []
    show_issue_details = True

    def _stop_audio():
        nonlocal current_audio_proc, audio_paused
        if current_audio_proc is not None and current_audio_proc.poll() is None:
            try:
                current_audio_proc.terminate()
            except Exception:
                pass
        current_audio_proc = None
        audio_paused = False

    try:
        while idx < total_count:
            iss = to_review[idx]
            ledger = load_ledger(lesson_dir)
            decisions_map = {d.issue_id: d for d in ledger.decisions}

            if issue_type == "asr":
                seg = seg_by_id.get(iss.segment_id)
                tc = seg.start_formatted if seg else "N/D"
                listen = f"{seg.start_formatted} - {seg.end_formatted}" if seg else "N/D"

                target_unit = seg_to_unit.get(iss.segment_id)
                unit_info = f"{target_unit.unit_id} - {target_unit.title}" if target_unit else "N/D"

                sentence = ""
                if target_unit:
                    sentence = extract_context_sentence(target_unit.content, iss.candidate, iss.source_text)
                if not sentence and draft:
                    for u in draft.units:
                        if target_unit and u.unit_id == target_unit.unit_id:
                            continue
                        s_found = extract_context_sentence(u.content, iss.candidate, iss.source_text)
                        if s_found:
                            sentence = s_found
                            unit_info = f"{u.unit_id} - {u.title}"
                            break

                if show_issue_details:
                    print(f"\n[{idx + 1}/{total_count}] ASR AMBIGUITY ({iss.level.value}) - ID: {iss.id}")
                    if unit_info != "N/D":
                        print(f"  📚 Unità:         {fix_mojibake(unit_info)}")
                    print(f"  ⏱ Timecode:      {tc}  (Ascolto audio: {listen})")
                    print(f"  🎙 ASR originale: \"{fix_mojibake(iss.source_text)}\"")
                    print(f"  💡 Proposta AI:   \"{fix_mojibake(iss.candidate)}\" (confidenza: {iss.confidence:.2f})")
                    print(f"  📝 Motivazione:   {fix_mojibake(iss.reason)}")
                    if sentence:
                        print(f"  📖 Contesto:      \"{fix_mojibake(sentence)}\"")
                    elif seg and seg.text_raw:
                        print(f"  📖 Contesto (trascrizione grezza, non trovato nel draft): \"{fix_mojibake(seg.text_raw)}\"")
                    if iss.id in decisions_map:
                        d = decisions_map[iss.id]
                        print(f"  📌 Ultima decisione: [{d.decision.upper()}] \"{fix_mojibake(d.resolved_text or '')}\"")

                print("\n  Azione [A=Accetta / R=Rifiuta / M=Modifica testo / P=Play audio / O=Riavvia audio / B=Indietro / S=Salta / Q=Esci]: ", end="", flush=True)
                raw_key = read_single_key()
                print(raw_key)
                choice = raw_key.strip().lower()

                if choice in ("a", "accetta", ""):
                    _stop_audio()
                    record_decision(lesson_dir, iss.id, "accepted", resolved_text=iss.candidate)
                    decided_this_session.add(iss.id)
                    print("  ✔ Approvato.")
                    idx += 1
                    show_issue_details = True
                elif choice in ("r", "rifiuta"):
                    _stop_audio()
                    record_decision(lesson_dir, iss.id, "rejected", resolved_text=iss.source_text)
                    decided_this_session.add(iss.id)
                    print("  ❌ Rifiutato (mantenuto testo originale).")
                    idx += 1
                    show_issue_details = True
                elif choice in ("m", "modifica"):
                    _stop_audio()
                    ctx_text = sentence if sentence else (seg.text_raw if seg and seg.text_raw else iss.candidate)
                    if iss.candidate and iss.candidate in ctx_text:
                        marked_body = ctx_text.replace(iss.candidate, f"»{iss.candidate}«", 1)
                    elif iss.source_text and iss.source_text in ctx_text:
                        marked_body = ctx_text.replace(iss.source_text, f"»{iss.source_text}«", 1)
                    else:
                        marked_body = f"»{iss.candidate}«\n{ctx_text}" if ctx_text != iss.candidate else f"»{iss.candidate}«"

                    initial_editor_content = (
                        "# Modifica solo il testo tra »« qui sotto. Il resto è solo contesto, non verrà usato.\n\n"
                        f"{marked_body}\n"
                    )
                    edited_res = edit_text_in_editor(initial_editor_content)
                    m = re.search(r"»(.*?)«", edited_res, re.DOTALL)
                    if m is None:
                        print("  ⚠️ Marcatori non trovati, nessuna modifica applicata.")
                        show_issue_details = False
                    else:
                        resolved = m.group(1).strip()
                        if resolved:
                            record_decision(lesson_dir, iss.id, "edited", resolved_text=resolved)
                            decided_this_session.add(iss.id)
                            print(f"  ✏ Modificato in: \"{resolved}\"")
                            idx += 1
                            show_issue_details = True
                        else:
                            print("  ⚠️ Testo vuoto tra i marcatori, nessuna modifica applicata.")
                            show_issue_details = False
                elif choice in ("p", "play", "audio"):
                    if current_audio_proc is None or current_audio_proc.poll() is not None:
                        audio_path = resolve_audio_path(lesson_dir)
                        seg = seg_by_id.get(iss.segment_id)
                        if not audio_path or not seg:
                            print("  ⚠️ File audio originale o timecode non disponibile.")
                        else:
                            start_s = max(0.0, seg.start_seconds - 5.0)
                            end_s = seg.end_seconds + 5.0
                            try:
                                clip_path = cut_clip(audio_path, start_s, end_s)
                                temp_audio_clips.append(clip_path)
                                current_audio_proc = play_clip_background(clip_path)
                                audio_paused = False
                                print(f"  🔊 Riproduzione audio in corso ({seg.start_formatted} - {seg.end_formatted})...")
                            except Exception as e:
                                print(f"  ⚠️ Impossibile riprodurre l'audio: {e}")
                    else:
                        if not audio_paused:
                            try:
                                current_audio_proc.send_signal(signal.SIGSTOP)
                                audio_paused = True
                                print("  ⏸ In pausa.")
                            except Exception as e:
                                print(f"  ⚠️ Errore pausa audio: {e}")
                        else:
                            try:
                                current_audio_proc.send_signal(signal.SIGCONT)
                                audio_paused = False
                                print("  ▶️ Ripreso.")
                            except Exception as e:
                                print(f"  ⚠️ Errore ripresa audio: {e}")
                    show_issue_details = False
                elif choice in ("o", "riavvia", "restart"):
                    _stop_audio()
                    audio_path = resolve_audio_path(lesson_dir)
                    seg = seg_by_id.get(iss.segment_id)
                    if not audio_path or not seg:
                        print("  ⚠️ File audio originale o timecode non disponibile.")
                    else:
                        start_s = max(0.0, seg.start_seconds - 5.0)
                        end_s = seg.end_seconds + 5.0
                        try:
                            clip_path = cut_clip(audio_path, start_s, end_s)
                            temp_audio_clips.append(clip_path)
                            current_audio_proc = play_clip_background(clip_path)
                            audio_paused = False
                            print(f"  🔊 Riproduzione audio in corso ({seg.start_formatted} - {seg.end_formatted})...")
                        except Exception as e:
                            print(f"  ⚠️ Impossibile riprodurre l'audio: {e}")
                    show_issue_details = False
                elif choice in ("b", "indietro", "back", "left"):
                    _stop_audio()
                    if idx == 0:
                        print("  ⚠️  Sei già al primo elemento, impossibile tornare oltre.")
                    else:
                        idx -= 1
                        prev_iss = to_review[idx]
                        if prev_iss.id in decided_this_session:
                            revert_last_decision(lesson_dir, prev_iss.id)
                            decided_this_session.discard(prev_iss.id)
                        print(f"  ◀️ Tornato all'issue precedente ({prev_iss.id}).")
                    show_issue_details = True
                elif choice in ("s", "salta", "skip", "right"):
                    _stop_audio()
                    print("  ⏭ Saltato.")
                    idx += 1
                    show_issue_details = True
                elif choice in ("q", "esci", "quit"):
                    _stop_audio()
                    print("  ⏹ Revisione interrotta. I progressi finora sono stati salvati.")
                    interrupted = True
                    break
                else:
                    show_issue_details = False

            else:  # science
                seg = seg_by_id.get(iss.segment_id) if iss.segment_id else None
                tc = seg.start_formatted if seg else "N/D"

                sci_unit = None
                if iss.unit_id and iss.unit_id in unit_by_id:
                    sci_unit = unit_by_id[iss.unit_id]
                elif iss.segment_id and iss.segment_id in seg_to_unit:
                    sci_unit = seg_to_unit[iss.segment_id]

                sci_unit_info = f"{sci_unit.unit_id} - {sci_unit.title}" if sci_unit else (iss.unit_id or "N/D")

                if show_issue_details:
                    print(f"\n[{idx + 1}/{total_count}] SCIENCE CRITIC ({iss.type.value}) - ID: {iss.id}")
                    if sci_unit_info != "N/D":
                        print(f"  📚 Unità:        {fix_mojibake(sci_unit_info)}")
                    print(f"  ⏱ Timecode:     {tc}")
                    print(f"  ⚠️ Affermazione: \"{fix_mojibake(iss.claim)}\"")
                    print(f"  🔬 Critica:      {fix_mojibake(iss.reason)}")
                    if iss.suggested_fix:
                        print(f"  💡 Correzione:   \"{fix_mojibake(iss.suggested_fix)}\"")
                    if iss.diplomatic_question:
                        print(f"  🤝 Domanda docente: \"{fix_mojibake(iss.diplomatic_question)}\"")
                    if sci_unit and sci_unit.content:
                        print(f"\n  📖 Contesto Draft (Unità {sci_unit.unit_id} intera):")
                        print("  " + "-" * 56)
                        for line in fix_mojibake(sci_unit.content).strip().split("\n"):
                            print(f"  {line}")
                        print("  " + "-" * 56)
                    if iss.id in decisions_map:
                        d = decisions_map[iss.id]
                        print(f"  📌 Ultima decisione: [{d.decision.upper()}] \"{fix_mojibake(d.resolved_text or '')}\"")

                print("\n  Azione [A=Applica correzione / M=Mantieni claim / E=Modifica testo / P=Play audio / O=Riavvia audio / B=Indietro / S=Salta / Q=Esci]: ", end="", flush=True)
                raw_key = read_single_key()
                print(raw_key)
                choice = raw_key.strip().lower()

                if choice in ("a", "accetta", "applica", ""):
                    _stop_audio()
                    clean_fix = sanitize_suggested_fix(iss.suggested_fix)
                    record_decision(lesson_dir, iss.id, "accepted", resolved_text=clean_fix)
                    decided_this_session.add(iss.id)
                    print("  ✔ Correzione scientifica applicata.")
                    idx += 1
                    show_issue_details = True
                elif choice in ("m", "mantieni", "rifiuta", "r"):
                    _stop_audio()
                    record_decision(lesson_dir, iss.id, "rejected", resolved_text=iss.claim)
                    decided_this_session.add(iss.id)
                    print("  ✔ Formulazione originale mantenuta.")
                    idx += 1
                    show_issue_details = True
                elif choice in ("e", "modifica"):
                    _stop_audio()
                    initial_editor_content = (
                        "# Modifica liberamente il testo qui sotto, sostituirà l'affermazione originale.\n\n"
                        f"{iss.claim}\n"
                    )
                    edited_res = edit_text_in_editor(initial_editor_content)
                    lines = [line for line in edited_res.splitlines() if not line.strip().startswith("#")]
                    resolved = "\n".join(lines).strip()
                    if resolved:
                        record_decision(lesson_dir, iss.id, "edited", resolved_text=resolved)
                        decided_this_session.add(iss.id)
                        print(f"  ✏ Modificato in: \"{resolved}\"")
                        idx += 1
                        show_issue_details = True
                    else:
                        print("  ⚠️ Nessuna modifica inserita.")
                        show_issue_details = False
                elif choice in ("p", "play", "audio"):
                    if current_audio_proc is None or current_audio_proc.poll() is not None:
                        audio_path = resolve_audio_path(lesson_dir)
                        start_s, end_s = None, None
                        if sci_unit:
                            start_seg = seg_by_id.get(sci_unit.start_segment_id)
                            end_seg = seg_by_id.get(sci_unit.end_segment_id)
                            if start_seg and end_seg:
                                start_s = start_seg.start_seconds
                                end_s = end_seg.end_seconds
                        if start_s is None and iss.segment_id:
                            s_seg = seg_by_id.get(iss.segment_id)
                            if s_seg:
                                start_s = s_seg.start_seconds
                                end_s = s_seg.end_seconds

                        if not audio_path or start_s is None or end_s is None:
                            print("  ⚠️ File audio originale o intervallo non disponibile.")
                        else:
                            try:
                                clip_path = cut_clip(audio_path, start_s, end_s)
                                temp_audio_clips.append(clip_path)
                                current_audio_proc = play_clip_background(clip_path)
                                audio_paused = False
                                print(f"  🔊 Riproduzione audio unità in corso ({start_s:.1f}s - {end_s:.1f}s)...")
                            except Exception as e:
                                print(f"  ⚠️ Impossibile riprodurre l'audio: {e}")
                    else:
                        if not audio_paused:
                            try:
                                current_audio_proc.send_signal(signal.SIGSTOP)
                                audio_paused = True
                                print("  ⏸ In pausa.")
                            except Exception as e:
                                print(f"  ⚠️ Errore pausa audio: {e}")
                        else:
                            try:
                                current_audio_proc.send_signal(signal.SIGCONT)
                                audio_paused = False
                                print("  ▶️ Ripreso.")
                            except Exception as e:
                                print(f"  ⚠️ Errore ripresa audio: {e}")
                    show_issue_details = False
                elif choice in ("o", "riavvia", "restart"):
                    _stop_audio()
                    audio_path = resolve_audio_path(lesson_dir)
                    start_s, end_s = None, None
                    if sci_unit:
                        start_seg = seg_by_id.get(sci_unit.start_segment_id)
                        end_seg = seg_by_id.get(sci_unit.end_segment_id)
                        if start_seg and end_seg:
                            start_s = start_seg.start_seconds
                            end_s = end_seg.end_seconds
                    if start_s is None and iss.segment_id:
                        s_seg = seg_by_id.get(iss.segment_id)
                        if s_seg:
                            start_s = s_seg.start_seconds
                            end_s = s_seg.end_seconds

                    if not audio_path or start_s is None or end_s is None:
                        print("  ⚠️ File audio originale o intervallo non disponibile.")
                    else:
                        try:
                            clip_path = cut_clip(audio_path, start_s, end_s)
                            temp_audio_clips.append(clip_path)
                            current_audio_proc = play_clip_background(clip_path)
                            audio_paused = False
                            print(f"  🔊 Riproduzione audio unità in corso ({start_s:.1f}s - {end_s:.1f}s)...")
                        except Exception as e:
                            print(f"  ⚠️ Impossibile riprodurre l'audio: {e}")
                    show_issue_details = False
                elif choice in ("b", "indietro", "back", "left"):
                    _stop_audio()
                    if idx == 0:
                        print("  ⚠️  Sei già al primo elemento, impossibile tornare oltre.")
                    else:
                        idx -= 1
                        prev_iss = to_review[idx]
                        if prev_iss.id in decided_this_session:
                            revert_last_decision(lesson_dir, prev_iss.id)
                            decided_this_session.discard(prev_iss.id)
                        print(f"  ◀️ Tornato all'issue precedente ({prev_iss.id}).")
                    show_issue_details = True
                elif choice in ("s", "salta", "skip", "right"):
                    _stop_audio()
                    print("  ⏭ Saltato.")
                    idx += 1
                    show_issue_details = True
                elif choice in ("q", "esci", "quit"):
                    _stop_audio()
                    print("  ⏹ Revisione interrotta. I progressi finora sono stati salvati.")
                    interrupted = True
                    break
                else:
                    show_issue_details = False
    finally:
        _stop_audio()
        for clip in temp_audio_clips:
            if os.path.exists(clip):
                try:
                    os.remove(clip)
                except Exception:
                    pass

    if interrupted:
        return False

    rem_asr, rem_sci = get_pending_issues(lesson_dir)
    if not rem_asr and not rem_sci:
        yaml_path = os.path.join(lesson_dir, "info.yaml")
        if os.path.isfile(yaml_path):
            try:
                transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
            except Exception:
                pass
        print("\n✨ Revisione completata. Esegui 'rt build <cartella>' per finalizzare.")

    return True
