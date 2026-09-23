"""
rt.tui.commands_palette
Provider Textual per la Command Palette (ctrl+p) di RT: espone i comandi secondari
e di debug (setup, prepare, outline, rewrite, build, add-images, validate-outline, validate-draft)
aprendo il form CommandFormScreen corrispondente con prefill della lezione selezionata.
"""
import functools
from typing import Dict, List, Optional

from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.fuzzy import Matcher

PALETTE_SUBCOMMANDS: List[str] = [
    "setup",
    "prepare",
    "outline",
    "rewrite",
    "build",
    "add-images",
    "validate-outline",
    "validate-draft",
]


class CommandsProvider(Provider):
    """Provider per i comandi secondari e di pipeline in Command Palette."""

    def _get_command_help(self, name: str) -> str:
        parser = getattr(self.app, "subcommand_parsers", {}).get(name)
        if parser:
            return getattr(parser, "description", "") or getattr(parser, "help", "") or ""
        return ""

    def _trigger_command(self, name: str) -> None:
        self.app.run_worker(self._launch_command(name))

    async def _launch_command(self, name: str) -> None:
        parser = getattr(self.app, "subcommand_parsers", {}).get(name)
        if not parser:
            return
        from rt.tui.command_form import CommandFormScreen

        prefill: Dict[str, object] = {}
        selected = getattr(self.app, "selected_lesson", None)
        if selected:
            if name == "setup":
                root = getattr(self.app, "_lessons_root", lambda: None)()
                if root:
                    prefill = {"dest_dir": root}
            else:
                prefill = {"lesson_dir": selected.dir_path}
        elif name == "setup":
            root = getattr(self.app, "_lessons_root", lambda: None)()
            if root:
                prefill = {"dest_dir": root}

        argv = await self.app.push_screen_wait(CommandFormScreen(name, parser, prefill=prefill))
        if argv:
            await self.app._execute(argv)

    async def discover(self) -> Hits:
        for name in PALETTE_SUBCOMMANDS:
            candidate = f"Comando: {name}"
            help_text = self._get_command_help(name)
            yield DiscoveryHit(
                display=candidate,
                command=functools.partial(self._trigger_command, name),
                text=candidate,
                help=help_text,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name in PALETTE_SUBCOMMANDS:
            candidate = f"Comando: {name}"
            score = matcher.match(candidate)
            if score > 0:
                help_text = self._get_command_help(name)
                yield Hit(
                    score=score,
                    match_display=matcher.highlight(candidate),
                    command=functools.partial(self._trigger_command, name),
                    text=candidate,
                    help=help_text,
                )
