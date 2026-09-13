"""
rt.pipeline.issue_review
Invio sequenziale delle issue ASR/scientifiche via Telegram e avanzamento della
coda dopo ogni decisione. Non blocca mai il chiamante: avvia la coda, manda la
prima issue, ritorna. Il resto della coda viene avanzato dal daemon dopo ogni
click/risposta (vedi rt/telegram/daemon.py).
"""
import os
import re
import subprocess
import time
from typing import List, Optional, Set, Dict, Any
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.widgets import Static

from rt.core.models import ScienceIssue, ScienceType
from rt.telegram import issue_queue as tg_queue
from rt.core.audio_clip import resolve_audio_path, cut_clip, play_clip_background
from rt.core.editor_edit import edit_text_in_editor
from rt.core.lesson_paths import lesson_path
from rt.pipeline.ledger import (
    load_ledger,
    record_decision,
    revert_last_decision,
    sanitize_suggested_fix,
)


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


def _prepare_issue_context(lesson_dir: str, issue, issue_type: str) -> dict:
    from rt.core.segments import load_segments_json
    from rt.pipeline.rewrite import load_draft, get_draft_path

    seg_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
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
        if os.path.isfile(yaml_path):
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

    ctx = _prepare_issue_context(lesson_dir, issue, issue_type)
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
                if tmp_clip and os.path.exists(tmp_clip):
                    try:
                        os.remove(tmp_clip)
                    except Exception:
                        pass


def should_auto_accept_science(iss: ScienceIssue, auto_accept: Optional[str]) -> bool:
    """Valuta se auto-accettare una critica scientifica in base ai flag CLI."""
    if not auto_accept:
        return False
    mode = str(auto_accept).lower()
    if mode in ("all", "true"):
        return True
    return False


def _build_science_panel(
    idx: int,
    total_count: int,
    iss: ScienceIssue,
    tc: str,
    sci_unit_info: str,
    sci_unit,
    decisions_map: dict,
    last_status: Optional[str] = None
) -> Panel:
    from rt.core.encoding import fix_mojibake

    iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
    is_asr_risk = (iss.type == ScienceType.ERR_ASR_ST) or (iss_type_str == "ERR_ASR_LLM")

    out = Text()

    if is_asr_risk:
        header_title = "🎙️ RISCHIO ASR (statistico)" if iss.type == ScienceType.ERR_ASR_ST else "🎙️ RISCHIO ASR (validato LLM)"
        out.append(f"[{idx + 1}/{total_count}] {header_title} - ID: {iss.id}\n")
        if sci_unit_info != "N/D":
            out.append(f"  📚 Unità:        {fix_mojibake(sci_unit_info)}\n")
        out.append(f"  ⏱ Timecode (stima): {tc}\n")
        out.append(f"  🎙️ Segmento raw sospetto: \"{fix_mojibake(iss.claim)}\"\n")
        out.append(f"  🔬 Critica:      {fix_mojibake(iss.reason)}\n")
        if iss.suggested_fix:
            out.append(f"  💡 Correzione:   \"{fix_mojibake(iss.suggested_fix)}\"\n")
        if iss.diplomatic_question:
            out.append(f"  🤝 Domanda docente: \"{fix_mojibake(iss.diplomatic_question)}\"\n")
        if sci_unit and sci_unit.content:
            out.append(f"\n  📖 Contesto Draft (Unità {sci_unit.unit_id} intera):\n")
            out.append("  " + "-" * 56 + "\n")
            for line in fix_mojibake(sci_unit.content).strip().split("\n"):
                out.append(f"  {line}\n")
            out.append("  " + "-" * 56 + "\n")
    else:
        out.append(f"[{idx + 1}/{total_count}] SCIENCE CRITIC ({iss_type_str}) - ID: {iss.id}\n")
        if sci_unit_info != "N/D":
            out.append(f"  📚 Unità:        {fix_mojibake(sci_unit_info)}\n")

        unit_text = fix_mojibake(sci_unit.content).strip() if (sci_unit and getattr(sci_unit, "content", None)) else None
        claim_clean = fix_mojibake(iss.claim or "").strip()
        has_fix = bool(iss.suggested_fix and iss.suggested_fix.strip())
        fix_clean = fix_mojibake(iss.suggested_fix.strip()) if has_fix else ""

        pos = unit_text.find(claim_clean) if (unit_text and claim_clean) else -1
        if unit_text and pos != -1:
            prefix = unit_text[:pos]
            matched_claim = unit_text[pos:pos+len(claim_clean)]
            suffix = unit_text[pos+len(claim_clean):]

            out.append("\n  ")
            out.append(prefix)
            out.append("- ", style="bold red")
            out.append(matched_claim, style="red")
            out.append(suffix)
            out.append("\n")
            if has_fix:
                out.append("  ")
                out.append("+ ", style="bold green")
                out.append(fix_clean, style="green")
                out.append("\n")
        else:
            if unit_text:
                out.append(f"\n  {unit_text}\n")
            out.append(f"\n  ⚠️ Affermazione: \"{claim_clean}\"\n")
            if has_fix:
                out.append(f"  💡 Correzione:   \"{fix_clean}\"\n")

        out.append(f"\n  🔬 Critica:      {fix_mojibake(iss.reason)}\n")
        if iss.diplomatic_question:
            out.append(f"  🤝 Domanda docente: \"{fix_mojibake(iss.diplomatic_question)}\"\n")

        if has_fix:
            out.append("  🔴 = claim attuale · 🟢 = correzione suggerita\n")

    if iss.id in decisions_map:
        d = decisions_map[iss.id]
        out.append(f"  📌 Ultima decisione: [{d.decision.upper()}] \"{fix_mojibake(d.resolved_text or '')}\"\n")

    if last_status:
        out.append(f"\n  {last_status}\n")

    if is_asr_risk:
        out.append("\n  Azione [A=Accetta / M=Modifica / P=Play audio / O=Riavvia audio / I=Indietro / S=Salta / Q=Esci]: ")
    else:
        out.append("\n  Azione [A=Accetta / R=Rifiuta / M=Modifica / P=Play audio / O=Riavvia audio / I=Indietro / S=Salta / Q=Esci]: ")

    return Panel(out, title=f"Science Review [{idx + 1}/{total_count}]", border_style="magenta")


class IssueReviewApp(App):
    """Schermata interattiva Textual per la revisione delle issue ASR / Science."""
    BINDINGS = [
        ("a", "approve_or_accept", "Accetta"),
        ("r", "reject", "Rifiuta"),
        ("m", "edit", "Modifica"),
        ("p", "toggle_audio", "Play / Pausa audio"),
        ("o", "restart_audio", "Riavvia audio"),
        ("i,b,left,up,k", "back", "Indietro"),
        ("s,right,down,j", "skip", "Salta"),
        ("q,escape", "quit", "Esci"),
    ]

    def __init__(
        self,
        lesson_dir: str,
        to_review: List[ScienceIssue],
        issue_type: str = "science",
        history: bool = False,
    ):
        super().__init__()
        self.lesson_dir = lesson_dir
        self.to_review: List[ScienceIssue] = to_review
        self.issue_type = issue_type
        self.history = history
        self.idx: int = 0
        self.decided_this_session: Set[str] = set()
        self.last_status: Optional[str] = None
        self.interrupted: bool = False

        from rt.core.segments import load_segments_json
        from rt.pipeline.rewrite import load_draft, get_draft_path

        seg_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
        self.seg_by_id = {s.id: s for s in seg_data.segments} if seg_data else {}

        draft_path = get_draft_path(lesson_dir)
        self.draft = load_draft(lesson_dir) if os.path.isfile(draft_path) else None

        self.seg_to_unit: Dict[str, Any] = {}
        self.unit_by_id: Dict[str, Any] = {}
        if self.draft:
            for u in self.draft.units:
                self.unit_by_id[u.unit_id] = u
                for sid in u.source_segment_ids:
                    self.seg_to_unit[sid] = u

        self.current_audio_proc: Optional[subprocess.Popen] = None
        self.audio_paused: bool = False
        self.audio_range_start: Optional[float] = None
        self.audio_range_end: Optional[float] = None
        self.audio_elapsed: float = 0.0
        self.audio_resumed_at: float = 0.0
        self.temp_audio_clips: List[str] = []

    def _get_time(self) -> float:
        return time.monotonic()

    def compose(self) -> ComposeResult:
        yield Static(self._render_panel(), id="panel_view")

    def on_mount(self) -> None:
        self.set_interval(0.2, self._check_audio_proc)

    def on_unmount(self) -> None:
        self._stop_audio()
        for clip in self.temp_audio_clips:
            if os.path.exists(clip):
                try:
                    os.remove(clip)
                except Exception:
                    pass

    def _stop_audio(self) -> None:
        if self.current_audio_proc is not None and self.current_audio_proc.poll() is None:
            try:
                self.current_audio_proc.terminate()
            except Exception:
                pass
        self.current_audio_proc = None
        self.audio_paused = False
        self.audio_range_start = None
        self.audio_range_end = None
        self.audio_elapsed = 0.0
        self.audio_resumed_at = 0.0

    def _check_audio_proc(self) -> None:
        if self.current_audio_proc is not None and self.current_audio_proc.poll() is not None:
            self.current_audio_proc = None
            self.audio_paused = False
            self.audio_range_start = None
            self.audio_range_end = None
            self.audio_elapsed = 0.0
            self.audio_resumed_at = 0.0

    def _render_panel(self) -> Panel:
        if self.idx >= len(self.to_review):
            return Panel(Text("✨ Tutte le issue sono state revisionate."), title="Revisione completata", border_style="green")

        iss = self.to_review[self.idx]
        ledger = load_ledger(self.lesson_dir)
        decisions_map = {d.issue_id: d for d in ledger.decisions}

        seg = self.seg_by_id.get(iss.segment_id) if iss.segment_id else None
        tc = seg.start_formatted if seg else "N/D"

        sci_unit = None
        if iss.unit_id and iss.unit_id in self.unit_by_id:
            sci_unit = self.unit_by_id[iss.unit_id]
        elif iss.segment_id and iss.segment_id in self.seg_to_unit:
            sci_unit = self.seg_to_unit[iss.segment_id]

        sci_unit_info = f"{sci_unit.unit_id} - {sci_unit.title}" if sci_unit else (iss.unit_id or "N/D")

        return _build_science_panel(
            self.idx,
            len(self.to_review),
            iss,
            tc,
            sci_unit_info,
            sci_unit,
            decisions_map,
            self.last_status,
        )

    def _update_display(self) -> None:
        try:
            widget = self.query_one("#panel_view", Static)
            widget.update(self._render_panel())
        except Exception:
            pass

    def action_approve_or_accept(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
        is_asr_risk = (iss.type == ScienceType.ERR_ASR_ST) or (iss_type_str == "ERR_ASR_LLM")
        self._stop_audio()
        if is_asr_risk:
            sci_unit = self.unit_by_id.get(iss.unit_id) if iss.unit_id else (self.seg_to_unit.get(iss.segment_id) if iss.segment_id else None)
            record_decision(self.lesson_dir, iss.id, "accepted", resolved_text=sci_unit.content if sci_unit else None)
            self.decided_this_session.add(iss.id)
            self.last_status = "✔ Testo dell'unità accettato."
        else:
            clean_fix = sanitize_suggested_fix(iss.suggested_fix)
            record_decision(self.lesson_dir, iss.id, "accepted", resolved_text=clean_fix)
            self.decided_this_session.add(iss.id)
            self.last_status = "✔ Correzione scientifica applicata."
        self.idx += 1
        if self.idx >= len(self.to_review):
            self.exit(True)
        else:
            self._update_display()

    def action_reject(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
        is_asr_risk = (iss.type == ScienceType.ERR_ASR_ST) or (iss_type_str == "ERR_ASR_LLM")
        if is_asr_risk:
            return
        self._stop_audio()
        record_decision(self.lesson_dir, iss.id, "rejected", resolved_text=iss.claim)
        self.decided_this_session.add(iss.id)
        self.last_status = "✔ Formulazione originale mantenuta."
        self.idx += 1
        if self.idx >= len(self.to_review):
            self.exit(True)
        else:
            self._update_display()


    def _do_edit_interaction(self, initial_content: str) -> str:
        return edit_text_in_editor(initial_content)

    def action_edit(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
        is_asr_risk = (iss.type == ScienceType.ERR_ASR_ST) or (iss_type_str == "ERR_ASR_LLM")
        self._stop_audio()
        sci_unit = self.unit_by_id.get(iss.unit_id) if iss.unit_id else (self.seg_to_unit.get(iss.segment_id) if iss.segment_id else None)

        if is_asr_risk:
            initial_editor_content = (
                "# Questa è l'intera unità come riscritta. Modificala liberamente per farla combaciare con l'audio: sostituirà l'intero contenuto dell'unità.\n\n"
                f"{(sci_unit.content if sci_unit else iss.claim)}\n"
            )
        else:
            initial_editor_content = (
                "# Modifica liberamente il testo qui sotto, sostituirà l'affermazione originale.\n\n"
                f"{iss.claim}\n"
            )

        edited_res = ""
        try:
            with self.suspend():
                edited_res = self._do_edit_interaction(initial_editor_content)
        except SuspendNotSupported:
            edited_res = self._do_edit_interaction(initial_editor_content)

        lines = [line for line in (edited_res or "").splitlines() if not line.strip().startswith("#")]
        resolved = "\n".join(lines).strip()
        if resolved:
            record_decision(self.lesson_dir, iss.id, "edited", resolved_text=resolved)
            self.decided_this_session.add(iss.id)
            self.last_status = f"✏ Modificato in: \"{resolved}\""
            self.idx += 1
            if self.idx >= len(self.to_review):
                self.exit(True)
            else:
                self._update_display()
        else:
            self.last_status = "⚠️ Nessuna modifica inserita."
            self._update_display()

    def action_toggle_audio(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        if not self.audio_paused:
            if self.current_audio_proc is not None and self.current_audio_proc.poll() is None:
                self.audio_elapsed += self._get_time() - self.audio_resumed_at
                try:
                    self.current_audio_proc.terminate()
                except Exception:
                    pass
                self.current_audio_proc = None
                self.audio_paused = True
            else:
                audio_path = resolve_audio_path(self.lesson_dir)
                start_s, end_s = None, None
                if iss.segment_id and iss.segment_id in self.seg_by_id:
                    s_seg = self.seg_by_id[iss.segment_id]
                    start_s = max(0.0, s_seg.start_seconds - 5.0)
                    end_s = s_seg.end_seconds + 5.0
                else:
                    sci_unit = self.unit_by_id.get(iss.unit_id) if iss.unit_id else (self.seg_to_unit.get(iss.segment_id) if iss.segment_id else None)
                    if sci_unit:
                        start_seg = self.seg_by_id.get(sci_unit.start_segment_id)
                        end_seg = self.seg_by_id.get(sci_unit.end_segment_id)
                        if start_seg and end_seg:
                            start_s = start_seg.start_seconds
                            end_s = end_seg.end_seconds

                if not audio_path or start_s is None or end_s is None:
                    self.last_status = "⚠️ File audio originale o intervallo non disponibile."
                else:
                    self.audio_range_start = start_s
                    self.audio_range_end = end_s
                    self.audio_elapsed = 0.0
                    try:
                        clip_path = cut_clip(audio_path, self.audio_range_start, self.audio_range_end)
                        self.temp_audio_clips.append(clip_path)
                        self.current_audio_proc = play_clip_background(clip_path)
                        self.audio_resumed_at = self._get_time()
                        self.audio_paused = False
                    except Exception as e:
                        self.last_status = f"⚠️ Impossibile riprodurre l'audio: {e}"
        else:
            audio_path = resolve_audio_path(self.lesson_dir)
            if not audio_path or self.audio_range_start is None or self.audio_range_end is None:
                self.last_status = "⚠️ File audio originale o intervallo non disponibile."
            else:
                new_start = self.audio_range_start + self.audio_elapsed
                try:
                    clip_path = cut_clip(audio_path, new_start, self.audio_range_end)
                    self.temp_audio_clips.append(clip_path)
                    self.current_audio_proc = play_clip_background(clip_path)
                    self.audio_resumed_at = self._get_time()
                    self.audio_paused = False
                except Exception as e:
                    self.last_status = f"⚠️ Impossibile riprodurre l'audio: {e}"

        self._update_display()

    def action_restart_audio(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        self._stop_audio()
        audio_path = resolve_audio_path(self.lesson_dir)
        start_s, end_s = None, None
        if iss.segment_id and iss.segment_id in self.seg_by_id:
            s_seg = self.seg_by_id[iss.segment_id]
            start_s = max(0.0, s_seg.start_seconds - 5.0)
            end_s = s_seg.end_seconds + 5.0
        else:
            sci_unit = self.unit_by_id.get(iss.unit_id) if iss.unit_id else (self.seg_to_unit.get(iss.segment_id) if iss.segment_id else None)
            if sci_unit:
                start_seg = self.seg_by_id.get(sci_unit.start_segment_id)
                end_seg = self.seg_by_id.get(sci_unit.end_segment_id)
                if start_seg and end_seg:
                    start_s = start_seg.start_seconds
                    end_s = end_seg.end_seconds

        if not audio_path or start_s is None or end_s is None:
            self.last_status = "⚠️ File audio originale o intervallo non disponibile."
        else:
            self.audio_range_start = start_s
            self.audio_range_end = end_s
            self.audio_elapsed = 0.0
            try:
                clip_path = cut_clip(audio_path, self.audio_range_start, self.audio_range_end)
                self.temp_audio_clips.append(clip_path)
                self.current_audio_proc = play_clip_background(clip_path)
                self.audio_resumed_at = self._get_time()
                self.audio_paused = False
            except Exception as e:
                self.last_status = f"⚠️ Impossibile riprodurre l'audio: {e}"

        self._update_display()

    def action_back(self) -> None:
        self._stop_audio()
        if self.idx == 0:
            self.last_status = "⚠️  Sei già al primo elemento, impossibile tornare oltre."
        else:
            self.idx -= 1
            prev_iss = self.to_review[self.idx]
            if prev_iss.id in self.decided_this_session:
                revert_last_decision(self.lesson_dir, prev_iss.id)
                self.decided_this_session.discard(prev_iss.id)
            self.last_status = f"◀️ Tornato all'issue precedente ({prev_iss.id})."
        self._update_display()

    def action_skip(self) -> None:
        self._stop_audio()
        self.last_status = "⏭ Saltato."
        self.idx += 1
        if self.idx >= len(self.to_review):
            self.exit(True)
        else:
            self._update_display()

    def action_quit(self) -> None:
        self._stop_audio()
        self.interrupted = True
        self.exit(False)



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
    from rt.core.state import transition_to, WorkflowState
    from rt.pipeline.ledger import (
        get_pending_issues,
        record_decision,
        sanitize_suggested_fix,
    )
    from rt.pipeline.review import load_science_issues

    if not channel:
        from rt.core.config import load_config as _load_cfg_for_channel
        channel = _load_cfg_for_channel().telegram.default_channel

    if channel == "telegram" and history:
        print("⚠️  La modalità --history è disponibile solo da terminale. Procedo in modalità normale (solo pendenti).")
        history = False

    # 1. Carica le issue da revisionare
    if history:
        to_review = list(load_science_issues(lesson_dir))
    else:
        _, raw_issues = get_pending_issues(lesson_dir)

        to_review = []
        auto_accepted = []
        for iss in raw_issues:
            if should_auto_accept_science(iss, auto_accept):
                auto_accepted.append(iss)
            else:
                to_review.append(iss)
        for iss in auto_accepted:
            clean_fix = sanitize_suggested_fix(iss.suggested_fix)
            record_decision(lesson_dir, iss.id, "accepted", resolved_text=clean_fix, resolved_by="cli_auto")

        if auto_accepted:
            print(f"\n⚡ Auto-approvati {len(auto_accepted)} casi in base ai filtri CLI.")

    # 2. Se non resta nulla da rivedere
    if len(to_review) == 0:
        rem_asr, rem_sci = get_pending_issues(lesson_dir)
        if not rem_asr and not rem_sci:
            yaml_path = lesson_path(lesson_dir, "info.yaml")
            if os.path.isfile(yaml_path):
                try:
                    transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
                except Exception:
                    pass
        print(f"\n✨ Nessuna issue in attesa di revisione umana (tutte già risolte o auto-approvate).")
        return True

    # 3. Canale Telegram
    if channel == "telegram":
        start_review_via_telegram(lesson_dir, sci_to_review=to_review)
        return False

    # 4. Controllo TTY
    if not sys.stdin.isatty():
        print(f"\n⚠️  [HUMAN REVIEW REQUIRED] Ci sono {len(to_review)} issue che richiedono revisione umana.")
        print(f"Esegui 'rt review \"{lesson_dir}\"' per completare la revisione (da un terminale interattivo, o con --channel telegram).")
        return False

    # 5. Sessione interattiva da terminale con Textual App
    app = IssueReviewApp(
        lesson_dir=lesson_dir,
        to_review=to_review,
        issue_type=issue_type,
        history=history,
    )
    completed = app.run()

    if not completed:
        return False

    rem_asr, rem_sci = get_pending_issues(lesson_dir)
    if not rem_asr and not rem_sci:
        yaml_path = lesson_path(lesson_dir, "info.yaml")
        if os.path.isfile(yaml_path):
            try:
                transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
            except Exception:
                pass
        print("\n✨ Revisione completata. Esegui 'rt build <cartella>' per finalizzare.")

    return True


