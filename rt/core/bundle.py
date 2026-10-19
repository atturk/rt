"""
rt.core.bundle
L'app installabile (RT.app nel .dmg, setup .exe per Windows) contiene un Python suo, le
dipendenze e la web app già compilata. La cartella del codice ha un file BUNDLE che dice per
quale sistema è stata costruita: così 'rt -u' e la pagina Info sanno che l'aggiornamento è
il nuovo installer della release stabile, non il codice sorgente da sincronizzare.
"""
from datetime import datetime
import json
import os
import sys
from typing import Optional

MARKER = "BUNDLE"
BUILD_INFO_FILE = "BUILD.json"
MACOS, WINDOWS = "macos", "windows"


def build_info(project_root: Optional[str] = None) -> dict:
    """Legge BUILD.json e restituisce {} fuori dall'app o se il file è assente o rotto."""
    from rt.core.paths import project_root as default_root
    try:
        path = os.path.join(project_root or default_root(), BUILD_INFO_FILE)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def format_build(info: dict) -> Optional[str]:
    """Formatta la riga di build per Impostazioni › Info (es. 'build 812 · a1b2c3d · 19/10/2026')."""
    if not info:
        return None
    parts = []
    run = info.get("run")
    if run:
        parts.append(f"build {run}")
    commit = info.get("commit")
    if commit:
        parts.append(str(commit))
    built_at = info.get("built_at")
    if built_at:
        try:
            dt = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
            parts.append(dt.strftime("%d/%m/%Y"))
        except Exception:
            parts.append(str(built_at))
    return " · ".join(parts) if parts else None


def kind(project_root: Optional[str] = None) -> Optional[str]:
    """'macos' o 'windows' per un'installazione dall'app, None per install.sh, git o Docker."""
    from rt.core.paths import project_root as default_root
    try:
        with open(os.path.join(project_root or default_root(), MARKER), encoding="utf-8") as f:
            value = f.read().strip().lower()
    except OSError:
        return None
    return value if value in (MACOS, WINDOWS) else None


def app_path(project_root: Optional[str] = None) -> Optional[str]:
    """Su macOS la cartella RT.app che contiene il codice (Contents/Resources/app)."""
    from rt.core.paths import project_root as default_root
    root = os.path.abspath(project_root or default_root())
    contents = os.path.dirname(os.path.dirname(root))
    app = os.path.dirname(contents)
    if os.path.basename(contents) == "Contents" and app.endswith(".app"):
        return app
    return None


def apply_env() -> None:
    """Impostazioni per i processi dell'app (API, worker e figli): testo UTF-8 anche su Windows
    e browser delle catture nella cartella dati invece che nella cartella utente."""
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if kind() is None:
        return
    from rt.core.paths import data_dir
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(data_dir(), "browsers"))


def utf8_console() -> None:
    """Su Windows la console e i file di log usano cp1252: le emoji dei messaggi farebbero
    fallire la stampa. Qui si passa a UTF-8 sostituendo quello che non si può scrivere."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
