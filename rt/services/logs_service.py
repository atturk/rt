"""
rt.services.logs_service
Lettura dei log dei servizi (api, worker, bot) nella cartella dati: le ultime righe e, a
richiesta, il seguito in tempo reale. La usano 'rt logs' e 'rt web -v' (servizi già attivi);
l'output passa da una callback, così il servizio non sa chi lo mostra.
"""
import os
import time
from collections import deque
from typing import Callable, Dict, Optional, Tuple

LOG_SERVICES = ("api", "worker", "bot")


def _default_write(text: str) -> None:
    print(text, end="", flush=True)


def log_path(name: str) -> str:
    from rt.core.paths import data_dir
    return os.path.join(data_dir(), "logs", f"{name}.log")


def show_logs(service: Optional[str] = None, lines: int = 50, follow: bool = False,
              write: Callable[[str], None] = _default_write, poll_interval: float = 0.5) -> None:
    """Scrive con write() le ultime `lines` righe dei log (tutti i servizi o solo `service`);
    con follow=True continua a seguirli finché non arriva Ctrl+C."""
    names = [service] if service else list(LOG_SERVICES)
    positions: Dict[str, Tuple[str, int]] = {}
    for name in names:
        path = log_path(name)
        if not os.path.isfile(path):
            write(f"{name}: nessun log in {path}\n")
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            for line in deque(stream, maxlen=lines):
                write(f"[{name}] {line}")
            positions[name] = (path, stream.tell())
    if not follow:
        return
    write("Ctrl+C interrompe la lettura; i servizi continuano a funzionare.\n")
    try:
        while True:
            for name in names:
                path, position = positions.get(name, (log_path(name), 0))
                if not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as stream:
                    if os.path.getsize(path) < position:
                        position = 0
                    stream.seek(position)
                    for line in stream:
                        write(f"[{name}] {line}")
                    positions[name] = (path, stream.tell())
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        return
