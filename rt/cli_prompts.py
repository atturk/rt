"""
rt.cli_prompts
Prompt da terminale per i metadati di setup ('rt setup', 'rt run <audio>'). Il motore
(rt.pipeline.setup) non legge mai da stdin: riceve questo prompter solo quando la CLI è
collegata a un terminale interattivo.
"""
import sys
from typing import Optional

from rt.pipeline.setup import BOLD, CYAN, RED, RESET, YELLOW, SetupCancelled


def prompt_clean(message: str, default: str = "") -> str:
    """Prompt interattivo formattato per terminale."""
    if not sys.stdin.isatty():
        return default
    if default:
        prompt_text = f"{CYAN}?{RESET} {BOLD}{message}{RESET} [{YELLOW}{default}{RESET}]: "
    else:
        prompt_text = f"{CYAN}?{RESET} {BOLD}{message}{RESET}: "

    try:
        val = input(prompt_text).strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{YELLOW}Operazione annullata dall'utente.{RESET}")
        raise SetupCancelled("Operazione annullata dall'utente.")
    return val if val else default


def prompt_materia_select(default_guess: str = "") -> str:
    """Propone le materie già mappate in config (telegram.topics) come selezione,
    con una voce 'Altro' per materia libera. Degrada a prompt testuale libero se la
    config non è disponibile, topics è vuoto, questionary fallisce, o non siamo in un TTY."""
    try:
        from rt.core.config import load_config
        topic_keys = sorted(load_config().telegram.topics.keys())
    except Exception:
        topic_keys = []

    ALTRO = "➕ Altro (nuova materia)"
    if topic_keys:
        selection = None
        try:
            import questionary
            default_choice = default_guess.upper() if default_guess.upper() in topic_keys else None
            selection = questionary.select("Materia:", choices=topic_keys + [ALTRO], default=default_choice).ask()
        except Exception:
            selection = ALTRO
        if selection is None:
            print(f"\nOperazione annullata dall'utente.")
            raise SetupCancelled("Operazione annullata dall'utente.")
        if selection != ALTRO:
            return selection
    return prompt_clean("Materia (es. BIOINFORMATICA, BIOCHIMICA)", default=default_guess)


class CliSetupPrompter:
    """SetupPrompter per il terminale (stessi testi di sempre)."""

    def ask_audio(self) -> str:
        return prompt_clean("File audio (trascina il file qui o inserisci il percorso)")

    def ask_date(self, default: str) -> str:
        return prompt_clean("Data lezione (es. '26 sett 2025', '3 marzo 2024')", default=default)

    def invalid_date(self, raw: str) -> None:
        print(f"  {RED}Formato data non valido.{RESET}")

    def ask_materia(self, default_guess: str) -> str:
        return prompt_materia_select(default_guess=default_guess)


def terminal_setup_prompter() -> Optional[CliSetupPrompter]:
    """Il prompter solo se stdin è un terminale: altrimenti il setup usa i default."""
    return CliSetupPrompter() if sys.stdin.isatty() else None
