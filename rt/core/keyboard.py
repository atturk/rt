"""
rt.core.keyboard
Lettura a singolo tasto da terminale senza richiedere Invio.
Supporta macOS / Linux (termios/tty) con fallback su input() per ambienti non interattivi o di test.
"""

import sys


def read_single_key() -> str:
    """
    Legge un singolo carattere da stdin senza richiedere Invio.
    Se stdin non è una tty (es. pipe, CI, test) o se termios fallisce, fa fallback su input().
    """
    if not sys.stdin.isatty():
        try:
            return input()
        except EOFError:
            return ""

    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt()
            if ch in ("\r", "\n"):
                return ""
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        try:
            return input()
        except EOFError:
            return ""
