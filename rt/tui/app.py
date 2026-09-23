"""
rt.tui.app
Schermata principale di RT: dashboard delle lezioni trovate in 'telegram.lessons_root',
con azioni rapide sulla lezione selezionata. Le azioni richiamano gli stessi sottocomandi
CLI già usati da terminale (rt run/review/build/cost/recall/config), sospendendo
temporaneamente l'interfaccia Textual (App.suspend()) invece di reimplementarli.
"""
from typing import List, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, ListItem, ListView, MarkdownViewer, Static

from rt.core.idempotency import PhaseStatus
from rt.tui.data import PHASES, LessonSummary, badge_for_state, discover_lessons, load_markdown_preview

PHASE_ICON = {
    PhaseStatus.VALID: ("✓", "success"),
    PhaseStatus.PARTIAL: ("●", "warning"),
    PhaseStatus.MISSING: ("○", None),
    PhaseStatus.STALE: ("⚠", "warning"),
    PhaseStatus.INVALID: ("✗", "error"),
}


CAPTURED_SUBCOMMANDS = {
    "prepare",
    "rewrite",
    "build",
    "cost",
    "status",
    "add-images",
    "validate-outline",
    "validate-draft",
    "setup",
}

# Sottoinsieme di CAPTURED_SUBCOMMANDS il cui output è il vero scopo del comando (un report
# da leggere), non solo la conferma che un'azione è avvenuta: per questi la schermata NON si
# chiude da sola nemmeno su successo, altrimenti l'utente non fa in tempo a leggerlo.
REPORT_SUBCOMMANDS = {"cost", "status", "validate-outline", "validate-draft"}


def _phase_markup(phase: str, status: PhaseStatus) -> str:
    icon, token = PHASE_ICON.get(status, ("○", None))
    label = phase.upper()
    return f"[${token}]{icon} {label}[/]" if token else f"[dim]{icon} {label}[/]"


def build_header(lesson: LessonSummary) -> str:
    lines = [f"[b]{lesson.title}[/b]"]
    meta = lesson.subject or "—"
    if lesson.recorded:
        meta += f" · registrata {lesson.recorded}"
    meta += f" · aggiornata {lesson.when}"
    lines.append(f"[dim]{meta}[/dim]")
    return "\n".join(lines)


def build_stats(lesson: LessonSummary) -> str:
    stats = []
    if lesson.cost_total:
        stats.append(f"costo stimato [b]${lesson.cost_total:.2f}[/b]")
    if lesson.error:
        stats.append(f"[$error]⚠ stato illeggibile: {lesson.error}[/]")
    return "   ·   ".join(stats)


class LessonRow(ListItem):
    def __init__(self, lesson: LessonSummary) -> None:
        super().__init__()
        self.lesson = lesson

    def compose(self) -> ComposeResult:
        label, token = badge_for_state(self.lesson.state)
        with Horizontal(classes="lesson-row"):
            with Horizontal(classes="phase-strip"):
                for phase in PHASES:
                    status = next(
                        (st for ph, st in self.lesson.phase_status if ph == phase),
                        PhaseStatus.MISSING,
                    )
                    _, seg_token = PHASE_ICON.get(status, ("○", None))
                    yield Static("", classes=f"phase-seg phase-seg-{seg_token or 'missing'}")
            with Vertical(classes="lesson-text"):
                yield Static(self.lesson.title, classes="lesson-title")
                yield Static(f"{self.lesson.subject or '—'} · {self.lesson.when}", classes="lesson-sub")
            yield Static(f"[${token}]{label}[/]", classes="lesson-badge")


class TelegramStatusIndicator(Static):
    """Sensore cliccabile dello stato del demone Telegram nella topbar."""

    def on_click(self) -> None:
        if hasattr(self.app, "action_toggle_telegram_daemon"):
            self.app.action_toggle_telegram_daemon()


class PhaseLink(Static):
    """Testo cliccabile per una fase della pipeline nel pannello dettaglio lezione: appare come
    testo normale, con un effetto 'bottone' (sfondo/colore) solo quando ci si passa sopra col
    mouse — niente bordo o riquadro permanente."""

    def __init__(self, phase: str, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.phase = phase

    def on_click(self) -> None:
        if hasattr(self.app, "_handle_phase_action"):
            self.app._handle_phase_action(self.phase)


class IssuesLink(Static):
    """Testo cliccabile 'N issue in sospeso' nel pannello dettaglio lezione (stesso trattamento
    hover di PhaseLink)."""

    def on_click(self) -> None:
        if hasattr(self.app, "_handle_review_issues_action"):
            self.app._handle_review_issues_action()


class RTApp(App):
    """Dashboard principale di RT."""

    from rt.tui.commands_palette import CommandsProvider

    COMMANDS = App.COMMANDS | {CommandsProvider}
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
    ListItem:hover .lesson-row { background: $primary 15%; }
    ListItem:hover .lesson-title { color: $primary; text-style: bold; }

    .lesson-row { height: 3; padding: 0 1; }

    .phase-strip { width: 5; height: 3; margin-right: 1; }
    .phase-seg { width: 1; height: 1fr; }
    .phase-seg-success { background: $success; }
    .phase-seg-warning { background: $warning; }
    .phase-seg-error { background: $error; }
    .phase-seg-missing { background: $surface; }

    .lesson-text { width: 1fr; }
    .lesson-title { color: $text; text-wrap: nowrap; text-overflow: ellipsis; }
    .lesson-sub { color: $text-muted; text-wrap: nowrap; text-overflow: ellipsis; }
    .lesson-badge { width: auto; padding: 0 1; }

    #detail { width: 1fr; padding: 0 1; }

    #detail-info {
        height: auto; padding: 1 2; margin-bottom: 1;
        border: round $primary 25%; border-title-color: $primary;
    }
    #phase-stepper {
        height: auto; margin-top: 1; align: left middle;
    }
    .phase-link { width: auto; padding: 0 1; }
    .phase-link:hover { background: $primary 20%; text-style: bold; }
    .phase-sep { width: auto; color: $text-muted; }
    .issues-link { width: auto; padding: 0 1; margin-top: 1; }
    .issues-link:hover { background: $warning 20%; text-style: bold; }

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
        ("n", "run", "Nuova lezione"),
        ("g", "configure", "Configura"),
        ("r", "run", "Esegui/continua"),
        ("a", "recall", "Active recall"),
        ("t", "toggle_toc", "TOC"),
        ("?", "show_manual", "Manuale"),
        ("q", "quit", "Esci"),
    ]

    def __init__(self) -> None:
        super().__init__()
        from rt.core.ui_theme import apply_saved_theme
        from rt.cli import build_parser

        apply_saved_theme(self)
        self.lessons: List[LessonSummary] = []
        self.selected_lesson: Optional[LessonSummary] = None
        _, self.subcommand_parsers = build_parser()

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
            yield TelegramStatusIndicator("", id="status")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="› cerca lezione…", id="search")
                yield ListView(id="lesson-list")
            with Vertical(id="detail"):
                with Vertical(id="detail-info"):
                    yield Static("", id="detail-header")
                    with Horizontal(id="phase-stepper"):
                        for i, p in enumerate(PHASES):
                            if i > 0:
                                yield Static("  ─  ", classes="phase-sep")
                            yield PhaseLink(p, id=f"phase-link-{p}", classes="phase-link")
                    yield IssuesLink("", id="issues-link", classes="issues-link")
                    yield Static("", id="detail-stats")
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
            self.query_one("#detail-header", Static).update(
                "Nessuna lezione trovata in questa cartella."
                if root else
                "Configura 'telegram.lessons_root' in config/general.yaml (o premi 'g') "
                "per vedere qui le tue lezioni."
            )
            self.query_one("#detail-stats", Static).update("")
            self.query_one("#phase-stepper").display = False
            self.query_one("#issues-link").display = False
            await self.query_one(MarkdownViewer).document.update("")

    async def _show_lesson(self, lesson: LessonSummary) -> None:
        self.selected_lesson = lesson
        self.query_one("#detail-header", Static).update(build_header(lesson))
        self.query_one("#phase-stepper").display = True

        for p in PHASES:
            link = self.query_one(f"#phase-link-{p}", PhaseLink)
            status = next((st for ph, st in lesson.phase_status if ph == p), PhaseStatus.MISSING)
            link.update(_phase_markup(p, status))

        issues_link = self.query_one("#issues-link", IssuesLink)
        if lesson.pending_issues > 0:
            issues_link.display = True
            issues_link.update(f"[$warning]●[/] {lesson.pending_issues} issue in sospeso")
        else:
            issues_link.display = False

        self.query_one("#detail-stats", Static).update(build_stats(lesson))
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

    async def _execute(self, argv: List[str]) -> None:
        if argv and argv[0] in CAPTURED_SUBCOMMANDS:
            from rt.tui.command_output import CommandOutputScreen
            auto_dismiss = argv[0] not in REPORT_SUBCOMMANDS
            await self.push_screen_wait(CommandOutputScreen(argv, auto_dismiss_on_success=auto_dismiss))
        else:
            self._run_cli(argv)
        await self.refresh_lessons()

    @work
    async def _handle_phase_action(self, phase: str) -> None:
        if not self.selected_lesson:
            return
        lesson = self.selected_lesson
        status = next((st for ph, st in lesson.phase_status if ph == phase), PhaseStatus.MISSING)
        if status != PhaseStatus.VALID:
            await self._execute([phase, lesson.dir_path])
        else:
            from rt.tui.command_form import ConfirmModal
            msg = (
                f"La fase '{phase}' è già completata (VALID).\n\n"
                f"Rieseguirla forzerà la rigenerazione ignorando/sovrascrivendo i risultati precedenti (--force).\n\n"
                f"Continuare?"
            )
            confirmed = await self.push_screen_wait(ConfirmModal(msg, title=f"Riesecuzione {phase.upper()}"))
            if confirmed:
                await self._execute([phase, lesson.dir_path, "--force"])

    @work
    async def _handle_review_issues_action(self) -> None:
        if self.selected_lesson:
            await self._execute(["review", self.selected_lesson.dir_path])

    @work
    async def action_run(self) -> None:
        if self.selected_lesson:
            prefill = {"input": [self.selected_lesson.dir_path]}
        else:
            root = self._lessons_root()
            prefill = {"dest_dir": root} if root else {}

        parser = self.subcommand_parsers.get("run")
        if not parser:
            return
        from rt.tui.command_form import CommandFormScreen

        argv = await self.push_screen_wait(CommandFormScreen("run", parser, prefill=prefill))
        if argv:
            await self._execute(argv)

    async def action_recall(self) -> None:
        if self.selected_lesson:
            self._run_cli(["recall", self.selected_lesson.dir_path])
            await self.refresh_lessons()

    async def action_configure(self) -> None:
        self._run_cli(["config"])
        await self.refresh_lessons()

    def action_toggle_telegram_daemon(self) -> None:
        import shlex
        import subprocess
        from rt.telegram.daemon_status import get_rt_executable_path, is_daemon_running

        if is_daemon_running():
            self.notify("Il demone Telegram è già attivo.", title="Telegram")
            return

        rt_path = get_rt_executable_path()
        inner_cmd = f"{shlex.quote(rt_path)} telegram-daemon"
        escaped_inner_cmd = inner_cmd.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "Terminal" to do script "{escaped_inner_cmd}"'

        try:
            subprocess.Popen(["osascript", "-e", script])
            self.notify("Avvio demone Telegram in una nuova finestra Terminal…", title="Telegram")
        except Exception as exc:
            self.notify(f"Impossibile avviare il demone: {exc}", severity="error", title="Telegram")

        self.query_one("#status", Static).update(self._telegram_status_markup())

    def action_show_manual(self) -> None:
        from rt.tui.manual import ManualScreen
        self.push_screen(ManualScreen(self.subcommand_parsers))


def run_app() -> None:
    RTApp().run()

