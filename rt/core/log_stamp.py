"""
rt.core.log_stamp
Data e ora all'inizio di ogni riga dei registri di API e worker (api.log, worker.log),
come in desktop.log: senza non si misura quanto durano le operazioni.
"""
import sys
import threading
import time


def stamp() -> str:
    """Prefisso di una riga del registro, con i millesimi per misurare le richieste brevi."""
    now = time.time()
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}.{int(now % 1 * 1000):03d} "


class StampedStream:
    """Avvolge uno stream di testo e scrive stamp() all'inizio di ogni riga."""

    def __init__(self, stream):
        self._stream = stream
        self._line_start = True
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            out = []
            for part in text.splitlines(keepends=True):
                if self._line_start:
                    out.append(stamp())
                out.append(part)
                self._line_start = part.endswith(("\n", "\r"))
            self._stream.write("".join(out))
        return len(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def stamp_std_streams() -> None:
    """Data e ora su stdout e stderr quando finiscono in un file; nel terminale restano come sono."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None or isinstance(stream, StampedStream):
            continue
        try:
            if stream.isatty():
                continue
        except (AttributeError, ValueError):
            continue
        setattr(sys, name, StampedStream(stream))
