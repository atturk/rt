"""
rt.services.folder_picker
Scelta di una cartella per la web (RT4-FA6). Il browser non può restituire un percorso
assoluto, quindi l'API lo chiede al sistema: su macOS la finestra nativa di Finder
(osascript 'choose folder'); altrove, o se la finestra non è disponibile, la SPA usa un piccolo
navigatore basato su list_folders (solo cartelle, a partire dalla home, niente file).

La finestra nativa passa da un'astrazione (NativeFolderChooser) che i test sostituiscono con
set_native_chooser(); RT_NATIVE_FOLDER_PICKER=0 la disattiva (server dei test end-to-end).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

PROMPT = "Scegli la cartella delle lezioni di RT"
MAX_FOLDERS = 500


class FolderPickerUnavailable(Exception):
    """Nessuna finestra nativa su questo sistema: la SPA ripiega sul navigatore."""


class FolderAccessError(Exception):
    """Cartella fuori dalla home, inesistente o non leggibile (messaggio per l'utente)."""


# (cartella iniziale) -> percorso scelto, None se annullato; FolderPickerUnavailable se non c'è.
NativeFolderChooser = Callable[[Optional[str]], Optional[str]]

_override: Optional[NativeFolderChooser] = None


def set_native_chooser(chooser: Optional[NativeFolderChooser]) -> None:
    """Sostituisce la finestra nativa (test); None ripristina quella del sistema."""
    global _override
    _override = chooser


_APPLESCRIPT = (
    "on run argv",
    "activate",
    "set startAt to POSIX file (item 2 of argv)",
    "set chosen to choose folder with prompt (item 1 of argv) default location startAt",
    "return POSIX path of chosen",
    "end run",
)


def _macos_chooser(start: Optional[str]) -> Optional[str]:
    """Finder: 'choose folder' via osascript. Annullato (errore -128) -> None."""
    osascript = shutil.which("osascript")
    if not osascript:
        raise FolderPickerUnavailable("osascript non disponibile.")
    start_dir = start if start and os.path.isdir(start) else str(Path.home())
    args = [osascript]
    for line in _APPLESCRIPT:
        args += ["-e", line]
    args += [PROMPT, start_dir]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FolderPickerUnavailable("Finestra di Finder non disponibile.") from exc
    if proc.returncode != 0:
        if "-128" in (proc.stderr or ""):
            return None  # l'utente ha premuto Annulla
        raise FolderPickerUnavailable("Finestra di Finder non disponibile.")
    chosen = proc.stdout.strip()
    return (chosen.rstrip("/") or "/") if chosen else None


def native_chooser() -> NativeFolderChooser:
    if _override is not None:
        return _override
    if os.environ.get("RT_NATIVE_FOLDER_PICKER", "").strip() == "0" or sys.platform != "darwin":
        raise FolderPickerUnavailable("Finestra nativa non disponibile su questo sistema.")
    return _macos_chooser


def choose_folder(start: Optional[str] = None) -> Dict[str, Any]:
    """{"status": "chosen"|"cancelled"|"unavailable", "path": str|None}."""
    try:
        path = native_chooser()(start)
    except FolderPickerUnavailable:
        return {"status": "unavailable", "path": None}
    if not path:
        return {"status": "cancelled", "path": None}
    return {"status": "chosen", "path": path}


def _home() -> Path:
    return Path.home().resolve()


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def list_folders(path: Optional[str] = None) -> Dict[str, Any]:
    """Sottocartelle di `path` (default la home), senza file né cartelle nascoste. Solo dentro
    la home: {"path", "parent" (None nella home), "home", "folders": [{"name", "path"}]}."""
    home = _home()
    target = Path(os.path.expanduser(path)).resolve() if path and path.strip() else home
    if not _inside(target, home):
        raise FolderAccessError("Si possono sfogliare solo le cartelle della tua home.")
    if not target.is_dir():
        raise FolderAccessError("La cartella non esiste.")
    folders: List[Dict[str, str]] = []
    try:
        entries = sorted(os.scandir(target), key=lambda e: e.name.casefold())
    except OSError:
        raise FolderAccessError("Non è possibile leggere questa cartella.") from None
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if not entry.is_dir():
                continue
            real = Path(entry.path).resolve()
        except OSError:
            continue
        if _inside(real, home):
            folders.append({"name": entry.name, "path": str(target / entry.name)})
        if len(folders) >= MAX_FOLDERS:
            break
    return {"path": str(target), "parent": None if target == home else str(target.parent),
            "home": str(home), "folders": folders}
