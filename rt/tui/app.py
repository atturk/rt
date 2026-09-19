"""
rt.tui.app
Schermata principale di RT: dashboard delle lezioni trovate in 'telegram.lessons_root',
con azioni rapide sulla lezione selezionata. Le azioni richiamano gli stessi sottocomandi
CLI già usati da terminale (rt run/review/build/cost/recall/config), sospendendo
temporaneamente l'interfaccia Textual (App.suspend()) invece di reimplementarli.
"""
from typing import List, Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, ListItem, ListView, MarkdownViewer, Static

from rt.core.idempotency import PhaseStatus
from rt.tui.data import LessonSummary, badge_for_state, discover_lessons, load_markdown_preview

PHASE_ICON = {
    PhaseStatus.VALID: ("✓", "success"),
    PhaseStatus.PARTIAL: ("●", "warning"),
    PhaseStatus.MISSING: ("○", None),
    PhaseStatus.STALE: ("⚠", "warning"),
    PhaseStatus.INVALID: ("✗", "error"),
}


def build_stepper(lesson: LessonSummary) -> str:
    parts = []
    for phase, status in lesson.phase_status:
        icon, token = PHASE_ICON.get(status, ("○", None))
        label = phase.upper()
        parts.append(f"[${token}]{icon} {label}[/]" if token else f"[dim]{icon} {label}[/]")
    return "  ─  ".join(parts)


def build_detail(lesson: LessonSummary) -> str:
    lines = [f"[b]{lesson.title}[/b]"]
    meta = lesson.subject or "—"
    if lesson.recorded:
        meta += f" · registrata {lesson.recorded}"
    meta += f" · aggiornata {lesson.when}"
    lines.append(f"[dim]{meta}[/dim]")
    lines.append("")
    lines.append(build_stepper(lesson))
    stats = []
    if lesson.pending_issues:
        stats.append(f"[$warning]●[/] {lesson.pending_issues} issue in sospeso")
    if lesson.cost_total:
        stats.append(f"costo stimato [b]${lesson.cost_total:.2f}[/b]")
    if lesson.error:
        stats.append(f"[$error]⚠ stato illeggibile: {lesson.error}[/]")
    if stats:
        lines.append("")
        lines.append("   ·   ".join(stats))
    return "\n".join(lines)


class LessonRow(ListItem):
    def __init__(self, lesson: LessonSummary) -> None:
        _, token = badge_for_state(lesson.state)
        super().__init__(classes=f"status-{token}")
        self.lesson = lesson

    def compose(self) -> ComposeResult:
        label, token = badge_for_state(self.lesson.state)
        with Horizontal(classes="lesson-row"):
            with Vertical(classes="lesson-text"):
                yield Static(self.lesson.title, classes="lesson-title")
                yield Static(f"{self.lesson.subject or '—'} · {self.lesson.when}", classes="lesson-sub")
            yield Static(f"[${token}]{label}[/]", classes="lesson-badge")


class NewLessonModal(ModalScreen[Optional[str]]):
    """Chiede il percorso di un file audio per avviare 'rt run --dest-dir <root>'."""

    DEFAULT_CSS = """
    NewLessonModal { align: center middle; }
    NewLessonModal > #dialog {
        width: 74; height: auto; padding: 1 2;
        border: round $primary; background: $surface;
    }
    NewLessonModal > #dialog > Static { margin-bottom: 1; }
    """
    BINDINGS = [("escape", "cancel", "Annulla")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[b]Nuova lezione[/b]  [dim]— percorso file audio, INVIO per confermare, ESC per annullare[/dim]")
            yield Input(placeholder="/percorso/alla/lezione.m4a", id="audio-path")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RTApp(App):
    """Dashboard principale di RT."""

    TITLE = "RT"

    CSS = """
    Screen { background: $background; }

    #topbar {
        height: 3; background: $panel; border-bottom: solid $primary 20%;
        padding: 0 2; align: left middle;
    }
    #topbar #brand { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    #topbar #status { width: auto; color: $text-muted; text-wrap: nowrap; }

    #body { height: 1fr; }

    #sidebar {
        width: 46; background: $surface; border: round $primary 25%;
        border-title-color: $primary; padding: 1;
    }
    #sidebar:focus-within { border: round $primary; }
    #search { border: none; height: 1; padding: 0 1; margin-bottom: 1; }

    ListView { background: transparent; height: 1fr; }
    ListItem { padding: 0; background: transparent; }

    .lesson-row { height: 3; padding: 0 1; }
    .status-primary .lesson-row { border-left: thick $primary; }
    .status-secondary .lesson-row { border-left: thick $secondary; }
    .status-accent .lesson-row { border-left: thick $accent; }
    .status-success .lesson-row { border-left: thick $success; }
    .status-warning .lesson-row { border-left: thick $warning; }
    .status-error .lesson-row { border-left: thick $error; }

    .lesson-text { width: 1fr; }
    .lesson-title { color: $text; text-wrap: nowrap; text-overflow: ellipsis; }
    .lesson-sub { color: $text-muted; text-wrap: nowrap; text-overflow: ellipsis; }
    .lesson-badge { width: auto; padding: 0 1; }

    #detail { width: 1fr; padding: 0 1; }

    #detail-info {
        height: auto; padding: 1 2; margin-bottom: 1;
        border: round $primary 25%; border-title-color: $primary;
    }

    #markdown-panel {
        height: 1fr; border: round $primary 25%; border-title-color: $primary;
    }
    MarkdownViewer { height: 1fr; background: $surface; }
    MarkdownTableOfContents {
        width: 30;
        max-width: 35;
        border-right: vkey $primary 20%;
    }

    Footer { background: $panel; }
    """

    BINDINGS = [
        ("/", "focus_search", "Cerca"),
        ("n", "new_lesson", "Nuova lezione"),
        ("g", "configure", "Configura"),
        ("r", "run_next", "Esegui/continua"),
        ("v", "review", "Revisiona"),
        ("b", "build", "Build"),
        ("c", "cost", "Costi"),
        ("a", "recall", "Active recall"),
        ("t", "toggle_toc", "TOC"),
        ("q", "quit", "Esci"),
    ]

    def __init__(self) -> None:
        super().__init__()
        from rt.core.ui_theme import apply_saved_theme
        apply_saved_theme(self)
        self.lessons: List[LessonSummary] = []
        self.selected_lesson: Optional[LessonSummary] = None

    def _lessons_root(self) -> Optional[str]:
        try:
            from rt.core.config import load_config
            cfg = load_config()
        except Exception:
            return None
        root = getattr(getattr(cfg, "telegram", None), "lessons_root", None)
        return root.strip() if root and str(root).strip() else None

    def compose(self) -> ComposeResult:
        from rt.core.config import _default_project_root
        from rt.core.version import get_current_version
        version = get_current_version(_default_project_root())

        with Horizontal(id="topbar"):
            yield Static(
                f"[b $primary]RT[/]  [dim]│[/]  rielaborazione trascritti & active recall  "
                f"[dim]v{version}[/dim]",
                id="brand",
            )
            yield Static("", id="status")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="› cerca lezione…", id="search")
                yield ListView(id="lesson-list")
            with Vertical(id="detail"):
                with Vertical(id="detail-info"):
                    yield Static("", id="detail-body")
                with Vertical(id="markdown-panel"):
                    yield MarkdownViewer("", show_table_of_contents=True)
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#sidebar").border_title = "LEZIONI"
        self.query_one("#detail-info").border_title = "DETTAGLIO LEZIONE"
        self.query_one("#markdown-panel").border_title = "ANTEPRIMA MARKDOWN"
        await self.refresh_lessons()
        self.query_one("#lesson-list", ListView).focus()

    def _telegram_status_markup(self) -> str:
        from rt.telegram.daemon_status import is_daemon_running
        if is_daemon_running():
            return "[$success]●[/] telegram attivo"
        return "[dim]○ telegram non attivo[/]"

    async def refresh_lessons(self) -> None:
        root = self._lessons_root()
        self.query_one("#status", Static).update(self._telegram_status_markup())

        self.lessons = discover_lessons(root)
        list_view = self.query_one("#lesson-list", ListView)
        await list_view.clear()
        for lesson in self.lessons:
            await list_view.append(LessonRow(lesson))

        if self.lessons:
            list_view.index = 0
            await self._show_lesson(self.lessons[0])
        else:
            self.selected_lesson = None
            self.query_one("#detail-body", Static).update(
                "Nessuna lezione trovata in questa cartella."
                if root else
                "Configura 'telegram.lessons_root' in config/general.yaml (o premi 'g') "
                "per vedere qui le tue lezioni."
            )
            await self.query_one(MarkdownViewer).document.update("")

    async def _show_lesson(self, lesson: LessonSummary) -> None:
        self.selected_lesson = lesson
        self.query_one("#detail-body", Static).update(build_detail(lesson))
        await self.query_one(MarkdownViewer).document.update(load_markdown_preview(lesson.dir_path))

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, LessonRow):
            await self._show_lesson(event.item.lesson)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_toggle_toc(self) -> None:
        try:
            viewer = self.query_one(MarkdownViewer)
            viewer.show_table_of_contents = not viewer.show_table_of_contents
        except Exception:
            pass

    def _run_cli(self, argv: List[str]) -> None:
        """Sospende la dashboard e lancia 'rt <sottocomando>' in un sottoprocesso separato
        per evitare conflitti con l'event loop di asyncio (asyncio.run() annidato),
        poi riprende. Un errore nel sottocomando non deve far crashare la dashboard:
        viene mostrato e si torna qui."""
        import subprocess
        from rt.telegram.daemon_status import get_rt_executable_path

        rt_path = get_rt_executable_path()
        with self.suspend():
            print(f"\n$ rt {' '.join(argv)}\n")
            try:
                proc = subprocess.run([rt_path, *argv])
                if proc.returncode != 0:
                    print(f"\n[rt {' '.join(argv)} terminato con codice {proc.returncode}]")
            except KeyboardInterrupt:
                print("\n⏹ Interrotto.")
            except FileNotFoundError:
                print(f"\n❌ Eseguibile non trovato: {rt_path}")
            except Exception as exc:  # confine verso errori imprevisti di spawn: non deve uccidere la dashboard
                print(f"\n❌ Errore inatteso: {exc}")
            try:
                input("\nPremi INVIO per tornare alla dashboard RT…")
            except (KeyboardInterrupt, EOFError):
                pass

    async def action_run_next(self) -> None:
        if self.selected_lesson:
            self._run_cli(["run", self.selected_lesson.dir_path])
            await self.refresh_lessons()

    async def action_review(self) -> None:
        if self.selected_lesson:
            self._run_cli(["review", self.selected_lesson.dir_path])
            await self.refresh_lessons()

    async def action_build(self) -> None:
        if self.selected_lesson:
            self._run_cli(["build", self.selected_lesson.dir_path])
            await self.refresh_lessons()

    async def action_cost(self) -> None:
        if self.selected_lesson:
            self._run_cli(["cost", self.selected_lesson.dir_path, "--split"])

    async def action_recall(self) -> None:
        if self.selected_lesson:
            self._run_cli(["recall", self.selected_lesson.dir_path])
            await self.refresh_lessons()

    async def action_configure(self) -> None:
        self._run_cli(["config"])
        await self.refresh_lessons()

    async def action_new_lesson(self) -> None:
        root = self._lessons_root()
        if not root:
            self.notify(
                "Configura prima 'telegram.lessons_root' in config/general.yaml (premi 'g').",
                severity="warning",
            )
            return
        path = await self.push_screen_wait(NewLessonModal())
        if path:
            self._run_cli(["run", path, "--dest-dir", root])
            await self.refresh_lessons()


def run_app() -> None:
    RTApp().run()
