"""
rt.core.components
Gestione dei componenti scaricabili di RT:
- macparakeet: Motore di trascrizione per Mac (macparakeet-cli + modello parakeet-v3, ~500 MB)
- transcription: Modello di trascrizione per Windows e alternativa sul Mac (Parakeet TDT 0.6B v3 ONNX, ~900 MB)
- browser: Browser per PDF e catture (Chromium headless Playwright)
- libreoffice: Convertitore delle presentazioni (LibreOffice portabile, ~300 MB)

Ogni componente ha un solo download attivo alla volta garantito da file lock in
<models_dir>/.lock (.macparakeet.lock, .browser.lock, .libreoffice.lock), scrive stato e progresso in
<models_dir>/components.json letto da GET /api/v1/components e dai job del worker, e supporta
pausa/ripresa (.part) e eliminazione.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

from rt.core import config as rt_config, onnx_stt, paths
from rt.core.filelock import _expired, acquire_file_lock, release_file_lock

MACPARAKEET_ID = "macparakeet"
TRANSCRIPTION_ID = "transcription"
BROWSER_ID = "browser"
LIBREOFFICE_ID = "libreoffice"
VALID_COMPONENT_IDS = (MACPARAKEET_ID, TRANSCRIPTION_ID, BROWSER_ID, LIBREOFFICE_ID)

MACPARAKEET_URL = (
    "https://github.com/moona3k/macparakeet/releases/download/cli-v5.1.0/"
    "macparakeet-cli-5.1.0-darwin-arm64.tar.gz"
)
MACPARAKEET_TARBALL_BYTES = 20_679_495
MACPARAKEET_TARBALL_SHA256 = "b48210cb22eaf834fb4fea2201dab9334a1165ccaf4133991154c33123b43674"
MACPARAKEET_TARBALL_MEMBER = "macparakeet-cli-5.1.0-darwin-arm64/macparakeet-cli"
MACPARAKEET_BINARY_BYTES = 60_823_984
MACPARAKEET_BINARY_SHA256 = "ef07692faca2364ac0a24345a96389dd97721f6683f7ccee285bb4b9231212f5"
MACPARAKEET_MODEL_NAME = "parakeet-v3"
MACPARAKEET_MODEL_APPROX_BYTES = 480 * 1024 * 1024
MACPARAKEET_APPROX_BYTES = MACPARAKEET_TARBALL_BYTES + MACPARAKEET_MODEL_APPROX_BYTES

TRANSCRIPTION_APPROX_BYTES = 900 * 1024 * 1024
BROWSER_APPROX_BYTES = 110 * 1024 * 1024

LIBREOFFICE_VERSION = "26.8.3"
LIBREOFFICE_MAC_URL = (
    f"https://download.documentfoundation.org/libreoffice/stable/{LIBREOFFICE_VERSION}/mac/aarch64/"
    f"LibreOffice_{LIBREOFFICE_VERSION}_MacOS_aarch64.dmg"
)
LIBREOFFICE_MAC_BYTES = 299_927_705
LIBREOFFICE_MAC_SHA256 = "de943203795e5057785f65515063e2db5eb60b0bb6d8e2534fec59e5cc5fb988"
LIBREOFFICE_WIN_URL = (
    f"https://download.documentfoundation.org/libreoffice/stable/{LIBREOFFICE_VERSION}/win/x86_64/"
    f"LibreOffice_{LIBREOFFICE_VERSION}_Win_x86-64.msi"
)
LIBREOFFICE_WIN_BYTES = 376_311_808
LIBREOFFICE_WIN_SHA256 = "0e6918c273eabbdbbd800ee0dacbbf130a14c13c2e4cec861b06dd59e015bf94"
KEYNOTE_BLOCK_SECONDS = 7 * 24 * 60 * 60

LOCK_STALE_SECONDS = 30.0

_state_io_lock = threading.Lock()
_active_lock = threading.Lock()


class ComponentError(RuntimeError):
    """Errore generico nella gestione di un componente."""


class ComponentNotFound(ComponentError):
    """Componente sconosciuto."""


class ComponentUnavailable(ComponentError):
    """Componente non installabile su questo sistema/ambiente."""


class ComponentBusy(ComponentError):
    """Un altro processo sta scaricando questo componente."""


@dataclass
class _ActiveDownload:
    thread: threading.Thread
    cancel_event: threading.Event
    process: Optional[subprocess.Popen[Any]] = None

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()
        proc = self.process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass


class _CancelFlag:
    """Oggetto compatibile con cancel_token di onnx_stt (attributo .cancelled e raise_if_cancelled)."""

    def __init__(self, event: threading.Event, inner: Optional[Any] = None):
        self._event = event
        self._inner = inner

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or bool(self._inner is not None and getattr(self._inner, "cancelled", False))

    def raise_if_cancelled(self) -> None:
        if self._inner is not None and hasattr(self._inner, "raise_if_cancelled"):
            self._inner.raise_if_cancelled()
        if self._event.is_set():
            raise RuntimeError("Trascrizione annullata")


_active: Dict[str, _ActiveDownload] = {}


def _state_file() -> str:
    return os.path.join(onnx_stt.models_dir(), "components.json")


def lock_path_for(component_id: str) -> str:
    if component_id == TRANSCRIPTION_ID:
        return os.path.join(onnx_stt.models_dir(), ".lock")
    if component_id == MACPARAKEET_ID:
        return os.path.join(onnx_stt.models_dir(), ".macparakeet.lock")
    if component_id == BROWSER_ID:
        return os.path.join(onnx_stt.models_dir(), ".browser.lock")
    if component_id == LIBREOFFICE_ID:
        return os.path.join(onnx_stt.models_dir(), ".libreoffice.lock")
    raise ComponentNotFound(f"Componente sconosciuto: {component_id}")


def macparakeet_bin_dir() -> str:
    return os.path.join(paths.data_dir(), "bin")


def macparakeet_bin_path() -> str:
    return os.path.join(macparakeet_bin_dir(), "macparakeet-cli")


def macparakeet_part_path() -> str:
    return os.path.join(macparakeet_bin_dir(), "macparakeet-cli.tar.gz.part")


def macparakeet_models_root() -> str:
    explicit = os.environ.get("RT_MACPARAKEET_MODELS_DIR", "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "FluidAudio", "Models")


def _macparakeet_model_entries() -> List[str]:
    root = macparakeet_models_root()
    if not os.path.isdir(root):
        return []
    entries: List[str] = []
    for name in os.listdir(root):
        low = name.lower()
        if ("parakeet" in low and "v3" in low) or low == MACPARAKEET_MODEL_NAME:
            entries.append(os.path.join(root, name))
    return entries


def _entry_size(path: str) -> int:
    if os.path.isdir(path):
        return _dir_size(path)
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


def _macparakeet_models_bytes() -> int:
    entries = _macparakeet_model_entries()
    if entries:
        return sum(_entry_size(p) for p in entries)
    return _dir_size(macparakeet_models_root())


def macparakeet_available() -> bool:
    return rt_config.is_apple_silicon()


def _macparakeet_binary_installed() -> Optional[str]:
    local = macparakeet_bin_path()
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    from rt.pipeline.setup import find_macparakeet_binary
    return find_macparakeet_binary() or None


def _macparakeet_incomplete_download() -> bool:
    saved = _read_all_states().get(MACPARAKEET_ID) or {}
    return bool(saved) and not saved.get("model_ready") and saved.get("state") in ("downloading", "paused", "error")


def macparakeet_ready() -> bool:
    if not _macparakeet_binary_installed():
        return False
    saved = _read_all_states().get(MACPARAKEET_ID) or {}
    if saved.get("state") in ("paused", "error") and not saved.get("model_ready"):
        return False
    if saved.get("model_ready"):
        return True
    return bool(_macparakeet_model_entries() and _macparakeet_models_bytes() > 0)


def _macparakeet_partial_bytes() -> int:
    total = _entry_size(macparakeet_part_path()) + _entry_size(macparakeet_bin_path())
    total += _macparakeet_models_bytes()
    return total


def _macparakeet_ready_bytes() -> int:
    bin_path = _macparakeet_binary_installed()
    bin_bytes = _entry_size(bin_path) if bin_path else 0
    return bin_bytes + _macparakeet_models_bytes()


def browsers_dir() -> str:
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if explicit:
        return explicit
    return os.path.join(paths.data_dir(), "browsers")


def browser_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def current_playwright_headless_revision() -> Optional[str]:
    """Revisione di chromium-headless-shell richiesta dal pacchetto playwright installato."""
    try:
        spec = importlib.util.find_spec("playwright")
        if spec is None or not spec.origin:
            return None
        browsers_json = os.path.join(os.path.dirname(spec.origin), "driver", "package", "browsers.json")
        if not os.path.isfile(browsers_json):
            return None
        with open(browsers_json, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("browsers", []):
            if entry.get("name") == "chromium-headless-shell" and entry.get("revision"):
                return str(entry["revision"])
    except Exception:
        return None
    return None


def browser_ready(target: Optional[str] = None) -> bool:
    from rt.llm.enrichment_media import find_headless_shell_in_dir

    folder = target or browsers_dir()
    rev = current_playwright_headless_revision()
    if rev:
        # Una revisione diversa da quella del Playwright installato non parte con launch():
        # non conta come pronta (la pulizia all'avvio la rimuove).
        rev_dir = f"chromium_headless_shell-{rev}"
        return os.path.isdir(os.path.join(folder, rev_dir)) and \
            find_headless_shell_in_dir(folder, preferred_revision=rev) is not None
    return find_headless_shell_in_dir(folder) is not None


def cleanup_old_browsers(target: Optional[str] = None) -> int:
    """Rimuove le vecchie cartelle chromium-* (completo) e le revisioni obsolete di headless shell."""
    if is_download_active(BROWSER_ID):
        return 0
    folder = target or browsers_dir()
    if not os.path.isdir(folder):
        return 0
    current_rev = current_playwright_headless_revision()
    freed = 0
    removed: List[str] = []
    for name in sorted(os.listdir(folder)):
        if is_download_active(BROWSER_ID):
            break
        remove = False
        if name.startswith("chromium-"):
            remove = True
        elif name.startswith("chromium_headless_shell-"):
            rev = name[len("chromium_headless_shell-"):]
            if current_rev and rev != current_rev:
                remove = True
        if not remove:
            continue
        path = os.path.join(folder, name)
        freed += _entry_size(path)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.unlink(path)
            except OSError:
                pass
        removed.append(name)

    if removed:
        log_file_path = os.path.join(paths.data_dir(), "logs", "browser-install.log")
        try:
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} Pulizia browser obsoleti "
                    f"({', '.join(removed)}): liberati {freed / (1024 * 1024):.1f} MB\n"
                )
        except OSError:
            pass
    return freed


def components_dir() -> str:
    return os.path.join(paths.data_dir(), "components")


def libreoffice_dir() -> str:
    return os.path.join(components_dir(), "libreoffice")


def libreoffice_partial_dir() -> str:
    return os.path.join(components_dir(), "libreoffice.partial")


def libreoffice_profile_dir() -> str:
    return os.path.join(components_dir(), "libreoffice-profile")


def libreoffice_fonts_conf_path() -> str:
    return os.path.join(components_dir(), "libreoffice-fonts.conf")


def libreoffice_fontcache_dir() -> str:
    return os.path.join(components_dir(), "libreoffice-fontcache")


def _libreoffice_platform_spec() -> Optional[Tuple[str, int, str, str]]:
    if sys.platform == "darwin" and rt_config.is_apple_silicon():
        return (LIBREOFFICE_MAC_URL, LIBREOFFICE_MAC_BYTES, LIBREOFFICE_MAC_SHA256, ".dmg")
    if sys.platform == "win32":
        return (LIBREOFFICE_WIN_URL, LIBREOFFICE_WIN_BYTES, LIBREOFFICE_WIN_SHA256, ".msi")
    return None


def libreoffice_available() -> bool:
    return _libreoffice_platform_spec() is not None


def libreoffice_executable() -> Optional[str]:
    base = libreoffice_dir()
    if sys.platform == "win32":
        cand = os.path.join(base, "program", "soffice.exe")
        return cand if os.path.isfile(cand) else None
    cand = os.path.join(base, "LibreOffice.app", "Contents", "MacOS", "soffice")
    if os.path.isfile(cand):
        return cand
    if sys.platform != "darwin":
        win_cand = os.path.join(base, "program", "soffice.exe")
        if os.path.isfile(win_cand):
            return win_cand
    return None


def libreoffice_ready() -> bool:
    return libreoffice_executable() is not None


def libreoffice_part_path() -> str:
    spec = _libreoffice_platform_spec()
    ext = spec[3] if spec is not None else ".dmg"
    return os.path.join(components_dir(), f"libreoffice{ext}.part")


def _libreoffice_partial_bytes() -> int:
    total = sum(
        _entry_size(os.path.join(components_dir(), name))
        for name in ("libreoffice.dmg.part", "libreoffice.msi.part")
    )
    return total + _dir_size(libreoffice_partial_dir())


def _libreoffice_ready_bytes() -> int:
    return _dir_size(libreoffice_dir())


def _find_libreoffice_app_fonts_conf() -> Optional[str]:
    contents = os.path.join(libreoffice_dir(), "LibreOffice.app", "Contents")
    for rel in (
        ("Resources", "fontconfig", "fonts.conf"),
        ("Resources", "fonts", "fonts.conf"),
        ("etc", "fonts", "fonts.conf"),
    ):
        cand = os.path.join(contents, *rel)
        if os.path.isfile(cand):
            return cand
    return None


def _ensure_libreoffice_registry_substitutions(profile_dir: str) -> None:
    user_dir = os.path.join(profile_dir, "user")
    os.makedirs(user_dir, exist_ok=True)
    xcu_path = os.path.join(user_dir, "registrymodifications.xcu")
    if os.path.isfile(xcu_path):
        try:
            with open(xcu_path, encoding="utf-8") as f:
                existing = f.read()
            if "cambriamath" in existing and "STIX Two Math" in existing:
                return
        except OSError:
            pass
    items = [
        ("calibri", "Carlito", "Normal,SansSerif"),
        ("cambria", "Caladea", "Normal,Serif"),
        ("cambriamath", "STIX Two Math", "Normal,Symbol"),
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    ]
    for font_key, subst, font_type in items:
        lines.append(
            f'<item oor:path="/org.openoffice.VCL/FontSubstitutions">'
            f'<node oor:name="{xml_escape(font_key)}" oor:op="replace">'
            f'<prop oor:name="SubstFonts" oor:op="fuse"><value>{xml_escape(subst)}</value></prop>'
            f'<prop oor:name="FontType" oor:op="fuse"><value>{xml_escape(font_type)}</value></prop>'
            f'</node></item>'
        )
    lines.append("</oor:items>\n")
    tmp = f"{xcu_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, xcu_path)


def prepare_libreoffice_runtime() -> Dict[str, str]:
    """Prepara profilo RT e (su macOS) fontconfig + sostituzioni font per LibreOffice headless."""
    profile_dir = libreoffice_profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    if sys.platform != "darwin":
        return {}

    _ensure_libreoffice_registry_substitutions(profile_dir)
    fontcache_dir = libreoffice_fontcache_dir()
    os.makedirs(fontcache_dir, exist_ok=True)
    fonts_conf = libreoffice_fonts_conf_path()
    os.makedirs(os.path.dirname(fonts_conf), exist_ok=True)

    app_fonts_conf = _find_libreoffice_app_fonts_conf()
    lines = [
        '<?xml version="1.0"?>',
        '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">',
        "<fontconfig>",
    ]
    if app_fonts_conf:
        lines.append(f'  <include ignore_missing="yes">{xml_escape(app_fonts_conf)}</include>')
    for font_dir in (
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        "/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
    ):
        lines.append(f"  <dir>{xml_escape(font_dir)}</dir>")
    lines.append(f"  <cachedir>{xml_escape(fontcache_dir)}</cachedir>")
    lines.append("</fontconfig>\n")
    content = "\n".join(lines)
    try:
        with open(fonts_conf, encoding="utf-8") as f:
            if f.read() == content:
                return {"FONTCONFIG_FILE": fonts_conf}
    except OSError:
        pass
    tmp = f"{fonts_conf}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, fonts_conf)
    return {"FONTCONFIG_FILE": fonts_conf}


def keynote_blocked_until() -> Optional[float]:
    val = _read_all_states().get("keynote_blocked_until")
    return float(val) if isinstance(val, (int, float)) else None


def is_keynote_blocked(now: Optional[float] = None) -> bool:
    until = keynote_blocked_until()
    if until is None:
        return False
    current = time.time() if now is None else now
    return current < until


def _write_root_state(key: str, value: Any) -> None:
    path = _state_file()
    with _state_io_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        if value is None:
            if key not in data:
                return
            data.pop(key, None)
        else:
            data[key] = value
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def mark_keynote_blocked(seconds: float = KEYNOTE_BLOCK_SECONDS) -> float:
    until = time.time() + seconds
    _write_root_state("keynote_blocked_until", until)
    return until


def clear_keynote_blocked() -> None:
    _write_root_state("keynote_blocked_until", None)


def detect_system_slide_app() -> Optional[str]:
    from rt.core import materials

    if sys.platform == "win32":
        if materials._has_powerpoint():
            return "Microsoft PowerPoint"
        if materials._soffice():
            return "LibreOffice"
        return None
    if sys.platform == "darwin":
        if materials._has_keynote() and not is_keynote_blocked():
            return "Keynote"
        if materials._soffice():
            return "LibreOffice"
        return None
    if materials._soffice():
        return "LibreOffice"
    return None


def _read_all_states() -> Dict[str, Dict[str, Any]]:
    path = _state_file()
    with _state_io_lock:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


def _write_component_state(component_id: str, patch: Dict[str, Any]) -> None:
    path = _state_file()
    with _state_io_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        current = dict(data.get(component_id) or {})
        current.update(patch)
        current["updated_at"] = time.time()
        data[component_id] = current
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _clear_component_state(component_id: str) -> None:
    path = _state_file()
    with _state_io_lock:
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (OSError, ValueError):
            return
        if component_id not in data:
            return
        data.pop(component_id, None)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _lock_owner_pid(lock_path: str) -> Optional[int]:
    try:
        with open(lock_path, encoding="utf-8") as f:
            owner = json.load(f)
        pid = owner.get("pid")
        return int(pid) if pid is not None else None
    except (OSError, ValueError, TypeError):
        return None


def _is_lock_held(lock_path: str) -> bool:
    if not os.path.exists(lock_path):
        return False
    try:
        if _expired(lock_path, LOCK_STALE_SECONDS):
            try:
                os.remove(lock_path)
            except OSError:
                pass
            return False
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def is_download_active(component_id: str) -> bool:
    with _active_lock:
        active = _active.get(component_id)
        if active is not None and active.thread.is_alive():
            return True
    return _is_lock_held(lock_path_for(component_id))


def _dir_size(path: str) -> int:
    if not os.path.isdir(path):
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _transcription_partial_bytes() -> int:
    return _dir_size(onnx_stt.model_dir() + ".partial")


def _transcription_ready_bytes() -> int:
    return _dir_size(onnx_stt.model_dir())


def _browser_disk_bytes() -> int:
    folder = browsers_dir()
    if not os.path.isdir(folder):
        return 0
    return sum(
        _dir_size(os.path.join(folder, name))
        for name in os.listdir(folder)
        if name.startswith("chromium_headless_shell")
    )


def _renew_lock_loop(lock_path: str, stopped: threading.Event) -> None:
    while not stopped.wait(10.0):
        try:
            os.utime(lock_path, None)
        except OSError:
            return


def _acquire_nonblocking(lock_path: str) -> bool:
    try:
        acquire_file_lock(lock_path, retries=1, backoff=0.01, stale_sec=LOCK_STALE_SECONDS)
        return True
    except TimeoutError:
        return False


def _effective_engine_safe() -> str:
    try:
        return rt_config.effective_engine()
    except Exception:
        return rt_config.default_engine()


def _component_meta(component_id: str) -> Dict[str, Any]:
    effective = _effective_engine_safe()
    if component_id == MACPARAKEET_ID:
        avail = macparakeet_available()
        return {
            "id": MACPARAKEET_ID,
            "name": "Motore di trascrizione",
            "description": ("necessario per trascrivere l'audio" if avail and effective == "macparakeet"
                            else "non necessario: alternativa al motore scelto"),
            "detail": "macparakeet + modello parakeet-v3",
            "approx_bytes": MACPARAKEET_APPROX_BYTES,
            "required": bool(avail and effective == "macparakeet"),
            "available": avail,
            "unavailable_reason": None if avail else "Disponibile solo su Mac con Apple Silicon.",
        }
    if component_id == TRANSCRIPTION_ID:
        return {
            "id": TRANSCRIPTION_ID,
            "name": "Modello di trascrizione",
            "description": ("Modello di trascrizione per Windows" if sys.platform == "win32"
                            else "necessario per trascrivere l'audio" if effective == "parakeet"
                            else "non necessario: alternativa al motore scelto, puoi eliminarlo"),
            "detail": "Parakeet TDT 0.6B v3 di NVIDIA, CC-BY-4.0",
            "approx_bytes": TRANSCRIPTION_APPROX_BYTES,
            "required": effective == "parakeet",
            "available": onnx_stt.available(),
            "unavailable_reason": None if onnx_stt.available() else "Pacchetto onnx-asr non installato.",
        }
    if component_id == BROWSER_ID:
        avail = browser_available()
        from rt.llm.enrichment_media import detect_system_browser

        sb = detect_system_browser()
        sb_name = sb.name if sb is not None else None
        ready = (not is_download_active(BROWSER_ID)) and browser_ready()
        if ready:
            in_use: Optional[str] = "component"
            description = "RT usa il browser scaricato per esportare in PDF e per le visualizzazioni"
        elif sb_name:
            in_use = "system"
            description = (
                f"Rilevato {sb_name}: RT usa quello, scaricare questo componente non è necessario. "
                "Se lo scarichi, RT usa questo"
            )
        else:
            in_use = None
            description = "Serve per esportare in PDF e per le visualizzazioni: scaricalo"
        return {
            "id": BROWSER_ID,
            "name": "Browser per PDF e catture",
            "description": description,
            "detail": "Chrome Headless Shell (versione minima)",
            "approx_bytes": BROWSER_APPROX_BYTES,
            "required": sb_name is None,
            "available": avail,
            "unavailable_reason": None if avail else "Pacchetto playwright non installato.",
            "system_browser": sb_name,
            "in_use": in_use,
        }
    if component_id == LIBREOFFICE_ID:
        spec = _libreoffice_platform_spec()
        avail = spec is not None
        approx = spec[1] if spec is not None else LIBREOFFICE_MAC_BYTES
        sys_app = detect_system_slide_app()
        ready = (not is_download_active(LIBREOFFICE_ID)) and libreoffice_ready()
        keynote_blocked = (sys.platform == "darwin") and is_keynote_blocked()
        if ready:
            in_use_lo: Optional[str] = "component"
            desc_lo = "RT usa questo convertitore per le slide delle presentazioni"
        elif sys_app:
            in_use_lo = "system"
            desc_lo = f"Rilevato {sys_app}: RT usa quello, scaricare questo componente non è necessario"
        elif keynote_blocked:
            in_use_lo = None
            desc_lo = (
                "Keynote non risponde: consenti a RT di controllarlo in Impostazioni di "
                "Sistema › Privacy e sicurezza › Automazione, oppure scarica il convertitore"
            )
        else:
            in_use_lo = None
            desc_lo = "Serve per trasformare le presentazioni (.pptx) in slide: scaricalo"
        unavail_reason = (
            "Disponibile solo su Mac con Apple Silicon."
            if sys.platform == "darwin"
            else "Disponibile solo su Mac (Apple Silicon) e Windows."
        )
        return {
            "id": LIBREOFFICE_ID,
            "name": "Convertitore delle presentazioni",
            "description": desc_lo,
            "detail": f"LibreOffice {LIBREOFFICE_VERSION} (MPL-2.0)",
            "approx_bytes": approx,
            "required": sys_app is None,
            "available": avail,
            "unavailable_reason": None if avail else unavail_reason,
            "system_app": sys_app,
            "in_use": in_use_lo,
        }
    raise ComponentNotFound(f"Componente sconosciuto: {component_id}")


def get_component(component_id: str) -> Dict[str, Any]:
    meta = _component_meta(component_id)
    saved = _read_all_states().get(component_id) or {}
    active = is_download_active(component_id)
    if component_id == TRANSCRIPTION_ID:
        ready = (not active) and onnx_stt.model_ready()
        disk_bytes = _transcription_ready_bytes() if ready else _transcription_partial_bytes()
    elif component_id == MACPARAKEET_ID:
        ready = (not active) and macparakeet_ready()
        disk_bytes = _macparakeet_ready_bytes() if ready else _macparakeet_partial_bytes()
    elif component_id == LIBREOFFICE_ID:
        ready = (not active) and libreoffice_ready()
        disk_bytes = _libreoffice_ready_bytes() if ready else _libreoffice_partial_bytes()
    else:
        ready = (not active) and browser_ready()
        disk_bytes = _browser_disk_bytes() if ready else 0

    if active:
        state = "downloading"
        downloaded = max(int(saved.get("downloaded_bytes") or 0), disk_bytes)
        total = saved.get("total_bytes")
        percent = saved.get("percent")
        if percent is None and total:
            percent = min(100, max(0, int(downloaded * 100 / total)))
        eta_seconds = saved.get("eta_seconds")
        eta_label = saved.get("eta_label")
        error = None
    elif ready:
        state = "ready"
        downloaded = disk_bytes or int(saved.get("total_bytes") or meta["approx_bytes"])
        total = downloaded
        percent = 100
        eta_seconds = None
        eta_label = None
        error = None
    elif saved.get("state") == "error":
        state = "error"
        downloaded = max(int(saved.get("downloaded_bytes") or 0), disk_bytes)
        total = saved.get("total_bytes")
        percent = int(downloaded * 100 / total) if total and downloaded > 0 else saved.get("percent")
        eta_seconds = None
        eta_label = None
        error = saved.get("error") or "Download non riuscito."
    elif saved.get("state") == "paused" or (
        component_id in (TRANSCRIPTION_ID, MACPARAKEET_ID, LIBREOFFICE_ID) and disk_bytes > 0
    ):
        state = "paused" if (saved.get("state") == "paused" or disk_bytes > 0) else "not_downloaded"
        downloaded = disk_bytes
        total = saved.get("total_bytes")
        percent = int(downloaded * 100 / total) if total and downloaded > 0 else saved.get("percent")
        eta_seconds = None
        eta_label = None
        error = None
    else:
        state = "not_downloaded"
        downloaded = 0
        total = None
        percent = None
        eta_seconds = None
        eta_label = None
        error = None

    return {
        **meta,
        "state": state,
        "downloaded_bytes": downloaded,
        "total_bytes": total,
        "percent": percent,
        "eta_seconds": eta_seconds,
        "eta_label": eta_label,
        "error": error,
    }


def list_components() -> List[Dict[str, Any]]:
    return [get_component(cid) for cid in VALID_COMPONENT_IDS]


def _download_transcription_under_lock(
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
) -> str:
    """Scarica il modello q8pc assumendo il lock .lock già acquisito."""

    def handle_model_stats(stats: Dict[str, Any]) -> None:
        _write_component_state(TRANSCRIPTION_ID, {
            "state": "downloading",
            "auto_resume": True,
            "pid": os.getpid(),
            "downloaded_bytes": stats.get("downloaded_bytes") or 0,
            "total_bytes": stats.get("total_bytes"),
            "percent": int(stats.get("percent") or 0),
            "eta_seconds": stats.get("eta_seconds"),
            "eta_label": stats.get("eta_label"),
            "error": None,
        })

    model_path = onnx_stt._download_resumable(
        onnx_stt.MODEL_DIR_NAME,
        onnx_stt.QUANTIZATION,
        on_progress=on_progress,
        on_stats=handle_model_stats,
        cancel_token=cancel_token,
    )
    onnx_stt._cleanup_legacy_models()
    if onnx_stt.model_ready():
        ready_size = _transcription_ready_bytes()
        _write_component_state(TRANSCRIPTION_ID, {
            "state": "ready",
            "auto_resume": False,
            "pid": None,
            "downloaded_bytes": ready_size,
            "total_bytes": ready_size,
            "percent": 100,
            "eta_seconds": None,
            "eta_label": None,
            "error": None,
        })
    return model_path


def ensure_transcription_model(
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
) -> str:
    """Assicura che il modello ONNX sia su disco: attende se un altro processo sta scaricando,
    altrimenti acquisisce <models>/.lock e scarica aggiornando components.json."""
    if onnx_stt.model_ready():
        onnx_stt._cleanup_legacy_models()
        return onnx_stt.model_dir()

    lpath = lock_path_for(TRANSCRIPTION_ID)
    last_emit = 0.0
    last_pct = -1

    while not onnx_stt.model_ready():
        if cancel_token is not None and hasattr(cancel_token, "raise_if_cancelled"):
            cancel_token.raise_if_cancelled()
        elif cancel_token is not None and getattr(cancel_token, "cancelled", False):
            raise RuntimeError("Trascrizione annullata")

        if _acquire_nonblocking(lpath):
            stopped = threading.Event()
            renewer = threading.Thread(target=_renew_lock_loop, args=(lpath, stopped), daemon=True)
            renewer.start()
            try:
                if onnx_stt.model_ready():
                    onnx_stt._cleanup_legacy_models()
                    return onnx_stt.model_dir()
                _write_component_state(TRANSCRIPTION_ID, {
                    "state": "downloading",
                    "auto_resume": True,
                    "pid": os.getpid(),
                    "error": None,
                })
                return _download_transcription_under_lock(on_progress=on_progress, cancel_token=cancel_token)
            except RuntimeError as exc:
                if "annullat" in str(exc).lower():
                    _write_component_state(TRANSCRIPTION_ID, {
                        "state": "paused",
                        "auto_resume": False,
                        "pid": None,
                        "error": None,
                    })
                else:
                    _write_component_state(TRANSCRIPTION_ID, {
                        "state": "error",
                        "auto_resume": False,
                        "pid": None,
                        "error": str(exc),
                    })
                raise
            except Exception as exc:
                _write_component_state(TRANSCRIPTION_ID, {
                    "state": "error",
                    "auto_resume": False,
                    "pid": None,
                    "error": str(exc),
                })
                raise
            finally:
                stopped.set()
                renewer.join(timeout=1.0)
                release_file_lock(lpath)

        # Un altro processo (es. l'API) sta già scaricando: attendiamo leggendo il suo progresso.
        if on_progress:
            status = get_component(TRANSCRIPTION_ID)
            pct = status.get("percent")
            now = time.monotonic()
            if (pct is not None and pct != last_pct) or (now - last_emit >= 1.5):
                last_emit = now
                if pct is not None:
                    last_pct = pct
                    done_mb = round((status.get("downloaded_bytes") or 0) / (1024 * 1024))
                    total_mb = max(1, round((status.get("total_bytes") or TRANSCRIPTION_APPROX_BYTES) / (1024 * 1024)))
                    eta = status.get("eta_label")
                    eta_part = f", {eta}" if eta else ""
                    on_progress(f"Scarico il modello di trascrizione: {pct}% ({done_mb} di {total_mb} MB{eta_part})")
                else:
                    on_progress("In attesa del modello di trascrizione…")
        time.sleep(0.5)

    onnx_stt._cleanup_legacy_models()
    return onnx_stt.model_dir()


_sha256_file = onnx_stt._sha256_file


def _validate_safe_member_name(name: str) -> None:
    if not name or os.path.isabs(name) or name.startswith("/"):
        raise ComponentError(f"Percorso non sicuro nell'archivio macparakeet: {name!r}")
    parts = PurePosixPath(name).parts
    if any(part in ("", ".", "..") for part in parts):
        raise ComponentError(f"Percorso non sicuro nell'archivio macparakeet: {name!r}")


def _download_resumable_file(
    url: str,
    part_path: str,
    *,
    expected_sha256: str,
    offline_env: str,
    label: str,
    cancel_message: str,
    on_bytes: Optional[Callable[[int, Optional[int]], None]] = None,
    cancel_token: Optional[Any] = None,
) -> None:
    import requests

    if os.environ.get(offline_env) == "1" and not url.startswith(("http://127.0.0.1", "http://localhost")):
        raise ComponentError(f"Download di {label} disattivato nei test.")

    os.makedirs(os.path.dirname(part_path), exist_ok=True)
    resume_from = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
    headers: Dict[str, str] = {"Range": f"bytes={resume_from}-"} if resume_from > 0 else {}

    def _stream(resp: Any, start_at: int) -> None:
        total_hint: Optional[int] = None
        content_len = resp.headers.get("Content-Length")
        if content_len and str(content_len).isdigit():
            total_hint = start_at + int(content_len)
        mode = "ab" if start_at > 0 else "wb"
        downloaded = start_at
        with open(part_path, mode) as stream:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if cancel_token is not None and getattr(cancel_token, "cancelled", False):
                    raise RuntimeError(cancel_message)
                if not chunk:
                    continue
                stream.write(chunk)
                downloaded += len(chunk)
                if on_bytes:
                    on_bytes(downloaded, total_hint)

    try:
        with requests.get(url, headers=headers, stream=True, timeout=(15, 60), allow_redirects=True) as resp:
            if resp.status_code == 416 and resume_from > 0:
                if _sha256_file(part_path) == expected_sha256.lower():
                    return
                os.unlink(part_path)
                with requests.get(url, stream=True, timeout=(15, 60), allow_redirects=True) as resp2:
                    resp2.raise_for_status()
                    _stream(resp2, 0)
                return
            resp.raise_for_status()
            if resp.status_code == 206:
                content_range = resp.headers.get("Content-Range", "")
                if content_range and not content_range.startswith(f"bytes {resume_from}-"):
                    resume_from = 0
            elif resume_from > 0:
                resume_from = 0
            _stream(resp, resume_from)
    except RuntimeError:
        raise
    except Exception as exc:
        raise ComponentError(f"Download di {label} non riuscito: {exc}") from exc


def _download_macparakeet_tarball(
    part_path: str,
    *,
    on_bytes: Optional[Callable[[int, Optional[int]], None]] = None,
    cancel_token: Optional[Any] = None,
) -> None:
    _download_resumable_file(
        MACPARAKEET_URL,
        part_path,
        expected_sha256=MACPARAKEET_TARBALL_SHA256,
        offline_env="RT_MACPARAKEET_OFFLINE",
        label="macparakeet-cli",
        cancel_message="Trascrizione annullata",
        on_bytes=on_bytes,
        cancel_token=cancel_token,
    )


def _extract_and_verify_macparakeet(part_path: str, bin_path: str) -> None:
    actual_tar_sha = _sha256_file(part_path)
    if actual_tar_sha != MACPARAKEET_TARBALL_SHA256.lower():
        try:
            os.unlink(part_path)
        except OSError:
            pass
        raise ComponentError("Verifica SHA256 dell'archivio macparakeet-cli non riuscita.")

    _validate_safe_member_name(MACPARAKEET_TARBALL_MEMBER)
    os.makedirs(os.path.dirname(bin_path), exist_ok=True)
    tmp_bin = f"{bin_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with tarfile.open(part_path, "r:gz") as tar:
            try:
                member = tar.getmember(MACPARAKEET_TARBALL_MEMBER)
            except KeyError:
                raise ComponentError("Archivio macparakeet-cli incompleto: binario mancante.") from None
            _validate_safe_member_name(member.name)
            if not member.isreg():
                raise ComponentError("Membro macparakeet-cli non valido nell'archivio.")
            src = tar.extractfile(member)
            if src is None:
                raise ComponentError("Impossibile leggere macparakeet-cli dall'archivio.")
            digest = hashlib.sha256()
            with src, open(tmp_bin, "wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    digest.update(chunk)
                    dst.write(chunk)
        if digest.hexdigest() != MACPARAKEET_BINARY_SHA256.lower():
            raise ComponentError("Verifica SHA256 del binario macparakeet-cli non riuscita.")
        os.chmod(tmp_bin, 0o755)
        os.replace(tmp_bin, bin_path)
    except ComponentError:
        if os.path.exists(tmp_bin):
            try:
                os.unlink(tmp_bin)
            except OSError:
                pass
        try:
            os.unlink(part_path)
        except OSError:
            pass
        raise
    except (OSError, tarfile.TarError) as exc:
        if os.path.exists(tmp_bin):
            try:
                os.unlink(tmp_bin)
            except OSError:
                pass
        try:
            os.unlink(part_path)
        except OSError:
            pass
        raise ComponentError(f"Estrazione di macparakeet-cli non riuscita: {exc}") from exc

    try:
        os.unlink(part_path)
    except OSError:
        pass


def _download_macparakeet_model(
    bin_path: str,
    *,
    tarball_bytes: int,
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
    active_entry: Optional[_ActiveDownload] = None,
) -> None:
    models_root = macparakeet_models_root()
    os.makedirs(models_root, exist_ok=True)
    log_file_path = os.path.join(paths.data_dir(), "logs", "macparakeet-install.log")
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

    proc = subprocess.Popen(
        [bin_path, "models", "download", MACPARAKEET_MODEL_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "MACPARAKEET_TELEMETRY": "0"},
        **kwargs,
    )
    if active_entry is not None:
        active_entry.process = proc
    _write_component_state(MACPARAKEET_ID, {"pid": proc.pid, "helper_pid": os.getpid()})

    shared: Dict[str, Any] = {"stdout_pct": None, "last_line": ""}
    reader_lock = threading.Lock()

    def _read_output() -> None:
        assert proc.stdout is not None
        buf = b""
        with open(log_file_path, "a", encoding="utf-8") as log_stream:
            while True:
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                log_stream.write(chunk.decode("utf-8", errors="replace"))
                log_stream.flush()
                buf += chunk
                parts = re.split(rb"[\r\n]+", buf)
                buf = parts.pop() if parts else b""
                for raw_line in parts:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    match = re.search(r"\b(\d{1,3})%", line)
                    with reader_lock:
                        shared["last_line"] = line
                        if match:
                            shared["stdout_pct"] = min(100, max(0, int(match.group(1))))
            if buf.strip():
                line = buf.decode("utf-8", errors="replace").strip()
                match = re.search(r"\b(\d{1,3})%", line)
                with reader_lock:
                    shared["last_line"] = line
                    if match:
                        shared["stdout_pct"] = min(100, max(0, int(match.group(1))))

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    started = time.monotonic()
    initial_model_bytes = _macparakeet_models_bytes()
    last_emit = started - 1.5
    last_pct = -1
    cancelled = False
    try:
        while True:
            if cancel_token is not None and getattr(cancel_token, "cancelled", False):
                cancelled = True
                proc.terminate()
                break
            now = time.monotonic()
            model_bytes = _macparakeet_models_bytes()
            with reader_lock:
                stdout_pct = shared["stdout_pct"]
            total_bytes = tarball_bytes + max(MACPARAKEET_MODEL_APPROX_BYTES, model_bytes)
            if stdout_pct is not None:
                model_done_est = max(model_bytes, int(MACPARAKEET_MODEL_APPROX_BYTES * stdout_pct / 100))
                downloaded_bytes = tarball_bytes + model_done_est
                pct = min(99, max(0, int(downloaded_bytes * 100 / total_bytes)))
            else:
                downloaded_bytes = tarball_bytes + model_bytes
                pct = min(99, max(0, int(downloaded_bytes * 100 / total_bytes)))
            if pct != last_pct and (now - last_emit >= 0.5 or pct in (0, 99)) or (now - last_emit >= 1.5):
                last_emit = now
                last_pct = pct
                elapsed = now - started
                session_bytes = max(0, model_bytes - initial_model_bytes)
                remaining = max(0, total_bytes - downloaded_bytes)
                eta_seconds: Optional[float] = None
                eta_label: Optional[str] = None
                eta_part = ""
                if elapsed >= 2.0 and session_bytes > 0 and remaining > 0:
                    speed = session_bytes / elapsed
                    if speed > 0:
                        eta_seconds = remaining / speed
                        eta_label = onnx_stt._format_eta_short(eta_seconds)
                        eta_part = f", {onnx_stt._format_eta(eta_seconds)}"
                _write_component_state(MACPARAKEET_ID, {
                    "state": "downloading",
                    "auto_resume": True,
                    "downloaded_bytes": downloaded_bytes,
                    "total_bytes": total_bytes,
                    "percent": pct,
                    "eta_seconds": eta_seconds,
                    "eta_label": eta_label,
                    "error": None,
                })
                if on_progress:
                    done_mb = round(downloaded_bytes / (1024 * 1024))
                    total_mb = max(1, round(total_bytes / (1024 * 1024)))
                    on_progress(f"Scarico il motore di trascrizione: {pct}% ({done_mb} di {total_mb} MB{eta_part})")
            if proc.poll() is not None:
                break
            time.sleep(0.2)
    finally:
        reader.join(timeout=2.0)
        rc = proc.wait()

    if cancelled or (cancel_token is not None and getattr(cancel_token, "cancelled", False)):
        raise RuntimeError("Trascrizione annullata")
    if rc != 0:
        with reader_lock:
            detail = shared["last_line"]
        raise ComponentError(detail or f"Download del modello parakeet-v3 non riuscito (codice {rc}).")


def _download_macparakeet_under_lock(
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
    active_entry: Optional[_ActiveDownload] = None,
) -> str:
    bin_path = macparakeet_bin_path()
    part_path = macparakeet_part_path()
    total_approx = MACPARAKEET_APPROX_BYTES

    if not (os.path.isfile(bin_path) and os.access(bin_path, os.X_OK)):
        started = time.monotonic()
        last_emit = started - 1.5
        last_pct = -1

        def on_tar_bytes(done: int, total_hint: Optional[int]) -> None:
            nonlocal last_emit, last_pct
            tar_total = total_hint or MACPARAKEET_TARBALL_BYTES
            overall_total = tar_total + MACPARAKEET_MODEL_APPROX_BYTES
            pct = min(99, max(0, int(done * 100 / overall_total))) if overall_total else 0
            now = time.monotonic()
            if pct != last_pct and (now - last_emit >= 0.5 or pct == 0):
                last_emit = now
                last_pct = pct
                _write_component_state(MACPARAKEET_ID, {
                    "state": "downloading",
                    "auto_resume": True,
                    "pid": os.getpid(),
                    "downloaded_bytes": done,
                    "total_bytes": overall_total,
                    "percent": pct,
                    "eta_seconds": None,
                    "eta_label": None,
                    "error": None,
                })
                if on_progress:
                    done_mb = round(done / (1024 * 1024))
                    total_mb = max(1, round(overall_total / (1024 * 1024)))
                    on_progress(f"Scarico il motore di trascrizione: {pct}% ({done_mb} di {total_mb} MB)")

        _download_macparakeet_tarball(part_path, on_bytes=on_tar_bytes, cancel_token=cancel_token)
        _extract_and_verify_macparakeet(part_path, bin_path)

    tarball_bytes = os.path.getsize(bin_path) if os.path.isfile(bin_path) else MACPARAKEET_TARBALL_BYTES
    _download_macparakeet_model(
        bin_path,
        tarball_bytes=tarball_bytes,
        on_progress=on_progress,
        cancel_token=cancel_token,
        active_entry=active_entry,
    )

    ready_size = _macparakeet_ready_bytes() or total_approx
    _write_component_state(MACPARAKEET_ID, {
        "state": "ready",
        "model_ready": True,
        "auto_resume": False,
        "pid": None,
        "helper_pid": None,
        "downloaded_bytes": ready_size,
        "total_bytes": ready_size,
        "percent": 100,
        "eta_seconds": None,
        "eta_label": None,
        "error": None,
    })
    return bin_path


def ensure_macparakeet(
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
) -> str:
    """Assicura che macparakeet-cli e il modello parakeet-v3 siano pronti su Mac Apple Silicon."""
    from rt.pipeline.setup import find_macparakeet_binary

    existing = find_macparakeet_binary()
    local_bin = macparakeet_bin_path()
    has_local = os.path.isfile(local_bin) and os.access(local_bin, os.X_OK)
    if existing and not _macparakeet_incomplete_download() and not (has_local and not macparakeet_ready()):
        return existing

    if not macparakeet_available():
        raise ComponentUnavailable("macparakeet funziona solo su Mac con Apple Silicon.")

    lpath = lock_path_for(MACPARAKEET_ID)
    last_emit = 0.0
    last_pct = -1

    while True:
        existing = find_macparakeet_binary()
        has_local = os.path.isfile(local_bin) and os.access(local_bin, os.X_OK)
        if existing and not _macparakeet_incomplete_download() and not (has_local and not macparakeet_ready()):
            return existing

        if cancel_token is not None and hasattr(cancel_token, "raise_if_cancelled"):
            cancel_token.raise_if_cancelled()
        elif cancel_token is not None and getattr(cancel_token, "cancelled", False):
            raise RuntimeError("Trascrizione annullata")

        if _acquire_nonblocking(lpath):
            stopped = threading.Event()
            renewer = threading.Thread(target=_renew_lock_loop, args=(lpath, stopped), daemon=True)
            renewer.start()
            try:
                existing = find_macparakeet_binary()
                has_local = os.path.isfile(local_bin) and os.access(local_bin, os.X_OK)
                if existing and not _macparakeet_incomplete_download() and not (has_local and not macparakeet_ready()):
                    return existing
                _write_component_state(MACPARAKEET_ID, {
                    "state": "downloading",
                    "auto_resume": True,
                    "pid": os.getpid(),
                    "error": None,
                })
                return _download_macparakeet_under_lock(on_progress=on_progress, cancel_token=cancel_token)
            except RuntimeError as exc:
                if "annullat" in str(exc).lower():
                    _write_component_state(MACPARAKEET_ID, {
                        "state": "paused",
                        "auto_resume": False,
                        "pid": None,
                        "helper_pid": None,
                        "error": None,
                    })
                else:
                    _write_component_state(MACPARAKEET_ID, {
                        "state": "error",
                        "auto_resume": False,
                        "pid": None,
                        "helper_pid": None,
                        "error": str(exc),
                    })
                raise
            except Exception as exc:
                _write_component_state(MACPARAKEET_ID, {
                    "state": "error",
                    "auto_resume": False,
                    "pid": None,
                    "helper_pid": None,
                    "error": str(exc),
                })
                raise
            finally:
                stopped.set()
                renewer.join(timeout=1.0)
                release_file_lock(lpath)

        if on_progress:
            status = get_component(MACPARAKEET_ID)
            pct = status.get("percent")
            now = time.monotonic()
            if (pct is not None and pct != last_pct) or (now - last_emit >= 1.5):
                last_emit = now
                if pct is not None:
                    last_pct = pct
                    done_mb = round((status.get("downloaded_bytes") or 0) / (1024 * 1024))
                    total_mb = max(1, round((status.get("total_bytes") or MACPARAKEET_APPROX_BYTES) / (1024 * 1024)))
                    eta = status.get("eta_label")
                    eta_part = f", {eta}" if eta else ""
                    on_progress(f"Scarico il motore di trascrizione: {pct}% ({done_mb} di {total_mb} MB{eta_part})")
                else:
                    on_progress("In attesa del motore di trascrizione…")
        time.sleep(0.5)


def _parse_playwright_progress(line: str) -> Tuple[Optional[int], Optional[int]]:
    pct_match = re.search(r"(\d{1,3})%", line)
    pct = min(100, max(0, int(pct_match.group(1)))) if pct_match else None
    size_match = re.search(r"of\s+([\d.]+)\s*(KiB|KB|MiB|MB|GiB|GB)", line, re.IGNORECASE)
    total_bytes: Optional[int] = None
    if size_match:
        val = float(size_match.group(1))
        unit = size_match.group(2).lower()
        mult = {
            "kib": 1024, "kb": 1000,
            "mib": 1024 * 1024, "mb": 1000 * 1000,
            "gib": 1024 * 1024 * 1024, "gb": 1000 * 1000 * 1000,
        }[unit]
        total_bytes = int(val * mult)
    return pct, total_bytes


def run_browser_download_sync(
    cancel_event: Optional[threading.Event] = None,
    active_entry: Optional[_ActiveDownload] = None,
) -> bool:
    """Scarica Chromium Playwright scrivendo in logs/browser-install.log e components.json."""
    if not browser_available():
        raise ComponentUnavailable("Pacchetto playwright non installato.")
    target = browsers_dir()
    if browser_ready(target):
        size = _browser_disk_bytes()
        _write_component_state(BROWSER_ID, {
            "state": "ready",
            "auto_resume": False,
            "pid": None,
            "downloaded_bytes": size,
            "total_bytes": size,
            "percent": 100,
            "eta_seconds": None,
            "eta_label": None,
            "error": None,
        })
        return True

    lpath = lock_path_for(BROWSER_ID)
    if not _acquire_nonblocking(lpath):
        return False

    stopped = threading.Event()
    renewer = threading.Thread(target=_renew_lock_loop, args=(lpath, stopped), daemon=True)
    renewer.start()
    log_file_path = os.path.join(paths.data_dir(), "logs", "browser-install.log")
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    os.makedirs(target, exist_ok=True)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": target}
    kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

    _write_component_state(BROWSER_ID, {
        "state": "downloading",
        "auto_resume": True,
        "pid": os.getpid(),
        "downloaded_bytes": 0,
        "total_bytes": BROWSER_APPROX_BYTES,
        "percent": 0,
        "eta_seconds": None,
        "eta_label": None,
        "error": None,
    })

    proc: Optional[subprocess.Popen[bytes]] = None
    last_line = ""
    cancelled = False
    started = time.monotonic()
    last_emit = started - 1.0
    last_pct = -1
    known_total = BROWSER_APPROX_BYTES

    try:
        with open(log_file_path, "a", encoding="utf-8") as log_stream:
            proc = subprocess.Popen(
                [sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                **kwargs,
            )
            if active_entry is not None:
                active_entry.process = proc
            _write_component_state(BROWSER_ID, {"pid": proc.pid, "helper_pid": os.getpid()})

            buf = b""
            assert proc.stdout is not None
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    proc.terminate()
                    break
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                log_stream.write(text)
                log_stream.flush()
                buf += chunk
                parts = re.split(rb"[\r\n]+", buf)
                buf = parts.pop() if parts else b""
                for raw_line in parts:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    last_line = line
                    pct, total_b = _parse_playwright_progress(line)
                    if total_b:
                        known_total = total_b
                    if pct is not None:
                        now = time.monotonic()
                        if pct != last_pct and (now - last_emit >= 0.5 or pct in (0, 100)):
                            last_emit = now
                            last_pct = pct
                            elapsed = now - started
                            eta_seconds = None
                            eta_label = None
                            if elapsed >= 2.0 and 0 < pct < 100:
                                eta_seconds = elapsed * (100 - pct) / pct
                                eta_label = onnx_stt._format_eta_short(eta_seconds)
                            _write_component_state(BROWSER_ID, {
                                "state": "downloading",
                                "auto_resume": True,
                                "downloaded_bytes": int(known_total * pct / 100),
                                "total_bytes": known_total,
                                "percent": pct,
                                "eta_seconds": eta_seconds,
                                "eta_label": eta_label,
                                "error": None,
                            })
            rc = proc.wait()
        if cancelled or (cancel_event is not None and cancel_event.is_set()):
            _write_component_state(BROWSER_ID, {
                "state": "paused",
                "auto_resume": False,
                "pid": None,
                "helper_pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
            return False
        if rc != 0:
            _write_component_state(BROWSER_ID, {
                "state": "error",
                "auto_resume": False,
                "pid": None,
                "helper_pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": last_line or f"Installazione browser non riuscita (codice {rc}).",
            })
            return False
        ready_size = _browser_disk_bytes() or known_total
        _write_component_state(BROWSER_ID, {
            "state": "ready",
            "auto_resume": False,
            "pid": None,
            "helper_pid": None,
            "downloaded_bytes": ready_size,
            "total_bytes": ready_size,
            "percent": 100,
            "eta_seconds": None,
            "eta_label": None,
            "error": None,
        })
        return True
    except BaseException as exc:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                pass
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            _write_component_state(BROWSER_ID, {
                "state": "paused",
                "auto_resume": False,
                "pid": None,
                "helper_pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
            raise
        _write_component_state(BROWSER_ID, {
            "state": "error",
            "auto_resume": False,
            "pid": None,
            "helper_pid": None,
            "eta_seconds": None,
            "eta_label": None,
            "error": str(exc),
        })
        return False
    finally:
        stopped.set()
        renewer.join(timeout=1.0)
        release_file_lock(lpath)


def _run_transcription_thread(active_entry: _ActiveDownload) -> None:
    lpath = lock_path_for(TRANSCRIPTION_ID)
    if not _acquire_nonblocking(lpath):
        return
    stopped = threading.Event()
    renewer = threading.Thread(target=_renew_lock_loop, args=(lpath, stopped), daemon=True)
    renewer.start()
    try:
        if onnx_stt.model_ready():
            ready_size = _transcription_ready_bytes()
            _write_component_state(TRANSCRIPTION_ID, {
                "state": "ready",
                "auto_resume": False,
                "pid": None,
                "downloaded_bytes": ready_size,
                "total_bytes": ready_size,
                "percent": 100,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
            return
        _download_transcription_under_lock(cancel_token=_CancelFlag(active_entry.cancel_event))
    except RuntimeError as exc:
        if "annullat" in str(exc).lower():
            _write_component_state(TRANSCRIPTION_ID, {
                "state": "paused",
                "auto_resume": False,
                "pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
        else:
            _write_component_state(TRANSCRIPTION_ID, {
                "state": "error",
                "auto_resume": False,
                "pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": str(exc),
            })
    except Exception as exc:
        _write_component_state(TRANSCRIPTION_ID, {
            "state": "error",
            "auto_resume": False,
            "pid": None,
            "eta_seconds": None,
            "eta_label": None,
            "error": str(exc),
        })
    finally:
        stopped.set()
        renewer.join(timeout=1.0)
        release_file_lock(lpath)
        with _active_lock:
            if _active.get(TRANSCRIPTION_ID) is active_entry:
                _active.pop(TRANSCRIPTION_ID, None)


def _run_macparakeet_thread(active_entry: _ActiveDownload) -> None:
    lpath = lock_path_for(MACPARAKEET_ID)
    if not _acquire_nonblocking(lpath):
        return
    stopped = threading.Event()
    renewer = threading.Thread(target=_renew_lock_loop, args=(lpath, stopped), daemon=True)
    renewer.start()
    try:
        if macparakeet_ready():
            ready_size = _macparakeet_ready_bytes()
            _write_component_state(MACPARAKEET_ID, {
                "state": "ready",
                "model_ready": True,
                "auto_resume": False,
                "pid": None,
                "helper_pid": None,
                "downloaded_bytes": ready_size,
                "total_bytes": ready_size,
                "percent": 100,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
            return
        _download_macparakeet_under_lock(
            cancel_token=_CancelFlag(active_entry.cancel_event),
            active_entry=active_entry,
        )
    except RuntimeError as exc:
        if "annullat" in str(exc).lower():
            _write_component_state(MACPARAKEET_ID, {
                "state": "paused",
                "auto_resume": False,
                "pid": None,
                "helper_pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
        else:
            _write_component_state(MACPARAKEET_ID, {
                "state": "error",
                "auto_resume": False,
                "pid": None,
                "helper_pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": str(exc),
            })
    except Exception as exc:
        _write_component_state(MACPARAKEET_ID, {
            "state": "error",
            "auto_resume": False,
            "pid": None,
            "helper_pid": None,
            "eta_seconds": None,
            "eta_label": None,
            "error": str(exc),
        })
    finally:
        stopped.set()
        renewer.join(timeout=1.0)
        release_file_lock(lpath)
        with _active_lock:
            if _active.get(MACPARAKEET_ID) is active_entry:
                _active.pop(MACPARAKEET_ID, None)


def _run_browser_thread(active_entry: _ActiveDownload) -> None:
    try:
        run_browser_download_sync(cancel_event=active_entry.cancel_event, active_entry=active_entry)
    finally:
        with _active_lock:
            if _active.get(BROWSER_ID) is active_entry:
                _active.pop(BROWSER_ID, None)


def _extract_libreoffice_macos(dmg_path: str, partial_dir: str) -> str:
    shutil.rmtree(partial_dir, ignore_errors=True)
    os.makedirs(partial_dir, exist_ok=True)
    mount_dir = tempfile.mkdtemp(prefix="rt-lo-mnt-")
    mounted = False
    try:
        subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount_dir, dmg_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        mounted = True
        src_app = os.path.join(mount_dir, "LibreOffice.app")
        if not os.path.isdir(src_app):
            raise ComponentError("Immagine LibreOffice incompleta: LibreOffice.app mancante.")
        dst_app = os.path.join(partial_dir, "LibreOffice.app")
        subprocess.run(["ditto", src_app, dst_app], check=True, capture_output=True, text=True, timeout=240)
    except ComponentError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComponentError(f"Estrazione di LibreOffice non riuscita: {exc}") from exc
    finally:
        if mounted:
            subprocess.run(["hdiutil", "detach", mount_dir], check=False, capture_output=True, timeout=30)
        shutil.rmtree(mount_dir, ignore_errors=True)
    return os.path.join(partial_dir, "LibreOffice.app", "Contents", "MacOS", "soffice")


def _find_windows_soffice_root(root_dir: str) -> Optional[str]:
    for walk_root, _dirs, files in os.walk(root_dir):
        if os.path.basename(walk_root).lower() == "program" and any(f.lower() == "soffice.exe" for f in files):
            return os.path.dirname(walk_root)
    return None


def _extract_libreoffice_windows(msi_path: str, partial_dir: str) -> str:
    shutil.rmtree(partial_dir, ignore_errors=True)
    os.makedirs(partial_dir, exist_ok=True)
    tmp_dir = os.path.join(components_dir(), "libreoffice-tmp")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        subprocess.run(
            ["msiexec", "/a", msi_path, "/qn", f"TARGETDIR={tmp_dir}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            **kwargs,
        )
        found_root = _find_windows_soffice_root(tmp_dir)
        if not found_root:
            raise ComponentError("Estrazione di LibreOffice non riuscita: program\\soffice.exe mancante.")
        for entry in os.listdir(found_root):
            shutil.move(os.path.join(found_root, entry), os.path.join(partial_dir, entry))
    except ComponentError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComponentError(f"Estrazione di LibreOffice non riuscita: {exc}") from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return os.path.join(partial_dir, "program", "soffice.exe")


def _verify_libreoffice_binary(exe_path: str) -> None:
    if not os.path.isfile(exe_path):
        raise ComponentError("Installazione di LibreOffice incompleta: eseguibile soffice mancante.")
    kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    try:
        subprocess.run(
            [exe_path, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ComponentError(f"Verifica di LibreOffice non riuscita: {exc}") from exc


def _download_libreoffice_under_lock(cancel_token: Optional[Any] = None) -> str:
    spec = _libreoffice_platform_spec()
    if spec is None:
        raise ComponentUnavailable("LibreOffice portabile non disponibile su questo sistema.")
    url, approx_bytes, expected_sha256, ext = spec
    part_path = os.path.join(components_dir(), f"libreoffice{ext}.part")
    partial_dir = libreoffice_partial_dir()
    final_dir = libreoffice_dir()

    started = time.monotonic()
    initial_bytes = _entry_size(part_path)
    last_emit = started - 1.5
    last_pct = -1

    def on_bytes(done: int, total_hint: Optional[int]) -> None:
        nonlocal last_emit, last_pct
        total = total_hint or approx_bytes
        pct = min(99, max(0, int(done * 99 / total))) if total else 0
        now = time.monotonic()
        if pct != last_pct and (now - last_emit >= 0.5 or pct in (0, 99)):
            last_emit = now
            last_pct = pct
            elapsed = now - started
            session_bytes = max(0, done - initial_bytes)
            remaining = max(0, total - done)
            eta_seconds: Optional[float] = None
            eta_label: Optional[str] = None
            if elapsed >= 2.0 and session_bytes > 0 and remaining > 0:
                speed = session_bytes / elapsed
                if speed > 0:
                    eta_seconds = remaining / speed
                    eta_label = onnx_stt._format_eta_short(eta_seconds)
            _write_component_state(LIBREOFFICE_ID, {
                "state": "downloading",
                "auto_resume": True,
                "pid": os.getpid(),
                "downloaded_bytes": done,
                "total_bytes": total,
                "percent": pct,
                "eta_seconds": eta_seconds,
                "eta_label": eta_label,
                "error": None,
            })

    _download_resumable_file(
        url,
        part_path,
        expected_sha256=expected_sha256,
        offline_env="RT_LIBREOFFICE_OFFLINE",
        label="LibreOffice",
        cancel_message="Download annullato",
        on_bytes=on_bytes,
        cancel_token=cancel_token,
    )

    if cancel_token is not None and getattr(cancel_token, "cancelled", False):
        raise RuntimeError("Download annullato")

    downloaded_size = _entry_size(part_path) or approx_bytes
    _write_component_state(LIBREOFFICE_ID, {
        "state": "downloading",
        "auto_resume": True,
        "pid": os.getpid(),
        "downloaded_bytes": downloaded_size,
        "total_bytes": downloaded_size,
        "percent": 99,
        "eta_seconds": None,
        "eta_label": "Preparo…",
        "error": None,
    })

    actual_sha = _sha256_file(part_path)
    if actual_sha != expected_sha256.lower():
        try:
            os.unlink(part_path)
        except OSError:
            pass
        raise ComponentError("Verifica SHA256 di LibreOffice non riuscita.")

    try:
        if ext == ".dmg":
            exe_in_partial = _extract_libreoffice_macos(part_path, partial_dir)
        else:
            exe_in_partial = _extract_libreoffice_windows(part_path, partial_dir)
        if cancel_token is not None and getattr(cancel_token, "cancelled", False):
            raise RuntimeError("Download annullato")
        _verify_libreoffice_binary(exe_in_partial)
        shutil.rmtree(final_dir, ignore_errors=True)
        os.makedirs(os.path.dirname(final_dir), exist_ok=True)
        os.replace(partial_dir, final_dir)
    except BaseException:
        shutil.rmtree(partial_dir, ignore_errors=True)
        raise

    try:
        os.unlink(part_path)
    except OSError:
        pass

    prepare_libreoffice_runtime()
    ready_size = _libreoffice_ready_bytes() or downloaded_size
    _write_component_state(LIBREOFFICE_ID, {
        "state": "ready",
        "auto_resume": False,
        "pid": None,
        "downloaded_bytes": ready_size,
        "total_bytes": ready_size,
        "percent": 100,
        "eta_seconds": None,
        "eta_label": None,
        "error": None,
    })
    return final_dir


def _run_libreoffice_thread(active_entry: _ActiveDownload) -> None:
    lpath = lock_path_for(LIBREOFFICE_ID)
    if not _acquire_nonblocking(lpath):
        return
    stopped = threading.Event()
    renewer = threading.Thread(target=_renew_lock_loop, args=(lpath, stopped), daemon=True)
    renewer.start()
    try:
        if libreoffice_ready():
            ready_size = _libreoffice_ready_bytes()
            _write_component_state(LIBREOFFICE_ID, {
                "state": "ready",
                "auto_resume": False,
                "pid": None,
                "downloaded_bytes": ready_size,
                "total_bytes": ready_size,
                "percent": 100,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
            return
        _download_libreoffice_under_lock(cancel_token=_CancelFlag(active_entry.cancel_event))
    except RuntimeError as exc:
        if "annullat" in str(exc).lower():
            _write_component_state(LIBREOFFICE_ID, {
                "state": "paused",
                "auto_resume": False,
                "pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": None,
            })
        else:
            _write_component_state(LIBREOFFICE_ID, {
                "state": "error",
                "auto_resume": False,
                "pid": None,
                "eta_seconds": None,
                "eta_label": None,
                "error": str(exc),
            })
    except Exception as exc:
        _write_component_state(LIBREOFFICE_ID, {
            "state": "error",
            "auto_resume": False,
            "pid": None,
            "eta_seconds": None,
            "eta_label": None,
            "error": str(exc),
        })
    finally:
        stopped.set()
        renewer.join(timeout=1.0)
        release_file_lock(lpath)
        with _active_lock:
            if _active.get(LIBREOFFICE_ID) is active_entry:
                _active.pop(LIBREOFFICE_ID, None)


def start_download(component_id: str) -> Dict[str, Any]:
    meta = _component_meta(component_id)
    if not meta["available"]:
        raise ComponentUnavailable(meta["unavailable_reason"] or "Componente non disponibile.")

    if is_download_active(component_id):
        return get_component(component_id)

    current = get_component(component_id)
    if current["state"] == "ready":
        return current

    with _active_lock:
        existing = _active.get(component_id)
        if existing is not None and existing.thread.is_alive():
            return get_component(component_id)
        if _is_lock_held(lock_path_for(component_id)):
            return get_component(component_id)

        cancel_event = threading.Event()
        if component_id == TRANSCRIPTION_ID:
            target = _run_transcription_thread
        elif component_id == MACPARAKEET_ID:
            target = _run_macparakeet_thread
        elif component_id == LIBREOFFICE_ID:
            target = _run_libreoffice_thread
        else:
            target = _run_browser_thread
        entry = _ActiveDownload(thread=threading.Thread(), cancel_event=cancel_event)
        thread = threading.Thread(
            target=target,
            args=(entry,),
            name=f"rt-component-{component_id}",
            daemon=True,
        )
        entry.thread = thread
        _active[component_id] = entry
        _write_component_state(component_id, {
            "state": "downloading",
            "auto_resume": True,
            "pid": os.getpid(),
            "error": None,
        })
        thread.start()

    return get_component(component_id)


def _terminate_external_process(pid: Optional[int]) -> None:
    if not pid or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def cancel_download(component_id: str) -> Dict[str, Any]:
    _component_meta(component_id)
    entry: Optional[_ActiveDownload] = None
    with _active_lock:
        entry = _active.get(component_id)
        if entry is not None:
            entry.cancel()

    saved = _read_all_states().get(component_id) or {}
    if entry is None and is_download_active(component_id):
        if component_id in (TRANSCRIPTION_ID, MACPARAKEET_ID):
            # Lo scarica un altro processo (il worker, dentro una lezione): non si termina mai
            # un processo che potrebbe avere altri lavori in corso.
            label = "Il modello" if component_id == TRANSCRIPTION_ID else "Il motore di trascrizione"
            raise ComponentBusy(f"{label} si sta scaricando per una lezione in corso: "
                                "per fermarlo annulla la lezione.")
        if component_id == LIBREOFFICE_ID:
            raise ComponentBusy("Il convertitore delle presentazioni si sta scaricando in un altro processo.")
        # Browser: si termina solo il processo dedicato lanciato da ensure_browser_detached, e
        # solo se è lui a tenere il lock (mai un PID salvato e magari riusato da altri).
        detached = saved.get("detached_pid")
        if detached and detached == _lock_owner_pid(lock_path_for(component_id)):
            _terminate_external_process(detached)

    if entry is not None and entry.thread.is_alive():
        entry.thread.join(timeout=2.0)

    if component_id == TRANSCRIPTION_ID:
        ready = onnx_stt.model_ready()
        partial = _transcription_partial_bytes()
    elif component_id == MACPARAKEET_ID:
        ready = macparakeet_ready()
        partial = _macparakeet_partial_bytes()
    elif component_id == LIBREOFFICE_ID:
        ready = libreoffice_ready()
        partial = _libreoffice_partial_bytes()
    else:
        ready = browser_ready()
        partial = 0
    if not ready:
        _write_component_state(component_id, {
            "state": "paused" if partial > 0 or saved.get("state") == "downloading" else "not_downloaded",
            "auto_resume": False,
            "pid": None,
            "helper_pid": None,
            "eta_seconds": None,
            "eta_label": None,
            "error": None,
        })
    return get_component(component_id)


def delete_component(component_id: str) -> Dict[str, Any]:
    _component_meta(component_id)
    cancel_download(component_id)

    lpath = lock_path_for(component_id)
    deadline = time.monotonic() + 3.0
    while _is_lock_held(lpath):
        if time.monotonic() >= deadline:
            raise ComponentBusy("Download ancora in corso: attendi qualche secondo e riprova.")
        time.sleep(0.1)

    if component_id == TRANSCRIPTION_ID:
        for path in (
            onnx_stt.model_dir(),
            onnx_stt.model_dir() + ".partial",
        ):
            shutil.rmtree(path, ignore_errors=True)
        onnx_stt._cleanup_legacy_models()
        onnx_stt.clear_loaded()
    elif component_id == MACPARAKEET_ID:
        for path in (macparakeet_bin_path(), macparakeet_part_path()):
            if os.path.isfile(path) or os.path.islink(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        bin_dir = macparakeet_bin_dir()
        if os.path.isdir(bin_dir):
            for name in os.listdir(bin_dir):
                if name.startswith("macparakeet-cli.") and name.endswith(".tmp"):
                    try:
                        os.unlink(os.path.join(bin_dir, name))
                    except OSError:
                        pass
        # Il modello in FluidAudio/Models è condiviso con l'app MacParakeet: se c'è, non lo tocchiamo
        # (la cartella Application Support/MacParakeet la crea anche la CLI: conta solo l'app installata)
        shared = any(os.path.isdir(os.path.join(d, "MacParakeet.app"))
                     for d in ("/Applications", os.path.expanduser("~/Applications")))
        for entry_path in ([] if shared else _macparakeet_model_entries()):
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path, ignore_errors=True)
            else:
                try:
                    os.unlink(entry_path)
                except OSError:
                    pass
    elif component_id == LIBREOFFICE_ID:
        for dir_path in (
            libreoffice_dir(),
            libreoffice_partial_dir(),
            os.path.join(components_dir(), "libreoffice-tmp"),
            libreoffice_profile_dir(),
            libreoffice_fontcache_dir(),
        ):
            shutil.rmtree(dir_path, ignore_errors=True)
        for file_path in (
            os.path.join(components_dir(), "libreoffice.dmg.part"),
            os.path.join(components_dir(), "libreoffice.msi.part"),
            libreoffice_fonts_conf_path(),
        ):
            if os.path.isfile(file_path) or os.path.islink(file_path):
                try:
                    os.unlink(file_path)
                except OSError:
                    pass
    else:
        folder = browsers_dir()
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                if name.startswith("chromium"):
                    shutil.rmtree(os.path.join(folder, name), ignore_errors=True)
    _clear_component_state(component_id)
    return get_component(component_id)


def resume_interrupted_downloads() -> List[str]:
    """Riprende al riavvio i download interrotti prima della chiusura di RT."""
    resumed: List[str] = []
    states = _read_all_states()
    for cid in VALID_COMPONENT_IDS:
        saved = states.get(cid) or {}
        if not saved.get("auto_resume"):
            continue
        if is_download_active(cid):
            continue
        status = get_component(cid)
        if status["state"] in ("ready", "error") or not status["available"]:
            continue
        try:
            start_download(cid)
            resumed.append(cid)
        except ComponentError:
            pass
    return resumed


def _ensure_fallback_download(component_id: str) -> Dict[str, Any]:
    status = get_component(component_id)
    if not status.get("available"):
        return status
    if status["state"] == "not_downloaded" and not is_download_active(component_id):
        try:
            return start_download(component_id)
        except ComponentError:
            return get_component(component_id)
    return status


def ensure_browser_fallback_download() -> Dict[str, Any]:
    """Avvia il download del browser minimo come ripiego se non è già in corso, in pausa o in errore."""
    return _ensure_fallback_download(BROWSER_ID)


def ensure_libreoffice_fallback_download() -> Dict[str, Any]:
    """Avvia il download di LibreOffice alla prima .pptx se non c'è altro convertitore."""
    return _ensure_fallback_download(LIBREOFFICE_ID)


def pdf_browser_missing_message(status: Dict[str, Any]) -> str:
    """Messaggio 409 per PDF senza nessun browser disponibile."""
    if not status.get("available"):
        return "Per il PDF serve un browser, ma il pacchetto playwright non è installato."
    state = status.get("state")
    if state == "paused":
        return (
            "Per il PDF serve un browser, ma il download del browser minimo è in pausa. "
            "Riprendilo in Impostazioni › Lavorazione delle lezioni › Componenti, poi riprova."
        )
    if state == "error":
        err = status.get("error")
        detail = f" ({err})" if err else ""
        return (
            f"Per il PDF serve un browser, ma il download del browser minimo non è riuscito{detail}. "
            "Riprova in Impostazioni › Lavorazione delle lezioni › Componenti."
        )
    return (
        "Per il PDF serve un browser: sto scaricando il browser minimo (circa 110 MB). "
        "Vedi l'avanzamento in Impostazioni › Lavorazione delle lezioni › Componenti, poi riprova."
    )


def ensure_browser_detached(say: Callable[[str], None]) -> None:
    """Avvia in background il download di Chromium Playwright usando il gestore componenti."""
    if browser_ready() or is_download_active(BROWSER_ID):
        return
    saved = _read_all_states().get(BROWSER_ID) or {}
    if saved.get("state") == "paused":
        return
    kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}
    _write_component_state(BROWSER_ID, {
        "state": "downloading",
        "auto_resume": True,
        "downloaded_bytes": 0,
        "total_bytes": BROWSER_APPROX_BYTES,
        "percent": 0,
        "error": None,
    })
    try:
        subprocess.Popen(
            [sys.executable, "-m", "rt.core.components", "--install-browser"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
        say("🌐 Scarico in background il browser per PDF e catture.")
    except OSError as exc:
        _write_component_state(BROWSER_ID, {
            "state": "error",
            "auto_resume": False,
            "error": str(exc),
        })
        say(f"⚠️  Browser per PDF e catture non scaricato: {exc}")


def _main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--install-browser" in argv:
        def _on_sigterm(_signum, _frame):
            raise SystemExit(1)

        signal.signal(signal.SIGTERM, _on_sigterm)
        _write_component_state(BROWSER_ID, {"detached_pid": os.getpid()})
        try:
            ok = run_browser_download_sync()
        finally:
            _write_component_state(BROWSER_ID, {"detached_pid": None})
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
