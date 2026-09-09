"""
rt.core.keyboard
Lettura a singolo tasto da terminale senza richiedere Invio.
Supporta macOS / Linux (termios/tty) con fallback su input() per ambienti non interattivi o di test.
"""

import sys


def read_single_key() -> str:
    """
    Legge un singolo carattere da stdin senza richiedere Invio.
    Supporta anche sequenze ANSI per freccia sinistra ("LEFT") e freccia destra ("RIGHT").
    Se stdin non è una tty (es. pipe, CI, test) o se termios fallisce, fa fallback su input().
    """
    if not sys.stdin.isatty():
        try:
            val = input()
            if val == "\x1b[D":
                return "LEFT"
            if val == "\x1b[C":
                return "RIGHT"
            return val
        except EOFError:
            return ""

    try:
        import termios
        import tty
        import select

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt()
            if ch in ("\r", "\n"):
                return ""
            if ch == "\x1b":
                try:
                    r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r:
                        ch2 = sys.stdin.read(1)
                        if ch2 == "[":
                            r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                            if r2:
                                ch3 = sys.stdin.read(1)
                                if ch3 == "D":
                                    return "LEFT"
                                elif ch3 == "C":
                                    return "RIGHT"
                                return ""
                            return ""
                        return ""
                    return ""
                except Exception:
                    return ""
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        try:
            val = input()
            if val == "\x1b[D":
                return "LEFT"
            if val == "\x1b[C":
                return "RIGHT"
            return val
        except EOFError:
            return ""
