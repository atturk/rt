"""
rt.pipeline.issue_review
Invio sequenziale delle issue ASR/scientifiche via Telegram e avanzamento della
coda dopo ogni decisione. Non blocca mai il chiamante: avvia la coda, manda la
prima issue, ritorna. Il resto della coda viene avanzato dal daemon dopo ogni
click/risposta (vedi rt/telegram/daemon.py).
"""
import os
import re
import json
import shutil
import subprocess
import time
from typing import List, Optional, Set, Dict, Any, Tuple
from rich.text import Text
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static, Button
from textual_diff_view import DiffView, LoadError

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


def _is_no_diff_issue_type(iss: ScienceIssue) -> bool:
    """Tipi di issue che non hanno un suggested_fix da mostrare come diff rosso/verde:
    vengono renderizzati con una descrizione piatta (stesso trattamento già riservato
    alle issue ASR)."""
    iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
    return iss.type in (ScienceType.ERR_ASR_ST, ScienceType.ERR_REWRITE_DRIFT) or iss_type_str in ("ERR_ASR_LLM", "ERR_REWRITE_DRIFT")


def _build_diff_strings(sci_unit: Any, iss: ScienceIssue) -> Tuple[str, str]:
    from rt.core.encoding import fix_mojibake

    unit_text = fix_mojibake(sci_unit.content).strip() if (sci_unit and getattr(sci_unit, "content", None)) else ""
    claim_clean = fix_mojibake(iss.claim or "").strip()
    has_fix = bool(iss.suggested_fix and iss.suggested_fix.strip())
    fix_clean = fix_mojibake(iss.suggested_fix.strip()) if has_fix else ""

    if not unit_text:
        return (claim_clean, fix_clean if has_fix else claim_clean)

    if not has_fix:
        return (unit_text, unit_text)

    pos = unit_text.find(claim_clean) if claim_clean else -1
    if pos != -1:
        code_orig = unit_text
        code_mod = unit_text[:pos] + fix_clean + unit_text[pos + len(claim_clean):]
        return (code_orig, code_mod)
    else:
        # Fallback se non c'è match posizionale esatto
        code_orig = f"{unit_text}\n\n[Affermazione]: {claim_clean}"
        code_mod = f"{unit_text}\n\n[Correzione]: {fix_clean}"
        return (code_orig, code_mod)


def _build_science_panel(
    idx: int,
    total_count: int,
    iss: ScienceIssue,
    tc: str,
    sci_unit_info: str,
    sci_unit,
    decisions_map: dict,
    last_status: Optional[str] = None
) -> Text:
    from rt.core.encoding import fix_mojibake

    is_asr_risk = _is_no_diff_issue_type(iss)

    out = Text()

    if is_asr_risk:
        if sci_unit_info != "N/D":
            out.append(f"  📚 Unità:        {fix_mojibake(sci_unit_info)}\n")
        if iss.type != ScienceType.ERR_REWRITE_DRIFT:
            out.append(f"  ⏱ Timecode (stima): {tc}\n")
            out.append(f"  🎙️ Segmento raw sospetto: \"{fix_mojibake(iss.claim)}\"\n")
        out.append(f"  🔬 Critica:      {fix_mojibake(iss.reason)}\n")
        if iss.suggested_fix:
            out.append(f"  💡 Correzione:   \"{fix_mojibake(iss.suggested_fix)}\"\n")
        if iss.diplomatic_question:
            out.append(f"  🤝 Domanda docente: \"{fix_mojibake(iss.diplomatic_question)}\"\n")
        if sci_unit and getattr(sci_unit, "content", None):
            out.append(f"\n  📖 Contesto Draft (Unità {sci_unit.unit_id} intera):\n")
            out.append("  " + "-" * 56 + "\n")
            for line in fix_mojibake(sci_unit.content).strip().split("\n"):
                out.append(f"  {line}\n")
            out.append("  " + "-" * 56 + "\n")
    else:
        if sci_unit_info != "N/D":
            out.append(f"  📚 Unità:        {fix_mojibake(sci_unit_info)}\n")
        out.append(f"  🔬 Critica:      {fix_mojibake(iss.reason)}\n")
        if iss.diplomatic_question:
            out.append(f"  🤝 Domanda docente: \"{fix_mojibake(iss.diplomatic_question)}\"\n")

    if iss.id in decisions_map:
        d = decisions_map[iss.id]
        out.append(f"  📌 Ultima decisione: [{d.decision.upper()}] \"{fix_mojibake(d.resolved_text or '')}\"\n")

    if last_status:
        out.append(f"\n  {last_status}\n")

    return out


class IssueReviewApp(App):
    """Schermata interattiva Textual per la revisione delle issue ASR / Science."""

    TITLE = "RT · Revisione Issue"

    BINDINGS = [
        ("a", "approve_or_accept", "Accetta"),
        ("r", "reject", "Rifiuta"),
        ("m", "edit", "Modifica"),
        ("p", "toggle_audio", "Player audio"),
        ("i,b,left,up,k", "back", "Indietro"),
        ("s,right,down,j", "skip", "Salta"),
        ("q,escape", "quit", "Esci"),
    ]

    CSS = """
    Screen {
        background: $background;
    }

    #topbar {
        height: 3;
        background: $panel;
        border-bottom: solid $primary 20%;
        padding: 0 2;
        align: left middle;
    }

    #topbar #brand {
        width: 1fr;
        color: $text;
        text-style: bold;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    #topbar #progress {
        width: auto;
        color: $text-muted;
        text-wrap: nowrap;
    }

    #body {
        height: 1fr;
        padding: 1 2;
    }

    #issue-card {
        height: 1fr;
        background: $surface;
        border: round $primary 25%;
        border-title-color: $primary;
        padding: 1 2;
    }

    #issue-card:focus-within {
        border: round $primary;
    }

    #diff-container {
        height: 1fr;
        min-height: 8;
        border-bottom: solid $primary 15%;
        margin-bottom: 1;
    }

    #diff-view {
        height: 1fr;
    }

    #content-container {
        height: auto;
        max-height: 14;
        overflow-y: auto;
    }

    #issue-content {
        height: auto;
    }

    #actions-bar {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    #actions-bar Button {
        margin: 0 1;
        min-width: 10;
        height: 3;
    }

    Footer {
        background: $panel;
    }
    """

    def __init__(
        self,
        lesson_dir: str,
        to_review: List[ScienceIssue],
        issue_type: str = "science",
        history: bool = False,
    ):
        super().__init__()
        from rt.core.ui_theme import apply_saved_theme
        apply_saved_theme(self)
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

        seg_path = lesson_path(lesson_dir, "segments.json")
        seg_data = load_segments_json(seg_path) if os.path.isfile(seg_path) else None
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

        self.mpv_proc: Optional[subprocess.Popen] = None
        self.mpv_socket_path: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="topbar"):
                yield Static("🔬 RT · Revisione Issue", id="brand")
                yield Static(self._get_progress_label(), id="progress")
            with Vertical(id="body"):
                with Vertical(id="issue-card") as card:
                    card.border_title = self._get_card_title()
                    with Vertical(id="diff-container"):
                        yield DiffView("original", "modified", "", "", split=True, id="diff-view")
                    with VerticalScroll(id="content-container"):
                        yield Static(self._get_issue_content(), id="issue-content")
                    with Horizontal(id="actions-bar"):
                        yield Button("Accetta", variant="success", id="btn-accept")
                        yield Button("Rifiuta", variant="error", id="btn-reject")
                        yield Button("Modifica", id="btn-edit")
                        yield Button("◀ Indietro", id="btn-back")
                        yield Button("Salta ▶", id="btn-skip")
                        yield Button("Player audio", id="btn-audio")
            yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(0.2, self._check_audio_proc)
        await self._update_display()

    def on_unmount(self) -> None:
        self._stop_audio()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-accept":
            await self.action_approve_or_accept()
        elif button_id == "btn-reject":
            await self.action_reject()
        elif button_id == "btn-edit":
            await self.action_edit()
        elif button_id == "btn-back":
            await self.action_back()
        elif button_id == "btn-skip":
            await self.action_skip()
        elif button_id == "btn-audio":
            await self.action_toggle_audio()

    def _stop_audio(self) -> None:
        if self.mpv_proc is not None:
            if self.mpv_proc.poll() is None:
                try:
                    self.mpv_proc.terminate()
                except Exception:
                    pass
            self.mpv_proc = None
        if self.mpv_socket_path and os.path.exists(self.mpv_socket_path):
            try:
                os.remove(self.mpv_socket_path)
            except Exception:
                pass
            self.mpv_socket_path = None

    def _check_audio_proc(self) -> None:
        if self.mpv_proc is not None and self.mpv_proc.poll() is not None:
            self.mpv_proc = None

    def _get_progress_label(self) -> str:
        total = len(self.to_review)
        if total == 0:
            return "[0/0]"
        current = min(self.idx + 1, total)
        return f"[{current}/{total}]"

    def _get_card_title(self) -> str:
        if self.idx >= len(self.to_review):
            return "Revisione completata"
        iss = self.to_review[self.idx]
        iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
        is_asr_risk = _is_no_diff_issue_type(iss)
        if is_asr_risk:
            if iss.type == ScienceType.ERR_ASR_ST:
                header_title = "🎙️ RISCHIO ASR (statistico)"
            elif iss.type == ScienceType.ERR_REWRITE_DRIFT:
                header_title = "🔀 DERIVA RIELABORAZIONE (Jev)"
            else:
                header_title = "🎙️ RISCHIO ASR (validato LLM)"
            return f"{header_title} · ID: {iss.id}"
        return f"SCIENCE CRITIC ({iss_type_str}) · ID: {iss.id}"

    def _get_issue_content(self) -> Text:
        if self.idx >= len(self.to_review):
            return Text("✨ Tutte le issue sono state revisionate.", style="green bold")

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

    async def _update_display(self) -> None:
        try:
            card = self.query_one("#issue-card", Vertical)
            card.border_title = self._get_card_title()

            prog = self.query_one("#progress", Static)
            prog.update(self._get_progress_label())

            content = self.query_one("#issue-content", Static)
            content.update(self._get_issue_content())

            diff_container = self.query_one("#diff-container", Vertical)
            btn_reject = self.query_one("#btn-reject", Button)

            if self.idx >= len(self.to_review):
                diff_container.display = False
                return

            iss = self.to_review[self.idx]
            is_asr = _is_no_diff_issue_type(iss)

            if is_asr:
                diff_container.display = False
                btn_reject.display = False
            else:
                diff_container.display = True
                btn_reject.display = True
                sci_unit = None
                if iss.unit_id and iss.unit_id in self.unit_by_id:
                    sci_unit = self.unit_by_id[iss.unit_id]
                elif iss.segment_id and iss.segment_id in self.seg_to_unit:
                    sci_unit = self.seg_to_unit[iss.segment_id]
                try:
                    code_orig, code_mod = _build_diff_strings(sci_unit, iss)
                    # DiffView non ricalcola il diff se si aggiornano code_original/
                    # code_modified su un'istanza già montata (verificato: i contatori
                    # +N/-N restano a 0 nonostante il contenuto sia genuinamente diverso) —
                    # l'unico modo affidabile è costruire un'istanza nuova con il contenuto
                    # già nel costruttore, stesso principio del remount MarkdownViewer.
                    old_diff_view = self.query_one("#diff-view", DiffView)
                    await old_diff_view.remove()
                    new_diff_view = DiffView(
                        "originale", "corretto", code_orig, code_mod, split=True, id="diff-view"
                    )
                    await diff_container.mount(new_diff_view)
                except Exception:
                    pass
        except Exception:
            pass

    async def action_approve_or_accept(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        is_asr_risk = _is_no_diff_issue_type(iss)
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
            await self._update_display()

    async def action_reject(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        is_asr_risk = _is_no_diff_issue_type(iss)
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
            await self._update_display()

    def _do_edit_interaction(self, initial_content: str) -> str:
        return edit_text_in_editor(initial_content)

    async def action_edit(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]
        is_asr_risk = _is_no_diff_issue_type(iss)
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
                await self._update_display()
        else:
            self.last_status = "⚠️ Nessuna modifica inserita."
            await self._update_display()

    async def action_toggle_audio(self) -> None:
        if self.idx >= len(self.to_review):
            return
        iss = self.to_review[self.idx]

        if self.mpv_proc is not None and self.mpv_proc.poll() is None:
            self._stop_audio()
            self.last_status = "⏹ Player audio chiuso."
            await self._update_display()
            return

        if not shutil.which("mpv"):
            self.last_status = "⚠️ Installa mpv con 'brew install mpv' per usare il player companion."
            await self._update_display()
            return

        sci_unit = self.unit_by_id.get(iss.unit_id) if iss.unit_id else (self.seg_to_unit.get(iss.segment_id) if iss.segment_id else None)
        if not sci_unit:
            self.last_status = "⚠️ Unità non associata all'issue."
            await self._update_display()
            return

        from rt.core.audio_clip import get_or_create_unit_clip, calculate_mpv_geometry
        from rt.core.segments import load_segments_json
        seg_path = lesson_path(self.lesson_dir, "segments.json")
        seg_data = load_segments_json(seg_path) if os.path.isfile(seg_path) else None
        segments = seg_data.segments if seg_data else []

        try:
            clip_path = get_or_create_unit_clip(self.lesson_dir, sci_unit, segments)
        except Exception as e:
            self.last_status = f"⚠️ Errore ritaglio clip audio: {e}"
            await self._update_display()
            return

        if not clip_path:
            self.last_status = "⚠️ File audio originale o clip non disponibile."
            await self._update_display()
            return

        geometry = calculate_mpv_geometry()
        import uuid
        self.mpv_socket_path = f"/tmp/rt_mpv_{os.getpid()}_{uuid.uuid4().hex[:8]}.sock"

        cmd = [
            "mpv",
            f"--input-ipc-server={self.mpv_socket_path}",
            f"--geometry={geometry}",
            f"--title=RT Review: {sci_unit.unit_id} - {sci_unit.title}",
            "--force-window=yes",
            clip_path,
        ]

        try:
            self.mpv_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.last_status = f"▶️ Player audio aperto per unità {sci_unit.unit_id}."
        except Exception as e:
            self.last_status = f"⚠️ Impossibile avviare mpv: {e}"

        await self._update_display()

    async def action_back(self) -> None:
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
        await self._update_display()

    async def action_skip(self) -> None:
        self._stop_audio()
        self.last_status = "⏭ Saltato."
        self.idx += 1
        if self.idx >= len(self.to_review):
            self.exit(True)
        else:
            await self._update_display()

    def action_quit(self) -> None:
        self._stop_audio()
        self.last_status = "⏹ Revisione interrotta."
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


