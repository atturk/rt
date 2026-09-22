"""
rt.tui.command_output
Schermata di esecuzione in-app per comandi a sola stampa (build, cost, ecc.),
che cattura lo stdout/stderr del sottoprocesso e lo renderizza in un RichLog
senza sospendere la TUI né stampare testo grezzo sul terminale.
"""
import asyncio
from typing import List, Optional

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static

from rt.telegram.daemon_status import get_rt_executable_path


class CommandOutputScreen(Screen[int]):
    """Schermata che esegue un comando CLI catturando l'output in un widget RichLog."""

    DEFAULT_CSS = """
    CommandOutputScreen {
        background: $background;
        padding: 1 2;
    }

    #cmd-header {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        border-bottom: solid $primary 40%;
        color: $text;
        text-style: bold;
    }

    #cmd-log-container {
        height: 1fr;
        border: round $primary 30%;
        background: $surface;
        padding: 0 1;
    }

    #cmd-log {
        height: 1fr;
        background: transparent;
    }

    #cmd-status {
        height: auto;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 1;
        color: $text-muted;
    }

    Footer {
        background: $panel;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_screen", "Chiudi / Esc"),
    ]

    def __init__(self, argv: List[str], auto_dismiss_on_success: bool = True) -> None:
        super().__init__()
        self.argv = argv
        self.auto_dismiss_on_success = auto_dismiss_on_success
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.exit_code: Optional[int] = None
        self._proc_running = True

    def compose(self) -> ComposeResult:
        yield Static(f"[b $primary]$ rt {' '.join(self.argv)}[/]", id="cmd-header")
        with Vertical(id="cmd-log-container"):
            yield RichLog(wrap=True, highlight=False, markup=False, auto_scroll=True, id="cmd-log")
        yield Static("[dim]● In esecuzione…[/]", id="cmd-status")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#cmd-log-container").border_title = "OUTPUT"
        self._run_command()

    @work
    async def _run_command(self) -> None:
        rt_path = get_rt_executable_path()
        log = self.query_one("#cmd-log", RichLog)
        status = self.query_one("#cmd-status", Static)

        try:
            # stdin=DEVNULL (non ereditato dal terminale reale della dashboard): alcuni
            # sottocomandi qui catturati (es. build -> _prompt_and_launch_daemon_if_needed)
            # hanno un prompt interattivo opzionale che si auto-disattiva controllando
            # sys.stdin.isatty(). Senza DEVNULL il sottoprocesso erediterebbe lo stesso
            # terminale reale della dashboard, isatty() risulterebbe vero, e il prompt
            # entrerebbe in conflitto con la lettura raw-mode di Textual (nessun input riga
            # per riga può mai arrivargli) restando bloccato per sempre.
            self.proc = await asyncio.create_subprocess_exec(
                rt_path,
                *self.argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as exc:
            self._proc_running = False
            self.exit_code = 1
            log.write(f"Impossibile avviare il comando: {exc}")
            status.update(f"[$error]✗ Errore di avvio: {exc}[/] — premi [b]Esc[/b] per tornare alla dashboard")
            return

        if self.proc.stdout is not None:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").rstrip("\r\n")
                log.write(decoded)

        await self.proc.wait()
        self.exit_code = self.proc.returncode if self.proc.returncode is not None else 0
        self._proc_running = False

        if self.exit_code == 0:
            if self.auto_dismiss_on_success:
                status.update("[$success]✓ Completato con successo[/]")
                await asyncio.sleep(0.6)
                try:
                    self.dismiss(0)
                except Exception:
                    pass
            else:
                status.update(
                    "[$success]✓ Completato con successo[/] — premi [b]Esc[/b] per tornare alla dashboard"
                )
        else:
            status.update(
                f"[$error]✗ Terminato con codice {self.exit_code}[/] — premi [b]Esc[/b] per tornare alla dashboard"
            )

    async def action_dismiss_screen(self) -> None:
        if self._proc_running and self.proc is not None and self.proc.returncode is None:
            try:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            except ProcessLookupError:
                pass
            except Exception:
                pass
            code = self.proc.returncode if self.proc and self.proc.returncode is not None else 130
        else:
            code = self.exit_code if self.exit_code is not None else 0

        try:
            self.dismiss(code)
        except Exception:
            pass
