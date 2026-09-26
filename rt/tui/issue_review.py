"""
rt.tui.issue_review
Review interattiva delle issue scientifiche da terminale (app Textual) e dispatch verso
Telegram per 'rt review' / 'rt run'. Le decisioni passano da rt.services.review_service.
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
from rt.core.audio_clip import resolve_audio_path, cut_clip, play_clip_background
from rt.core.editor_edit import edit_text_in_editor
from rt.core.lesson_paths import lesson_path
from rt.pipeline.issue_review import (
    _build_diff_strings,
    _is_no_diff_issue_type,
    should_auto_accept_science,
)
from rt.pipeline.ledger import load_ledger, sanitize_suggested_fix
from rt.services import review_service
from rt.telegram.review_channel import start_review_via_telegram
from rt.storage import fs


def record_decision(lesson_dir: str, issue_id: str, decision: str, resolved_text: Optional[str] = None, **kwargs):
    """Decisione presa dal terminale: passa dal servizio (lock per lezione, canale cli)."""
    return review_service.record_review_decision(lesson_dir, issue_id, decision, resolved_text, channel="cli", **kwargs)


def revert_last_decision(lesson_dir: str, issue_id: str) -> bool:
    try:
        review_service.undo_last_decision(lesson_dir, issue_id)
        return True
    except review_service.ReviewDecisionError:
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
        seg_data = load_segments_json(seg_path) if fs.isfile(seg_path) else None
        self.seg_by_id = {s.id: s for s in seg_data.segments} if seg_data else {}

        draft_path = get_draft_path(lesson_dir)
        self.draft = load_draft(lesson_dir) if fs.isfile(draft_path) else None

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
        if self.mpv_socket_path and fs.exists(self.mpv_socket_path):
            try:
                fs.remove(self.mpv_socket_path)
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
        seg_data = load_segments_json(seg_path) if fs.isfile(seg_path) else None
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
    from rt.pipeline.ledger import get_pending_issues
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
        auto_accepted, to_review = review_service.auto_accept_pending(lesson_dir, auto_accept, channel="cli")

        if auto_accepted:
            print(f"\n⚡ Auto-approvati {len(auto_accepted)} casi in base ai filtri CLI.")

    # 2. Se non resta nulla da rivedere
    if len(to_review) == 0:
        rem_asr, rem_sci = get_pending_issues(lesson_dir)
        if not rem_asr and not rem_sci:
            yaml_path = lesson_path(lesson_dir, "info.yaml")
            if fs.isfile(yaml_path):
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
        if fs.isfile(yaml_path):
            try:
                transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
            except Exception:
                pass
        print("\n✨ Revisione completata. Esegui 'rt build <cartella>' per finalizzare.")

    return True


