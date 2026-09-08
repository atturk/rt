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
            tg_client.send_message(tg_cfg, text="✨ Review completata. Esegui 'rt build' quando vuoi.", message_thread_id=thread_id)
        except TelegramConfigError:
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
        print("⚠️  Telegram non configurato: impossibile inviare l'issue. Usa 'rt review \"<cartella>\"' da terminale.")
        return

    runtime_cfg = load_config().telegram
    thread_id = resolve_topic_id(lesson_dir, runtime_cfg.topics)
    short_id = tg_registry.register_pending(
        lesson_dir, round_=queue.current_index, kind="issue_review", state_dir=runtime_cfg.state_dir,
        message_thread_id=thread_id, extra={"issue_id": issue_id, "issue_type": issue_type}
    )
    keyboard = tg_fmt.build_issue_keyboard(short_id, issue_type)
    try:
        tg_client.send_message(tg_cfg, text=text, reply_markup=keyboard, message_thread_id=thread_id)
    except tg_client.TelegramAPIError as e:
        print(f"⚠️  Invio issue a Telegram fallito: {e}")
