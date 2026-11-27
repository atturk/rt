"""
rt.core.components
Gestione dei componenti scaricabili di RT:
- transcription: Modello di trascrizione (Parakeet ONNX + Silero VAD, ~670 MB)
- browser: Browser per le catture (Chromium Playwright, facoltativo)

Ogni componente ha un solo download attivo alla volta garantito da file lock in
<models_dir>/.lock (e .browser.lock), scrive stato e progresso in <models_dir>/components.json
letto da GET /api/v1/components e dai job del worker, e supporta pausa/ripresa (.part) e
eliminazione.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from rt.core import onnx_stt, paths
from rt.core.filelock import _expired, acquire_file_lock, release_file_lock

TRANSCRIPTION_ID = "transcription"
BROWSER_ID = "browser"
VALID_COMPONENT_IDS = (TRANSCRIPTION_ID, BROWSER_ID)

TRANSCRIPTION_APPROX_BYTES = 670 * 1024 * 1024
BROWSER_APPROX_BYTES = 170 * 1024 * 1024

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
    if component_id == BROWSER_ID:
        return os.path.join(onnx_stt.models_dir(), ".browser.lock")
    raise ComponentNotFound(f"Componente sconosciuto: {component_id}")


def browsers_dir() -> str:
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if explicit:
        return explicit
    return os.path.join(paths.data_dir(), "browsers")


def browser_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def browser_ready(target: Optional[str] = None) -> bool:
    folder = target or browsers_dir()
    if not os.path.isdir(folder):
        return False
    return any(name.startswith("chromium") for name in os.listdir(folder))


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
    return (
        _dir_size(onnx_stt._model_dir(onnx_stt.MODEL_NAME) + ".partial")
        + _dir_size(onnx_stt._model_dir(onnx_stt.VAD_NAME) + ".partial")
    )


def _transcription_ready_bytes() -> int:
    return (
        _dir_size(onnx_stt._model_dir(onnx_stt.MODEL_NAME))
        + _dir_size(onnx_stt._model_dir(onnx_stt.VAD_NAME))
    )


def _browser_disk_bytes() -> int:
    folder = browsers_dir()
    if not os.path.isdir(folder):
        return 0
    return sum(
        _dir_size(os.path.join(folder, name))
        for name in os.listdir(folder)
        if name.startswith("chromium")
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


def _component_meta(component_id: str) -> Dict[str, Any]:
    if component_id == TRANSCRIPTION_ID:
        return {
            "id": TRANSCRIPTION_ID,
            "name": "Modello di trascrizione",
            "description": "necessario per trascrivere l'audio",
            "detail": "Parakeet ONNX + VAD",
            "approx_bytes": TRANSCRIPTION_APPROX_BYTES,
            "required": True,
            "available": onnx_stt.available(),
            "unavailable_reason": None if onnx_stt.available() else "Pacchetto onnx-asr non installato.",
        }
    if component_id == BROWSER_ID:
        avail = browser_available()
        return {
            "id": BROWSER_ID,
            "name": "Browser per le catture",
            "description": "facoltativo",
            "detail": "Chromium Playwright",
            "approx_bytes": BROWSER_APPROX_BYTES,
            "required": False,
            "available": avail,
            "unavailable_reason": None if avail else "Pacchetto playwright non installato.",
        }
    raise ComponentNotFound(f"Componente sconosciuto: {component_id}")


def get_component(component_id: str) -> Dict[str, Any]:
    meta = _component_meta(component_id)
    saved = _read_all_states().get(component_id) or {}
    active = is_download_active(component_id)
    if component_id == TRANSCRIPTION_ID:
        ready = (not active) and onnx_stt.model_ready()
        disk_bytes = _transcription_ready_bytes() if ready else _transcription_partial_bytes()
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
    elif saved.get("state") == "paused" or (component_id == TRANSCRIPTION_ID and disk_bytes > 0):
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
) -> Tuple[str, str]:
    """Scarica modello + VAD assumendo il lock .lock già acquisito."""
    model_done = os.path.isdir(onnx_stt._model_dir(onnx_stt.MODEL_NAME))
    vad_done = os.path.isdir(onnx_stt._model_dir(onnx_stt.VAD_NAME))

    def handle_model_stats(stats: Dict[str, Any]) -> None:
        pct = int(stats.get("percent") or 0)
        if not vad_done and pct >= 100:
            pct = 99
        _write_component_state(TRANSCRIPTION_ID, {
            "state": "downloading",
            "auto_resume": True,
            "pid": os.getpid(),
            "downloaded_bytes": stats.get("downloaded_bytes") or 0,
            "total_bytes": stats.get("total_bytes"),
            "percent": pct,
            "eta_seconds": stats.get("eta_seconds"),
            "eta_label": stats.get("eta_label"),
            "error": None,
        })

    def handle_vad_stats(stats: Dict[str, Any]) -> None:
        pct = 99 if model_done is False else int(stats.get("percent") or 0)
        if int(stats.get("percent") or 0) >= 100:
            pct = 100
        _write_component_state(TRANSCRIPTION_ID, {
            "state": "downloading",
            "auto_resume": True,
            "pid": os.getpid(),
            "percent": pct,
            "error": None,
        })

    model_path = onnx_stt._download_resumable(
        onnx_stt.MODEL_NAME,
        onnx_stt.QUANTIZATION,
        on_progress=on_progress,
        on_stats=handle_model_stats,
        cancel_token=cancel_token,
    )
    vad_path = onnx_stt._download_resumable(
        onnx_stt.VAD_NAME,
        None,
        vad=True,
        on_progress=on_progress if model_done else None,
        on_stats=handle_vad_stats,
        cancel_token=cancel_token,
    )
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
    return model_path, vad_path


def ensure_transcription_model(
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[Any] = None,
) -> Tuple[str, str]:
    """Assicura che modello e VAD siano su disco: attende se un altro processo sta scaricando,
    altrimenti acquisisce <models>/.lock e scarica aggiornando components.json."""
    if onnx_stt.model_ready():
        return (
            onnx_stt._model_dir(onnx_stt.MODEL_NAME),
            onnx_stt._model_dir(onnx_stt.VAD_NAME),
        )

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
                    return (
                        onnx_stt._model_dir(onnx_stt.MODEL_NAME),
                        onnx_stt._model_dir(onnx_stt.VAD_NAME),
                    )
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

    return (
        onnx_stt._model_dir(onnx_stt.MODEL_NAME),
        onnx_stt._model_dir(onnx_stt.VAD_NAME),
    )


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
                [sys.executable, "-m", "playwright", "install", "chromium"],
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


def _run_browser_thread(active_entry: _ActiveDownload) -> None:
    try:
        run_browser_download_sync(cancel_event=active_entry.cancel_event, active_entry=active_entry)
    finally:
        with _active_lock:
            if _active.get(BROWSER_ID) is active_entry:
                _active.pop(BROWSER_ID, None)


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
        target = _run_transcription_thread if component_id == TRANSCRIPTION_ID else _run_browser_thread
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
        if component_id == TRANSCRIPTION_ID:
            # Lo scarica un altro processo (il worker, dentro una lezione): non si termina mai
            # un processo che potrebbe avere altri lavori in corso.
            raise ComponentBusy("Il modello si sta scaricando per una lezione in corso: "
                                "per fermarlo annulla la lezione.")
        # Browser: si termina solo il processo dedicato lanciato da ensure_browser_detached, e
        # solo se è lui a tenere il lock (mai un PID salvato e magari riusato da altri).
        detached = saved.get("detached_pid")
        if detached and detached == _lock_owner_pid(lock_path_for(component_id)):
            _terminate_external_process(detached)

    if entry is not None and entry.thread.is_alive():
        entry.thread.join(timeout=2.0)

    ready = onnx_stt.model_ready() if component_id == TRANSCRIPTION_ID else browser_ready()
    if not ready:
        partial = _transcription_partial_bytes() if component_id == TRANSCRIPTION_ID else 0
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
            onnx_stt._model_dir(onnx_stt.MODEL_NAME),
            onnx_stt._model_dir(onnx_stt.MODEL_NAME) + ".partial",
            onnx_stt._model_dir(onnx_stt.VAD_NAME),
            onnx_stt._model_dir(onnx_stt.VAD_NAME) + ".partial",
        ):
            shutil.rmtree(path, ignore_errors=True)
        onnx_stt.clear_loaded()
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
        say("🌐 Scarico in background il browser per le catture delle visualizzazioni.")
    except OSError as exc:
        _write_component_state(BROWSER_ID, {
            "state": "error",
            "auto_resume": False,
            "error": str(exc),
        })
        say(f"⚠️  Browser per le catture non scaricato: {exc}")


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
