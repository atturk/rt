"""
rt.tui.command_form
Infrastruttura per generare dinamicamente form Textual sopra i parser argparse
esistenti in rt.cli, garantendo che i flag e le opzioni non siano mai duplicati a mano.
"""
import argparse
import shlex
from typing import Any, Dict, List, Optional, Tuple, Union

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, Footer, Input, Select, Static


def _get_primary_opt_string(action: argparse.Action) -> str:
    """Restituisce l'opzione primaria (preferendo flag lunghi '--...')."""
    if not action.option_strings:
        return ""
    long_opts = [opt for opt in action.option_strings if opt.startswith("--")]
    if long_opts:
        return long_opts[0]
    return action.option_strings[0]


class ConfirmModal(ModalScreen[bool]):
    """Modale generico di conferma con messaggio parametrico."""

    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > #dialog {
        width: 64; height: auto; padding: 1 2;
        border: round $primary; background: $surface;
    }
    ConfirmModal > #dialog > #title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    ConfirmModal > #dialog > #message {
        margin-bottom: 1;
    }
    ConfirmModal > #dialog > Horizontal {
        align: right middle;
        height: auto;
        margin-top: 1;
    }
    ConfirmModal > #dialog > Horizontal > Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("y", "confirm", "Conferma"),
        ("n", "cancel", "Annulla"),
        ("escape", "cancel", "Annulla"),
    ]

    def __init__(self, message: str, title: str = "Conferma operazione") -> None:
        super().__init__()
        self.message = message
        self.title_text = title

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.title_text, id="title")
            yield Static(self.message, id="message")
            with Horizontal():
                yield Button("Annulla (Esc/N)", id="btn-cancel", variant="default")
                yield Button("Conferma (Y)", id="btn-confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#btn-confirm", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class CommandFormScreen(Screen[Optional[List[str]]]):
    """Schermata di configurazione form per un sottocomando generata da un ArgumentParser."""

    DEFAULT_CSS = """
    CommandFormScreen {
        background: $background;
        padding: 1 2;
    }

    #form-header {
        height: 3;
        padding: 0 1;
        margin-bottom: 1;
        border-bottom: solid $primary 20%;
    }

    #form-scroll {
        height: 1fr;
        margin-bottom: 1;
    }

    .field-group {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: $surface;
        border: round $primary 20%;
    }

    .field-label {
        color: $text;
        text-style: bold;
    }

    .field-help {
        color: $text-muted;
        margin-bottom: 1;
    }

    #form-actions {
        height: 3;
        align: right middle;
        border-top: solid $primary 20%;
        padding-top: 1;
    }

    #form-actions > Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Annulla"),
        ("ctrl+s", "submit", "Esegui"),
    ]

    def __init__(
        self,
        subcommand_name: str,
        parser: argparse.ArgumentParser,
        prefill: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self.subcommand_name = subcommand_name
        self.parser = parser
        self.prefill: Dict[str, Any] = prefill or {}

    def compose(self) -> ComposeResult:
        desc = self.parser.description or getattr(self.parser, "help", "") or ""
        header_text = f"[b $primary]RT[/]  [dim]│[/]  Comando: [b]{self.subcommand_name}[/b]"
        if desc and desc != argparse.SUPPRESS:
            header_text += f"  [dim]— {desc}[/dim]"

        yield Static(header_text, id="form-header")

        with VerticalScroll(id="form-scroll"):
            for action in self.parser._actions:
                if (
                    action.dest == "help"
                    or isinstance(action, argparse._HelpAction)
                    or isinstance(action, argparse._SubParsersAction)
                ):
                    continue

                help_text = action.help if action.help and action.help != argparse.SUPPRESS else ""
                opt_display = "/".join(action.option_strings) if action.option_strings else action.dest

                with Vertical(classes="field-group"):
                    yield Static(f"[b]{opt_display}[/b]", classes="field-label")
                    if help_text:
                        yield Static(f"[dim]{help_text}[/dim]", classes="field-help")

                    if isinstance(action, argparse.BooleanOptionalAction):
                        init_val = self.prefill.get(action.dest, action.default)
                        val = bool(init_val) if init_val is not None else True
                        yield Checkbox(f"Abilita {opt_display}", value=val, id=f"chk_{action.dest}")

                    elif isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)) or (
                        action.const in (True, False) and action.default in (False, True)
                    ):
                        if isinstance(action, argparse._StoreFalseAction) or action.const is False:
                            init_val = bool(
                                self.prefill.get(
                                    action.dest,
                                    action.default if action.default is not None else True,
                                )
                            )
                        else:
                            init_val = bool(self.prefill.get(action.dest, action.default or False))
                        yield Checkbox(f"Attiva {opt_display}", value=init_val, id=f"chk_{action.dest}")

                    elif action.nargs == "?" and action.const is not None:
                        if action.choices is not None:
                            choices = list(action.choices)
                            options: List[Tuple[str, str]] = [("Non specificato / disattivato", "__NONE__")] + [
                                (f"{c} (default se attivo)" if c == action.const else str(c), str(c))
                                for c in choices
                            ]
                            init_val = "__NONE__"
                            if action.dest in self.prefill:
                                v = self.prefill[action.dest]
                                if v is True or v == action.const:
                                    init_val = str(action.const)
                                elif v in choices:
                                    init_val = str(v)
                                elif v is not None and v is not False:
                                    init_val = str(v)
                            elif action.default is not None:
                                init_val = str(action.default)
                            yield Select(options, value=init_val, allow_blank=False, id=f"sel_{action.dest}")
                        else:
                            options_custom: List[Tuple[str, str]] = [
                                ("Disattivato / Non specificato", "__NONE__"),
                                (f"Attivo (default: {action.const})", "__CONST__"),
                                ("Valore personalizzato", "__CUSTOM__"),
                            ]
                            init_sel = "__NONE__"
                            init_inp = str(action.const)
                            if action.dest in self.prefill:
                                v = self.prefill[action.dest]
                                if v is None or v is False:
                                    init_sel = "__NONE__"
                                elif v is True or v == action.const:
                                    init_sel = "__CONST__"
                                else:
                                    init_sel = "__CUSTOM__"
                                    init_inp = str(v)
                            elif action.default is not None:
                                if action.default == action.const:
                                    init_sel = "__CONST__"
                                else:
                                    init_sel = "__CUSTOM__"
                                    init_inp = str(action.default)

                            with Horizontal():
                                yield Select(
                                    options_custom,
                                    value=init_sel,
                                    allow_blank=False,
                                    id=f"sel_{action.dest}",
                                )
                                yield Input(
                                    value=init_inp,
                                    placeholder=f"es. {action.const}",
                                    id=f"inp_{action.dest}",
                                )

                    elif action.choices is not None:
                        choices = list(action.choices)
                        if action.default is None:
                            options_choice: List[Tuple[str, str]] = [
                                ("Predefinito / Non specificato", "__NONE__")
                            ] + [(str(c), str(c)) for c in choices]
                            init_val = "__NONE__"
                        else:
                            options_choice = [(str(c), str(c)) for c in choices]
                            init_val = str(action.default)
                        if action.dest in self.prefill:
                            v = self.prefill[action.dest]
                            if v is not None and str(v) in [opt[1] for opt in options_choice]:
                                init_val = str(v)
                        yield Select(options_choice, value=init_val, allow_blank=False, id=f"sel_{action.dest}")

                    elif action.nargs in ("+", "*"):
                        if action.dest in self.prefill:
                            v = self.prefill[action.dest]
                            if isinstance(v, (list, tuple)):
                                init_str = " ".join(str(x) for x in v)
                            else:
                                init_str = str(v or "")
                        elif action.default and action.default != argparse.SUPPRESS:
                            if isinstance(action.default, (list, tuple)):
                                init_str = " ".join(str(x) for x in action.default)
                            else:
                                init_str = str(action.default)
                        else:
                            init_str = ""
                        yield Input(value=init_str, placeholder=help_text or opt_display, id=f"inp_{action.dest}")

                    else:
                        if action.dest in self.prefill:
                            v = self.prefill[action.dest]
                            init_str = str(v) if v is not None else ""
                        elif action.default and action.default != argparse.SUPPRESS:
                            init_str = str(action.default)
                        else:
                            init_str = ""
                        yield Input(value=init_str, placeholder=help_text or opt_display, id=f"inp_{action.dest}")

        with Horizontal(id="form-actions"):
            yield Button("Annulla (Esc)", id="btn-cancel", variant="default")
            yield Button("Esegui (Ctrl+S)", id="btn-submit", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        for widget in self.query("Input, Checkbox, Select"):
            widget.focus()
            break

    def build_argv(self) -> List[str]:
        flags: List[str] = []
        positionals: List[str] = []

        for action in self.parser._actions:
            if (
                action.dest == "help"
                or isinstance(action, argparse._HelpAction)
                or isinstance(action, argparse._SubParsersAction)
            ):
                continue

            is_pos = not bool(action.option_strings)
            primary_opt = _get_primary_opt_string(action)

            if isinstance(action, argparse.BooleanOptionalAction):
                chk = self.query_one(f"#chk_{action.dest}", Checkbox)
                pos_opt = [opt for opt in action.option_strings if not opt.startswith("--no-")][0]
                neg_opt = [opt for opt in action.option_strings if opt.startswith("--no-")][0]
                flags.append(pos_opt if chk.value else neg_opt)

            elif isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)) or (
                action.const in (True, False) and action.default in (False, True)
            ):
                chk = self.query_one(f"#chk_{action.dest}", Checkbox)
                if isinstance(action, argparse._StoreFalseAction) or action.const is False:
                    if not chk.value:
                        flags.append(primary_opt)
                else:
                    if chk.value:
                        flags.append(primary_opt)

            elif action.nargs == "?" and action.const is not None:
                if action.choices is not None:
                    sel = self.query_one(f"#sel_{action.dest}", Select)
                    val = sel.value
                    if val and val != "__NONE__" and val != Select.BLANK:
                        flags.extend([primary_opt, str(val)])
                else:
                    sel = self.query_one(f"#sel_{action.dest}", Select)
                    val = sel.value
                    if val == "__CONST__":
                        flags.append(primary_opt)
                    elif val == "__CUSTOM__":
                        inp = self.query_one(f"#inp_{action.dest}", Input)
                        v = inp.value.strip()
                        if v:
                            flags.extend([primary_opt, v])
                        else:
                            flags.append(primary_opt)

            elif action.choices is not None:
                sel = self.query_one(f"#sel_{action.dest}", Select)
                val = sel.value
                if val and val != "__NONE__" and val != Select.BLANK:
                    if is_pos:
                        positionals.append(str(val))
                    else:
                        flags.extend([primary_opt, str(val)])

            elif action.nargs in ("+", "*"):
                inp = self.query_one(f"#inp_{action.dest}", Input)
                val = inp.value.strip()
                if val:
                    try:
                        tokens = shlex.split(val)
                    except ValueError:
                        tokens = val.split()
                    if tokens:
                        if is_pos:
                            positionals.extend(tokens)
                        else:
                            flags.extend([primary_opt, *tokens])

            else:
                inp = self.query_one(f"#inp_{action.dest}", Input)
                val = inp.value.strip()
                if val:
                    if is_pos:
                        positionals.append(val)
                    else:
                        flags.extend([primary_opt, val])

        return [self.subcommand_name] + flags + positionals

    @work
    async def action_submit(self) -> None:
        argv = self.build_argv()
        if "--force" in argv:
            confirmed = await self.app.push_screen_wait(
                ConfirmModal(
                    "Sei sicuro di voler forzare l'esecuzione (--force)? I risultati precedenti verranno ignorati o sovrascritti.",
                    title="Conferma flag --force",
                )
            )
            if not confirmed:
                return
        self.dismiss(argv)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            self.action_submit()
        elif event.button.id == "btn-cancel":
            self.action_cancel()
