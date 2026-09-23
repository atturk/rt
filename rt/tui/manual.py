"""
rt.tui.manual
Schermata informativa 'Manuale' di RT: elenca le scorciatoie della dashboard
e la reference completa dei 15 comandi/flag CLI generata da argparse (build_parser).
"""
import argparse
from typing import Any, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, MarkdownViewer


def build_manual_markdown(bindings: Any, parsers: Dict[str, argparse.ArgumentParser]) -> str:
    """Genera la documentazione Markdown dai keybindings e dai parser CLI."""
    lines: List[str] = ["# Manuale & Reference RT\n"]
    lines.append("## Scorciatoie da tastiera (Dashboard)\n")
    lines.append("| Tasto | Azione | Descrizione |")
    lines.append("| :--- | :--- | :--- |")

    for b in bindings:
        if isinstance(b, tuple):
            key = b[0]
            action = b[1]
            desc = b[2] if len(b) > 2 else b[1]
        elif hasattr(b, "key"):
            key = b.key
            action = b.action
            desc = b.description or b.action
        else:
            continue
        lines.append(f"| `{key}` | `{action}` | {desc} |")
    lines.append("| `ctrl+p` | `command_palette` | Command Palette (comandi secondari / debug) |")
    lines.append("\n---\n")
    lines.append("## Reference Comandi CLI\n")
    lines.append("Tutti i sottocomandi CLI di RT generati direttamente dalle definizioni argparse:\n")

    for name, parser in parsers.items():
        desc = getattr(parser, "description", "") or getattr(parser, "help", "") or ""
        lines.append(f"### `rt {name}`\n")
        if desc:
            lines.append(f"{desc}\n")

        actions = [
            a for a in parser._actions
            if a.dest != "help" and not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))
        ]
        if actions:
            lines.append("**Opzioni e argomenti:**\n")
            for a in actions:
                opt_str = ", ".join(f"`{o}`" for o in a.option_strings) if a.option_strings else f"`{a.dest}`"
                help_str = a.help or "—"
                lines.append(f"- **{opt_str}**: {help_str}")
            lines.append("")
        else:
            lines.append("*Nessun argomento aggiuntivo richiesto.*\n")
        lines.append("")

    return "\n".join(lines)


class ManualScreen(Screen):
    """Schermata informativa con manuale, scorciatoie e reference CLI."""

    DEFAULT_CSS = """
    ManualScreen {
        background: $background;
    }
    #manual-container {
        height: 1fr;
        padding: 1 2;
    }
    #manual-viewer {
        height: 1fr;
        background: $surface;
        border: round $primary 25%;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Chiudi"),
        ("q", "dismiss", "Chiudi"),
        ("?", "dismiss", "Chiudi"),
    ]

    def __init__(self, parsers: Optional[Dict[str, argparse.ArgumentParser]] = None) -> None:
        super().__init__()
        self._parsers = parsers

    def compose(self) -> ComposeResult:
        with Vertical(id="manual-container"):
            yield MarkdownViewer("", show_table_of_contents=True, id="manual-viewer")
        yield Footer()

    async def on_mount(self) -> None:
        parsers = self._parsers or getattr(self.app, "subcommand_parsers", {})
        bindings = getattr(self.app, "BINDINGS", [])
        md_text = build_manual_markdown(bindings, parsers)
        viewer = self.query_one("#manual-viewer", MarkdownViewer)
        await viewer.document.update(md_text)

    def action_dismiss(self) -> None:
        self.app.pop_screen()
