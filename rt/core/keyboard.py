"""
rt.core.keyboard
Lettura a singolo tasto da terminale senza richiedere Invio.
Supporta macOS / Linux (termios/tty) con fallback su input() per ambienti non interattivi o di test.
"""

import contextlib
import sys

UNKNOWN_KEY = "\x00UNKNOWN"


@contextlib.contextmanager
def raw_mode():
    """Attiva la modalità raw del terminale per tutta la durata del blocco `with`,
    ripristinando le impostazioni originali all'uscita. No-op (yield False) se stdin non è una tty."""
    if not sys.stdin.isatty():
        yield False
        return
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    except Exception:
        yield False
        return

    try:
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _parse_tty_key() -> str:
    import select
    ch = sys.stdin.read(1)
    if ch == "\x03":  # Ctrl+C
        raise KeyboardInterrupt()
    if ch in ("\r", "\n"):
        return ""
    if ch == "\x1b":
        try:
            r, _, _ = select.select([sys.stdin], [], [], 0.15)
            if r:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    r2, _, _ = select.select([sys.stdin], [], [], 0.15)
                    if r2:
                        ch3 = sys.stdin.read(1)
                        if ch3 == "D":
                            return "LEFT"
                        elif ch3 == "C":
                            return "RIGHT"
                        return UNKNOWN_KEY
                    return UNKNOWN_KEY
                return UNKNOWN_KEY
            return UNKNOWN_KEY
        except Exception:
            return UNKNOWN_KEY
    return ch


def _fallback_input_key() -> str:
    try:
        val = input()
        if val == "\x1b[D":
            return "LEFT"
        if val == "\x1b[C":
            return "RIGHT"
        if val.startswith("\x1b"):
            return UNKNOWN_KEY
        return val
    except EOFError:
        return ""


def read_single_key(already_raw: bool = False) -> str:
    """
    Legge un singolo carattere da stdin senza richiedere Invio.
    Supporta anche sequenze ANSI per freccia sinistra ("LEFT") e freccia destra ("RIGHT").
    Se stdin non è una tty (es. pipe, CI, test) o se termios fallisce, fa fallback su input().
    Se already_raw è True, salta l'attivazione/ripristino di termios/tty (già gestita esternamente da raw_mode()).
    """
    if not sys.stdin.isatty():
        return _fallback_input_key()

    if already_raw:
        try:
            return _parse_tty_key()
        except KeyboardInterrupt:
            raise
        except Exception:
            return _fallback_input_key()

    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            return _parse_tty_key()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except KeyboardInterrupt:
        raise
    except Exception:
        return _fallback_input_key()
