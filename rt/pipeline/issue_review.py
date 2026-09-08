"""
rt.pipeline.issue_review
Invio sequenziale delle issue ASR/scientifiche via Telegram e avanzamento della
coda dopo ogni decisione. Non blocca mai il chiamante: avvia la coda, manda la
prima issue, ritorna. Il resto della coda viene avanzato dal daemon dopo ogni
click/risposta (vedi rt/telegram/daemon.py).
"""
import os
from typing import List
from rt.core.models import ASRIssue, ScienceIssue
from rt.telegram import issue_queue as tg_queue


def start_review_via_telegram(lesson_dir: str, asr_to_review: List[ASRIssue], sci_to_review: List[ScienceIssue]) -> None:
    try:
        from rt.telegram.config import load_telegram_config, resolve_topic_id
        from rt.core.config import load_config
        from rt.telegram import session as tg_session

        tg_cfg = load_telegram_config()
        runtime_cfg = load_config().telegram
        thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)
        tg_session.start_session(runtime_cfg.state_dir, tg_cfg.chat_id, thread_id, "issue_review", lesson_dir)
    except Exception:
        pass

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
    seg_by_id = {s.id: s for s in seg_data.segments}
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
        return {
            "timecode": seg.start_formatted if seg else "N/D",
            "listen_range": f"{seg.start_formatted} - {seg.end_formatted}" if seg else "N/D",
            "unit_info": f"{target_unit.unit_id} - {target_unit.title}" if target_unit else None,
            "sentence": sentence,
        }
    else:
        seg = seg_by_id.get(issue.segment_id) if issue.segment_id else None
        sci_unit = unit_by_id.get(issue.unit_id) if issue.unit_id else (seg_to_unit.get(issue.segment_id) if issue.segment_id else None)
        return {
            "timecode": seg.start_formatted if seg else "N/D",
            "unit_info": f"{sci_unit.unit_id} - {sci_unit.title}" if sci_unit else issue.unit_id,
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

            print(f"\n[{idx + 1}/{total_count}] ASR AMBIGUITY ({iss.level.value}) - ID: {iss.id}")
            if unit_info != "N/D":
                print(f"  📚 Unità:         {fix_mojibake(unit_info)}")
            print(f"  ⏱ Timecode:      {tc}  (Ascolto audio: {listen})")
            print(f"  🎙 ASR originale: \"{fix_mojibake(iss.source_text)}\"")
            print(f"  💡 Proposta AI:   \"{fix_mojibake(iss.candidate)}\" (confidenza: {iss.confidence:.2f})")
            print(f"  📝 Motivazione:   {fix_mojibake(iss.reason)}")
            if sentence:
                print(f"  📖 Contesto:      \"{fix_mojibake(sentence)}\"")
            if iss.id in decisions_map:
                d = decisions_map[iss.id]
                print(f"  📌 Ultima decisione: [{d.decision.upper()}] \"{fix_mojibake(d.resolved_text or '')}\"")

            choice = input("\n  Azione [A=Accetta / R=Rifiuta / M=Modifica testo / B=Indietro / S=Salta / Q=Esci]: ").strip().lower()
            if choice in ("a", "accetta", ""):
                record_decision(lesson_dir, iss.id, "accepted", resolved_text=iss.candidate)
                decided_this_session.add(iss.id)
                print("  ✔ Approvato.")
                idx += 1
            elif choice in ("r", "rifiuta"):
                record_decision(lesson_dir, iss.id, "rejected", resolved_text=iss.source_text)
                decided_this_session.add(iss.id)
                print("  ❌ Rifiutato (mantenuto testo originale).")
                idx += 1
            elif choice in ("m", "modifica"):
                custom = input("  Inserisci correzione personalizzata: ").strip()
                if custom:
                    record_decision(lesson_dir, iss.id, "edited", resolved_text=custom)
                    decided_this_session.add(iss.id)
                    print(f"  ✏ Modificato in: \"{custom}\"")
                    idx += 1
                else:
                    print("  ⚠️ Nessuna modifica inserita.")
            elif choice in ("b", "indietro", "back"):
                if idx == 0:
                    print("  ⚠️  Sei già al primo elemento, impossibile tornare oltre.")
                else:
                    idx -= 1
                    prev_iss = to_review[idx]
                    if prev_iss.id in decided_this_session:
                        revert_last_decision(lesson_dir, prev_iss.id)
                        decided_this_session.discard(prev_iss.id)
                    print(f"  ◀️ Tornato all'issue precedente ({prev_iss.id}).")
            elif choice in ("q", "esci", "quit"):
                print("  ⏹ Revisione interrotta. I progressi finora sono stati salvati.")
                interrupted = True
                break
            else:
                print("  ⏭ Saltato.")
                idx += 1

        else:  # science
            seg = seg_by_id.get(iss.segment_id) if iss.segment_id else None
            tc = seg.start_formatted if seg else "N/D"

            sci_unit = None
            if iss.unit_id and iss.unit_id in unit_by_id:
                sci_unit = unit_by_id[iss.unit_id]
            elif iss.segment_id and iss.segment_id in seg_to_unit:
                sci_unit = seg_to_unit[iss.segment_id]

            sci_unit_info = f"{sci_unit.unit_id} - {sci_unit.title}" if sci_unit else (iss.unit_id or "N/D")

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

            choice = input("\n  Azione [A=Applica correzione / M=Mantieni claim / E=Modifica testo / B=Indietro / S=Salta / Q=Esci]: ").strip().lower()
            if choice in ("a", "accetta", "applica", ""):
                clean_fix = sanitize_suggested_fix(iss.suggested_fix)
                record_decision(lesson_dir, iss.id, "accepted", resolved_text=clean_fix)
                decided_this_session.add(iss.id)
                print("  ✔ Correzione scientifica applicata.")
                idx += 1
            elif choice in ("m", "mantieni", "rifiuta", "r"):
                record_decision(lesson_dir, iss.id, "rejected", resolved_text=iss.claim)
                decided_this_session.add(iss.id)
                print("  ✔ Formulazione originale mantenuta.")
                idx += 1
            elif choice in ("e", "modifica"):
                custom = input("  Inserisci testo corretto: ").strip()
                if custom:
                    record_decision(lesson_dir, iss.id, "edited", resolved_text=custom)
                    decided_this_session.add(iss.id)
                    print(f"  ✏ Modificato in: \"{custom}\"")
                    idx += 1
                else:
                    print("  ⚠️ Nessuna modifica inserita.")
            elif choice in ("b", "indietro", "back"):
                if idx == 0:
                    print("  ⚠️  Sei già al primo elemento, impossibile tornare oltre.")
                else:
                    idx -= 1
                    prev_iss = to_review[idx]
                    if prev_iss.id in decided_this_session:
                        revert_last_decision(lesson_dir, prev_iss.id)
                        decided_this_session.discard(prev_iss.id)
                    print(f"  ◀️ Tornato all'issue precedente ({prev_iss.id}).")
            elif choice in ("q", "esci", "quit"):
                print("  ⏹ Revisione interrotta. I progressi finora sono stati salvati.")
                interrupted = True
                break
            else:
                print("  ⏭ Saltato.")
                idx += 1

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
