"""
La finestra dell'app RT. API e worker continuano a lavorare quando si chiude.
pywebview viene caricato solo nell'app installata, mai per 'rt web'.
"""
import atexit
import ctypes
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import webbrowser

from rt.core import bundle, paths

INFO_PATH = "/impostazioni/info-aggiornamenti"
GUIDA_PATH = "/guida"
LOCALIZATION = {
    "global.ok": "OK", "global.cancel": "Annulla", "global.quit": "Esci",
    "global.saveFile": "Salva file", "global.quitConfirmation": "Uscire da RT?",
    "cocoa.menu.about": "Informazioni su", "cocoa.menu.services": "Servizi",
    "cocoa.menu.view": "Vista", "cocoa.menu.edit": "Modifica", "cocoa.menu.hide": "Nascondi",
    "cocoa.menu.hideOthers": "Nascondi altre", "cocoa.menu.showAll": "Mostra tutte",
    "cocoa.menu.quit": "Esci da", "cocoa.menu.fullscreen": "Attiva tutto schermo",
    "cocoa.menu.cut": "Taglia", "cocoa.menu.copy": "Copia", "cocoa.menu.paste": "Incolla",
    "cocoa.menu.selectAll": "Seleziona tutto", "windows.fileFilter.allFiles": "Tutti i file",
    "windows.fileFilter.otherFiles": "Altri tipi di file",
}


def _log(message: str) -> None:
    from rt.desktop import _sayer
    _sayer()(message)


def available() -> bool:
    if os.environ.get("RT_NO_WINDOW"):
        _log("Finestra disattivata con RT_NO_WINDOW: apro il browser.")
        return False
    if bundle.kind() is None or sys.platform not in ("darwin", "win32"):
        _log("Finestra disponibile solo nell'app per Mac e Windows: apro il browser.")
        return False
    try:
        importlib.import_module("webview")
    except Exception as exc:
        _log(f"Finestra non disponibile: {exc}. Apro il browser.")
        return False
    return True


def _pid_path() -> str:
    return os.path.join(paths.sub_dir("run", create=True), "window.pid")


def _read_pid() -> int:
    try:
        with open(_pid_path(), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _activate_existing() -> bool:
    """Riporta davanti solo la finestra appartenente al pid registrato."""
    pid = _read_pid()
    if sys.platform != "win32" or not _pid_alive(pid):
        return False
    from ctypes import wintypes
    user = ctypes.windll.user32
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    hwnd = user.FindWindowW(None, "RT")
    owner = wintypes.DWORD()
    if not hwnd:
        return False
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value != pid:
        return False
    user.ShowWindow(hwnd, 9)  # SW_RESTORE
    user.SetForegroundWindow(hwnd)
    return True


def _open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open", path])


def _notice(window, message: str) -> None:
    window.evaluate_js(f"alert({json.dumps(message)})")


def _command(command: str) -> subprocess.CompletedProcess:
    # pythonw non crea una console; le pipe raccolgono anche gli errori del comando.
    return subprocess.run([sys.executable, os.path.join(paths.project_root(), "bin", "rt"), command],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                          **({"creationflags": 0x08000000} if sys.platform == "win32" else {}))


_window_start_time = 0.0
_announced_tokens = set()


class DesktopApi:
    """API esposta da pywebview alla pagina JavaScript (window.pywebview.api)."""
    def __init__(self, window=None, base_url: str = ""):
        self._window = window
        self._base_url = base_url.rstrip("/")
        self._update_window = None

    def file_in_attesa(self) -> list:
        from rt.core import opened_files
        items = opened_files.get_unannounced_tokens(since=_window_start_time, exclude=_announced_tokens)
        for it in items:
            _announced_tokens.add(it["token"])
        return items

    def importa_collezione(self, token: str) -> dict:
        from rt.core import opened_files
        path = opened_files.consume_token(token)
        if not path:
            return {"errore": "File non trovato o token scaduto."}
        _import_collection(self._window, self._base_url, chosen=path)
        return {"ok": True}

    def apri_aggiornamento(self):
        import webview
        if self._update_window is not None:
            if hasattr(self._update_window, "show"):
                self._update_window.show()
            return self._update_window

        base = self._base_url
        if not base and self._window and hasattr(self._window, "get_current_url"):
            curr = self._window.get_current_url() or ""
            if "://" in curr:
                parts = curr.split("/", 3)
                base = f"{parts[0]}//{parts[2]}"
        url = f"{base}/app/aggiornamento" if base else "/app/aggiornamento"

        popup = webview.create_window(
            "Aggiornamento di RT",
            url,
            width=420,
            height=240,
            resizable=False,
            on_top=True,
        )
        self._update_window = popup

        def _on_closed():
            self._update_window = None

        if hasattr(popup, "events") and hasattr(popup.events, "closed"):
            popup.events.closed += _on_closed

        return popup

    def badge(self, count: int) -> None:
        from rt import window_signals
        window_signals.badge(count)

    def notifica(self, titolo: str, testo: str, percorso: str | None = None) -> None:
        from rt import window_signals
        window_signals.notifica(titolo, testo, percorso=percorso, window=self._window, base_url=self._base_url)

    def riavvia_dopo_importazione(self) -> None:
        global _import_ready
        if _import_ready:
            _import_ready = False
            _restart_after_import(self._window)

    def mostra_esportazione(self) -> None:
        if _last_export_path and os.path.isfile(_last_export_path):
            _open_path(os.path.dirname(_last_export_path))

    def salva_copia_backup(self, percorso_snapshot: str) -> dict:
        from rt.services import backup_service
        import webview

        if not self._window:
            return {"errore": "Finestra non disponibile."}

        dest_root = os.path.realpath(backup_service.default_dest())
        target_path = os.path.realpath(os.path.expanduser(percorso_snapshot))
        name = os.path.basename(target_path)
        parent = os.path.dirname(target_path)
        if not (name.startswith(backup_service.BACKUP_PREFIX) and parent == dest_root and os.path.isdir(target_path)):
            return {"errore": "Percorso snapshot non valido."}

        save_name = f"{name}.rtdb"
        try:
            import webview
            dialog_type = webview.FileDialog.SAVE
            chosen = self._window.create_file_dialog(
                dialog_type,
                save_filename=save_name,
                file_types=("Collezione RT (*.rtdb)", "Archivio zip (*.zip)"),
            )
        except Exception as exc:
            _log(f"Errore create_file_dialog: {exc}")
            return {"errore": str(exc)}

        if not chosen:
            return {"annullato": True}
        if isinstance(chosen, (list, tuple)):
            chosen = chosen[0] if chosen else None
        if not chosen:
            return {"annullato": True}

        if not (chosen.lower().endswith(".rtdb") or chosen.lower().endswith(".zip")):
            chosen += ".rtdb"

        if not _stream_backup(self._window, ["backup", "--export", target_path, "--to", chosen, "--progress-json"], tipo="copia"):
            return {"errore": "Un backup è già in corso."}
        return {"avviato": True}

    def condividi(self, percorso_api: str) -> dict:
        """Scarica una risorsa di export dall'API e apre il menu di condivisione nativo (macOS)."""
        import requests
        from rt.api import auth

        if not (isinstance(percorso_api, str) and percorso_api.startswith("/api/v1/lessons/") and "/export?" in percorso_api):
            return {"errore": "Percorso non ammesso per la condivisione."}

        base = self._base_url.rstrip('/')
        url = f"{base}{percorso_api}"
        http = requests.Session()
        try:
            # Il token salvato può mancare (es. archivio dei segreti di un altro Mac dopo un ripristino):
            # allora si apre una sessione con un codice monouso, come il link di accesso del browser.
            token = auth.saved_token()
            if token:
                http.headers["Authorization"] = f"Bearer {token}"
            else:
                http.get(f"{base}/login", params={"code": auth.create_login_code()}, allow_redirects=False, timeout=15)
        except Exception:
            pass

        try:
            resp = http.get(url, timeout=60)
            if not resp.ok:
                try:
                    data = resp.json()
                    err = data.get("error", {}).get("message") or f"Errore server ({resp.status_code})"
                except Exception:
                    err = f"Errore server ({resp.status_code})"
                return {"errore": err}
        except Exception as exc:
            return {"errore": f"Download fallito: {exc}"}

        disposition = getattr(resp, "headers", {}).get("Content-Disposition") or getattr(resp, "headers", {}).get("content-disposition") or ""
        filename = ""
        m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.IGNORECASE)
        if m:
            try:
                filename = urllib.parse.unquote(m.group(1))
            except Exception:
                filename = m.group(1)
        if not filename:
            m = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
            if m:
                filename = m.group(1)
        if not filename:
            filename = "lezione.rt"

        temp_dir = tempfile.mkdtemp(prefix="rt-condividi-")
        _condividi_temp_dirs.append(temp_dir)
        file_path = os.path.join(temp_dir, filename)
        try:
            with open(file_path, "wb") as f:
                f.write(resp.content)
        except Exception as exc:
            return {"errore": f"Impossibile salvare il file temporaneo: {exc}"}

        if sys.platform != "darwin":
            return {"errore": "Condivisione non supportata su questo sistema operativo."}

        try:
            from AppKit import NSSharingServicePicker
            from Foundation import NSURL, NSMakeRect
            from PyObjCTools import AppHelper
        except ImportError:
            return {"errore": "AppKit non disponibile per la condivisione."}

        def _open_picker():
            try:
                file_url = NSURL.fileURLWithPath_(file_path)
                picker = NSSharingServicePicker.alloc().initWithItems_([file_url])
                native = getattr(self._window, "native", None)
                content_view = getattr(native, "contentView", None)
                view = content_view() if callable(content_view) else getattr(native, "contentView", None)
                if view is not None:
                    bounds = view.bounds() if callable(getattr(view, "bounds", None)) else getattr(view, "bounds", None)
                    w = bounds.size.width if hasattr(bounds, "size") else 800
                    h = bounds.size.height if hasattr(bounds, "size") else 600
                    rect = NSMakeRect(w - 150, h - 40, 100, 30)
                    picker.showRelativeToRect_ofView_preferredEdge_(rect, view, 3)
            except Exception as exc:
                _log(f"Errore apertura picker condivisione: {exc}")

        AppHelper.callAfter(_open_picker)
        return {"ok": True}

    def salva_esportazione(self, job_id: str) -> dict:
        """Salva tutti i singoli file di un job di esportazione in una cartella scelta dall'utente."""
        if not self._window:
            return {"errore": "Finestra non disponibile."}
        from rt.services.api_jobs import exports_root
        from rt.api.jobs import queue
        info = queue().get(job_id)
        job_dir = os.path.join(exports_root(), os.path.basename(job_id))
        if not os.path.isdir(job_dir):
            return {"errore": "Esportazione non trovata."}

        main_zip = (info.result or {}).get("file") if info else None
        files = (info.result or {}).get("files") if info else None
        if not files:
            files = [f for f in sorted(os.listdir(job_dir)) if f != main_zip and not f.startswith(".")]

        if not files:
            return {"errore": "Nessun file da salvare."}

        try:
            import webview
            dialog_type = getattr(getattr(webview, "FileDialog", None), "FOLDER", getattr(webview, "FOLDER_DIALOG", 20))
            chosen = self._window.create_file_dialog(dialog_type)
        except Exception as exc:
            _log(f"Errore create_file_dialog: {exc}")
            return {"errore": str(exc)}

        if not chosen:
            return {"annullato": True}
        if isinstance(chosen, (list, tuple)):
            chosen = chosen[0] if chosen else None
        if not chosen or not os.path.isdir(chosen):
            return {"annullato": True}

        for fname in files:
            src = os.path.join(job_dir, fname)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(chosen, fname))

        _cleanup_share_dirs()
        shutil.rmtree(job_dir, ignore_errors=True)
        return {"ok": True, "count": len(files)}

    def condividi_esportazione(self, job_id: str) -> dict:
        """Condivide tutti i singoli file di un job di esportazione aprendo il picker nativo (macOS)."""
        if sys.platform != "darwin":
            return {"errore": "Condivisione non supportata su questo sistema operativo."}

        from rt.services.api_jobs import exports_root
        from rt.api.jobs import queue
        info = queue().get(job_id)
        job_dir = os.path.join(exports_root(), os.path.basename(job_id))
        if not os.path.isdir(job_dir):
            return {"errore": "Esportazione non trovata."}

        main_zip = (info.result or {}).get("file") if info else None
        files = (info.result or {}).get("files") if info else None
        if not files:
            files = [f for f in sorted(os.listdir(job_dir)) if f != main_zip and not f.startswith(".")]

        if not files:
            return {"errore": "Nessun file da condividere."}

        _cleanup_share_dirs()
        temp_dir = tempfile.mkdtemp(prefix="rt-condividi-")
        _condividi_temp_dirs.append(temp_dir)

        copied = []
        for fname in files:
            src = os.path.join(job_dir, fname)
            if os.path.isfile(src):
                dst = os.path.join(temp_dir, fname)
                shutil.copy2(src, dst)
                copied.append(dst)

        if not copied:
            return {"errore": "Nessun file da condividere."}

        try:
            from AppKit import NSSharingServicePicker
            from Foundation import NSURL, NSMakeRect
            from PyObjCTools import AppHelper
        except ImportError:
            return {"errore": "AppKit non disponibile per la condivisione."}

        def _open_picker():
            try:
                file_urls = [NSURL.fileURLWithPath_(p) for p in copied]
                picker = NSSharingServicePicker.alloc().initWithItems_(file_urls)
                native = getattr(self._window, "native", None)
                content_view = getattr(native, "contentView", None)
                view = content_view() if callable(content_view) else getattr(native, "contentView", None)
                if view is not None:
                    bounds = view.bounds() if callable(getattr(view, "bounds", None)) else getattr(view, "bounds", None)
                    w = bounds.size.width if hasattr(bounds, "size") else 800
                    h = bounds.size.height if hasattr(bounds, "size") else 600
                    rect = NSMakeRect(w - 150, h - 40, 100, 30)
                    picker.showRelativeToRect_ofView_preferredEdge_(rect, view, 3)
            except Exception as exc:
                _log(f"Errore apertura picker condivisione: {exc}")

        AppHelper.callAfter(_open_picker)
        return {"ok": True}

    def pulisci_condivisione(self) -> dict:
        """Pulisce le cartelle temporanee create per la condivisione."""
        _cleanup_share_dirs()
        return {"ok": True}

    def set_zoom(self, factor: float) -> dict:
        """Imposta il fattore di zoom nativo della webview (macOS WKWebView, Windows WebView2)."""
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            return {"errore": "Fattore di zoom non valido."}

        factor = max(0.5, min(3.0, factor))

        if not self._window:
            return {"ok": False, "errore": "Finestra non disponibile."}

        native = getattr(self._window, "native", None)

        if sys.platform == "darwin":
            wv = None
            if native is not None:
                if hasattr(native, "webview"):
                    wv = native.webview
                elif hasattr(native, "contentView"):
                    cv = native.contentView
                    view = cv() if callable(cv) else cv
                    if hasattr(view, "setPageZoom_"):
                        wv = view
                    elif hasattr(view, "subviews"):
                        subviews = view.subviews() if callable(view.subviews) else view.subviews
                        for sv in subviews or []:
                            if hasattr(sv, "setPageZoom_"):
                                wv = sv
                                break
            if wv is None and hasattr(self._window, "webview"):
                wv = self._window.webview

            if wv is not None and hasattr(wv, "setPageZoom_"):
                try:
                    from PyObjCTools import AppHelper
                    AppHelper.callAfter(lambda: wv.setPageZoom_(factor))
                except Exception:
                    wv.setPageZoom_(factor)
                return {"ok": True, "factor": factor}
            elif native is not None and hasattr(native, "setPageZoom_"):
                native.setPageZoom_(factor)
                return {"ok": True, "factor": factor}

        if sys.platform == "win32":
            # Il controllo WebView2 si tocca solo dal thread dell'interfaccia: le chiamate della
            # js_api arrivano da un altro thread e un accesso diretto blocca la finestra.
            webview = getattr(native, "webview", None) if native is not None else None
            if webview is None:
                return {"ok": False, "errore": "Zoom non disponibile."}

            def apply():
                try:
                    webview.ZoomFactor = factor
                except Exception as exc:
                    _log(f"Zoom non applicato: {exc}")
            try:
                from System import Action
                native.BeginInvoke(Action(apply))
            except Exception as exc:
                _log(f"Zoom non applicato: {exc}")
                return {"ok": False, "errore": "Zoom non disponibile."}
            return {"ok": True, "factor": factor}

        if hasattr(self._window, "set_zoom"):
            self._window.set_zoom(factor)
            return {"ok": True, "factor": factor}
        if hasattr(native, "set_zoom"):
            native.set_zoom(factor)
            return {"ok": True, "factor": factor}

        return {"ok": True, "factor": factor}


_condividi_temp_dirs: list[str] = []


def _cleanup_share_dirs():
    for d in _condividi_temp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    _condividi_temp_dirs.clear()


def _cleanup_old_share_dirs():
    now = time.time()
    tmp = tempfile.gettempdir()
    try:
        for entry in os.listdir(tmp):
            if entry.startswith("rt-condividi-"):
                full = os.path.join(tmp, entry)
                try:
                    if os.path.isdir(full) and (now - os.path.getmtime(full) > 86400):
                        shutil.rmtree(full, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


atexit.register(_cleanup_share_dirs)
_cleanup_old_share_dirs()


_backup_lock = threading.Lock()
_backup_running = False


def _stream_backup(window, args: list[str], tipo: str = "backup", *, before_start=None, on_success=None,
                   on_failure=None) -> bool:
    global _backup_running
    with _backup_lock:
        if _backup_running:
            # Un backup o una copia è già in corso: il popup resta su quello, il nuovo non parte.
            _notice(window, "Un backup è già in corso.")
            return False
        _backup_running = True

    def work():
        global _backup_running
        has_client = False
        fallback_lines = []
        last_sent_time = 0.0
        pending_event = None

        def send_event(event: dict, immediate: bool = False):
            nonlocal has_client, last_sent_time, pending_event
            event.setdefault("tipo", tipo)
            now = time.monotonic()
            if not immediate and (now - last_sent_time < 0.1):
                pending_event = event
                return
            pending_event = None
            last_sent_time = now
            try:
                res = window.evaluate_js(f"Boolean(window.__rtBackup && (window.__rtBackup({json.dumps(event)}), true))")
                if res:
                    has_client = True
            except Exception as exc:
                _log(f"evaluate_js errore: {exc}")

        try:
            send_event({"inizio": True, "tipo": tipo}, immediate=True)

            if before_start:
                before_start()
            cmd = [sys.executable, os.path.join(paths.project_root(), "bin", "rt"), *args]
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                **kwargs,
            )

            final_event_sent = False
            succeeded = False
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    fallback_lines.append(line)
                    continue

                if "fine" in event or "errore" in event:
                    succeeded = bool(event.get("fine"))
                    if succeeded and tipo == "esporta":
                        global _last_export_path
                        _last_export_path = event.get("percorso")
                    if pending_event:
                        send_event(pending_event, immediate=True)
                    send_event(event, immediate=True)
                    final_event_sent = True
                    if not has_client:
                        if "riepilogo" in event:
                            _notice(window, "\n".join(event["riepilogo"]))
                        elif "errore" in event:
                            _notice(window, event["errore"])
                else:
                    send_event(event, immediate=False)

            proc.wait()
            if proc.returncode == 0 and succeeded and on_success:
                on_success()
            elif on_failure:
                on_failure()
            if pending_event and not final_event_sent:
                send_event(pending_event, immediate=True)

            if proc.returncode != 0 and not final_event_sent:
                err_msg = "\n".join(fallback_lines).strip() or "Operazione non riuscita."
                send_event({"errore": err_msg, "tipo": tipo}, immediate=True)
                if not has_client:
                    _notice(window, err_msg)
        except Exception as exc:
            _log(f"Backup {tipo} eccezione: {exc}")
            if on_failure:
                try:
                    on_failure()
                except Exception as failure_exc:
                    _log(f"Backup {tipo}: on_failure non riuscito: {failure_exc}")
            send_event({"errore": str(exc), "tipo": tipo}, immediate=True)
            if not has_client:
                _notice(window, str(exc))
        finally:
            with _backup_lock:
                _backup_running = False

    threading.Thread(target=work, name=f"rt-stream-{tipo}", daemon=True).start()
    return True


def _maintenance(window, command: str) -> None:
    if command == "backup":
        _stream_backup(window, ["backup", "--progress-json"], tipo="backup")
        return

    def work():
        try:
            result = _command(command)
            output = result.stdout + result.stderr
            if command == "doctor":
                target = os.path.join(paths.sub_dir("logs", create=True), "diagnostica.txt")
                with open(target, "w", encoding="utf-8", newline="\n") as f:
                    f.write(output)
                _open_path(target)
                return
            if result.returncode:
                raise RuntimeError(output.strip() or f"{command} non riuscito.")
            _notice(window, output.strip())
        except Exception as exc:
            _log(f"{command}: {exc}")
            _notice(window, str(exc))
    threading.Thread(target=work, name=f"rt-{command}", daemon=True).start()


def _check_permissions(window) -> None:
    from rt import window_permissions
    try:
        window_permissions.check(window, _notice, _open_path)
    except Exception as exc:
        _log(f"Controllo dei permessi non riuscito: {exc}")
        _notice(window, f"Non riesco a controllare i permessi: {exc}")


def _copy_to_clipboard(text: str) -> None:
    if sys.platform == "darwin":
        from AppKit import NSPasteboard, NSPasteboardTypeString
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        if not board.setString_forType_(text, NSPasteboardTypeString):
            raise RuntimeError("appunti non disponibili")
    elif sys.platform == "win32":
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True, creationflags=0x08000000)
    else:
        raise RuntimeError("appunti non disponibili su questo sistema")


def _copy_token(window) -> None:
    from rt.api import auth
    token = auth.saved_token()
    if not token:
        _notice(window, "Il token attuale non è salvato, quindi non posso copiarlo (è stato creato da "
                        "una versione precedente di RT o senza portachiavi). Usa Rigenera token: "
                        "quello nuovo viene copiato negli appunti.")
        return
    try:
        _copy_to_clipboard(token)
    except Exception as exc:
        _log(f"Token non copiato: {exc}")
        _notice(window, f"Non riesco a copiare il token negli appunti: {exc}")
        return
    _notice(window, "Token copiato negli appunti.")


def _regenerate_token(window, base_url: str) -> None:
    from rt.api import auth
    if not window.create_confirmation_dialog(
            "Rigenera token", "Il token attuale smette di funzionare: script, Swagger e browser "
            "collegati dovranno usare quello nuovo. Continuare?"):
        return
    try:
        token = auth.reset_token()
    except Exception as exc:
        _log(f"Token non rigenerato: {exc}")
        _notice(window, f"Non riesco a rigenerare il token: {exc}")
        return
    try:
        _copy_to_clipboard(token)
        copied = True
    except Exception as exc:
        _log(f"Token nuovo non copiato: {exc}")
        copied = False
    _notice(window, "Token nuovo copiato negli appunti." if copied else
            "Token rigenerato, ma non riesco a copiarlo negli appunti: riprova con Copia token.")
    # Il reset chiude anche la sessione di questa finestra: la riapre con un link monouso.
    window.load_url(f"{base_url}/login?code={auth.create_login_code()}")


def _guide_slugify(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    no_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    hyphenated = re.sub(r"[^a-z0-9]+", "-", no_accents.lower())
    return hyphenated.strip("-")


def _build_guide_menu(window, base_url: str):
    from webview.menu import Menu, MenuAction
    import yaml

    items = [
        MenuAction("Cerca nella guida…", lambda: window.load_url(f"{base_url}/guida?cerca=1"))
    ]

    guide_dir = os.path.join(paths.project_root(), "docs", "guida")
    index_file = os.path.join(guide_dir, "indice.yml")
    file_order = []
    if os.path.isfile(index_file):
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and "file" in entry:
                            file_order.append(str(entry["file"]))
                        elif isinstance(entry, str):
                            file_order.append(entry)
        except Exception:
            pass

    if not file_order and os.path.isdir(guide_dir):
        file_order = sorted([f[:-3] for f in os.listdir(guide_dir) if f.endswith(".md") and f != "COME-MODIFICARE.md"])

    for slug in file_order:
        md_path = os.path.join(guide_dir, f"{slug}.md")
        if not os.path.isfile(md_path):
            continue
        page_title = slug
        sections = []
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                for line in f:
                    trimmed = line.strip()
                    if trimmed.startswith("# ") and page_title == slug:
                        page_title = trimmed[2:].strip()
                    elif trimmed.startswith("## "):
                        sec_title = trimmed[3:].strip()
                        if sec_title:
                            anchor = _guide_slugify(sec_title)
                            sections.append((sec_title, anchor))
        except Exception:
            continue

        page_actions = []
        for sec_title, anchor in sections:
            route = f"/guida/{slug}#{anchor}" if slug != "index" else f"/guida#{anchor}"
            def make_handler(target_url):
                return lambda: window.load_url(target_url)
            page_actions.append(MenuAction(sec_title, make_handler(f"{base_url}{route}")))

        if page_actions:
            items.append(Menu(page_title, page_actions))
        else:
            route = f"/guida/{slug}" if slug != "index" else "/guida"
            items.append(MenuAction(page_title, lambda u=f"{base_url}{route}": window.load_url(u)))

    return Menu("Aiuto", items)


def _menu(window, base_url: str, api=None):
    from webview.menu import Menu, MenuAction, MenuSeparator

    def _open_update():
        target_api = api or getattr(window, "js_api", None)
        if target_api and hasattr(target_api, "apri_aggiornamento"):
            target_api.apri_aggiornamento()
        else:
            DesktopApi(window, base_url=base_url).apri_aggiornamento()

    def quit_rt():
        if window.create_confirmation_dialog("Esci da RT", "RT smetterà di lavorare in background. Uscire?"):
            def stop():
                try:
                    from rt.desktop import stop_background
                    stop_background(base_url)
                    window.destroy()
                except Exception as exc:
                    _log(f"RT non si è fermato: {exc}")
                    _notice(window, f"Non riesco a fermare RT: {exc}")
            threading.Thread(target=stop, name="rt-quit", daemon=True).start()

    def browser():
        from rt.api import auth
        webbrowser.open(f"{base_url}/login?code={auth.create_login_code()}")

    # pywebview 6.2.1 inserisce __app__ nel menu dell'applicazione su macOS.
    actions = []
    if sys.platform == "win32":
        actions.append(MenuAction("Informazioni su RT", lambda: window.load_url(base_url + INFO_PATH)))
    actions.extend([
        MenuAction("Controlla aggiornamenti…", _open_update),
        MenuSeparator(),
        MenuAction("Apri cartella dati", lambda: _open_path(paths.data_dir())),
        MenuAction("Mostra registri", lambda: _open_path(paths.sub_dir("logs", create=True))),
        MenuAction("Backup…", lambda: _maintenance(window, "backup")),
        MenuAction("Esporta tutto…", lambda: _export_collection(window)),
        MenuAction("Importa…", lambda: _import_collection(window, base_url)),
        MenuAction("Ripristina dati prima di un aggiornamento…", lambda: _restore_pre_update(window, base_url)),
        MenuAction("Diagnostica", lambda: _maintenance(window, "doctor")),
        *([MenuAction("Controlla permessi", lambda: _check_permissions(window))]
          if sys.platform in ("darwin", "win32") else []),
        MenuSeparator(),
        Menu("Autenticazione", [
            MenuAction("Copia token", lambda: _copy_token(window)),
            MenuAction("Rigenera token…", lambda: _regenerate_token(window, base_url)),
        ]),
        MenuAction("Apri nel browser", browser),
        MenuAction("Ricarica", lambda: window.load_url(window.get_current_url() or base_url)),
        MenuSeparator(),
        MenuAction("Ingrandisci", lambda: window.evaluate_js("window.rtZoom && window.rtZoom('in')")),
        MenuAction("Riduci", lambda: window.evaluate_js("window.rtZoom && window.rtZoom('out')")),
        MenuAction("Dimensioni reali", lambda: window.evaluate_js("window.rtZoom && window.rtZoom('reset')")),
        MenuSeparator(),
        MenuAction("Esci da RT", quit_rt),
    ])
    return [Menu("__app__" if sys.platform == "darwin" else "RT", actions),
            _build_guide_menu(window, base_url)]


def about_options(info: dict, versions: dict | None = None) -> dict:
    """Opzioni per il pannello Informazioni su RT del Mac."""
    from datetime import datetime
    import platform
    versions = versions or {}
    version = info.get("version") or versions.get("version")
    if not version:
        try:
            from rt.core.version import get_current_version
            version = get_current_version(paths.project_root())
        except Exception:
            version = None
        if version == "sconosciuta":
            version = None

    options: dict = {"ApplicationName": "RT"}
    if version:
        options["ApplicationVersion"] = version

    run = info.get("run")
    commit = info.get("commit")
    if run and commit:
        options["Version"] = f"build {run} · {commit}"
    elif commit:
        options["Version"] = str(commit)
    elif run:
        options["Version"] = f"build {run}"

    channel = versions.get("channel")
    if not channel:
        try:
            from rt.core.version import get_update_channel
            channel = get_update_channel()
        except Exception:
            channel = "stable"
    channel_label = "beta" if channel == "beta" else "stabile"
    credits_lines = [f"Canale aggiornamenti: {channel_label}"]

    built_at = info.get("built_at")
    if built_at:
        try:
            dt = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
            credits_lines.append(f"Compilata il {dt.strftime('%d/%m/%Y')}")
        except Exception:
            credits_lines.append(f"Compilata il {built_at}")

    py_ver = versions.get("python") or platform.python_version()
    webview_ver = versions.get("webview")
    if not webview_ver:
        try:
            from importlib.metadata import version as package_version
            webview_ver = package_version("pywebview")
        except Exception:
            webview_ver = None
    credits_lines.append(f"Python {py_ver}" + (f" · pywebview {webview_ver}" if webview_ver else ""))

    mac_ver = versions.get("macos") or platform.mac_ver()[0]
    arch = versions.get("arch") or platform.machine()
    credits_lines.append(f"macOS {mac_ver} · {arch}")

    options["credits_lines"] = credits_lines
    return options


def _show_macos_about() -> None:
    from AppKit import (NSApplication, NSAttributedString, NSColor, NSFont,
                        NSFontAttributeName, NSForegroundColorAttributeName, NSImage)
    from rt.core import bundle
    info = bundle.build_info()
    opts = about_options(info)
    credits_text = "\n".join(opts.get("credits_lines", []))
    attributes = {
        NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
        NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
    }
    credits_attr = NSAttributedString.alloc().initWithString_attributes_(credits_text, attributes)
    panel_opts = {
        "ApplicationName": opts["ApplicationName"],
        "ApplicationVersion": opts["ApplicationVersion"],
        "Credits": credits_attr,
    }
    if "Version" in opts:
        panel_opts["Version"] = opts["Version"]

    app = bundle.app_path()
    if app:
        icon_path = os.path.join(app, "Contents", "Resources", "rt.icns")
        if os.path.isfile(icon_path):
            img = NSImage.alloc().initWithContentsOfFile_(icon_path)
            if img:
                panel_opts["ApplicationIcon"] = img
    NSApplication.sharedApplication().orderFrontStandardAboutPanelWithOptions_(panel_opts)


_about_target = None


def _get_about_target():
    global _about_target
    if _about_target is None:
        try:
            from Foundation import NSObject

            class _AboutHandler(NSObject):
                def showAbout_(self, sender):
                    _show_macos_about()

            _about_target = _AboutHandler.alloc().init()
        except ImportError:
            _about_target = object()
    return _about_target


def _macos_menu() -> None:
    """Mantiene Modifica, collega Informazioni su RT e assegna Cmd+Q all'uscita."""
    from AppKit import NSApplication
    try:
        from AppKit import NSImage
    except ImportError:
        NSImage = None
    from PyObjCTools import AppHelper
    from rt.core import bundle

    def configure():
        app = bundle.app_path()
        if app and NSImage is not None:
            icon_path = os.path.join(app, "Contents", "Resources", "rt.icns")
            if os.path.isfile(icon_path):
                img = NSImage.alloc().initWithContentsOfFile_(icon_path)
                if img:
                    NSApplication.sharedApplication().setApplicationIconImage_(img)

        about_target = _get_about_target()
        main_menu = NSApplication.sharedApplication().mainMenu()
        menu = main_menu.itemAtIndex_(0).submenu()
        for item in list(menu.itemArray()):
            title = item.title() if callable(item.title) else getattr(item, "title", "")
            if item.keyEquivalent() == "q" and item.target() is None:
                menu.removeItem_(item)
            elif title == "Esci da RT":
                item.setKeyEquivalent_("q")
            elif title.startswith("Informazioni su") or title.startswith("About "):
                if hasattr(item, "setTarget_"):
                    item.setTarget_(about_target)
                if hasattr(item, "setAction_"):
                    item.setAction_("showAbout:")

        if hasattr(main_menu, "itemArray"):
            for item in list(main_menu.itemArray()):
                submenu = item.submenu() if hasattr(item, "submenu") and callable(item.submenu) else getattr(item, "submenu", None)
                sub_title = ""
                if submenu:
                    sub_title = submenu.title() if callable(submenu.title) else getattr(submenu, "title", "")
                item_title = item.title() if callable(item.title) else getattr(item, "title", "")
                if sub_title == "Aiuto" or item_title == "Aiuto":
                    target_help = submenu if submenu else item
                    if hasattr(NSApplication.sharedApplication(), "setHelpMenu_"):
                        NSApplication.sharedApplication().setHelpMenu_(target_help)
                    if hasattr(target_help, "setTitle_"):
                        target_help.setTitle_("Aiuto")
                    if hasattr(item, "setTitle_"):
                        item.setTitle_("Aiuto")
    AppHelper.callAfter(configure)


def _smoke(window) -> None:
    """La CI deve provare una pagina autenticata dentro il motore nativo."""
    result = {}
    try:
        result["page"] = window.evaluate_js("document.getElementById('root') !== null && document.title")
        result["authenticated"] = window.evaluate_js(
            "(() => { const r = new XMLHttpRequest(); r.open('GET', '/api/v1/auth/me', false); "
            "r.send(); return r.status === 200; })()")
        result["url"] = window.get_current_url()
        if result["page"] and result["authenticated"]:
            from rt._window_smoke import downloads, macos_menu
            result["downloads"] = downloads(window)
            if sys.platform == "darwin":
                result["menu"] = macos_menu()
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        target = os.path.join(paths.sub_dir("logs", create=True), "window-smoke.json")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            json.dump(result, f, ensure_ascii=False)
            f.write("\n")
        window.destroy()


def install_macos_open_files(window=None) -> None:
    """Registra application:openFiles: sul delegato dell'applicazione di pywebview."""
    try:
        import objc
        from webview.platforms import cocoa

        selector = b"application:openFiles:"

        def open_files(self, app, filenames):
            from rt.core import opened_files
            items = []
            for p in filenames or []:
                reg = opened_files.register_file(str(p))
                if reg:
                    items.append({"token": reg["token"], "name": reg["name"], "size": reg["size"]})
                    _announced_tokens.add(reg["token"])
            if items and window:
                window.evaluate_js(f"window.rtOpenedFiles && window.rtOpenedFiles({json.dumps(items)})")
            if hasattr(app, "replyToOpenOrPrint_"):
                app.replyToOpenOrPrint_(0)

        objc.classAddMethods(
            cocoa.BrowserView.AppDelegate,
            [objc.selector(open_files, selector=selector, signature=b"v@:@@")],
        )
    except Exception as exc:
        _log(f"Metodo openFiles non registrato: {exc}")


def open_window(base_url: str, path: str = "/") -> int:
    """Apre una sessione nella finestra; se non riesce usa il browser."""
    from rt.api import auth
    from rt.core import opened_files
    global _window_start_time
    _window_start_time = time.time()
    try:
        opened_files.cleanup_expired(600)
    except Exception:
        pass
    window = None
    owns_pid = False
    lock = None
    stop_watcher = threading.Event()
    try:
        if sys.platform == "win32" and _activate_existing():
            return 0
        if sys.platform == "win32":
            from rt.core.portable import lock_file
            # Il pid da solo non copre due doppi clic prima che compaia la finestra.
            lock = open(os.path.join(paths.sub_dir("run", create=True), "window.lock"), "a+b")
            if not lock_file(lock, blocking=False):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if _activate_existing():
                        return 0
                    time.sleep(0.2)
                _log("La finestra RT è già in apertura: riprova tra qualche secondo.")
                return 1
        url = f"{base_url}/login?code={auth.create_login_code()}&app=1"
        import webview
        if sys.platform == "darwin":
            from Foundation import NSBundle
            NSBundle.mainBundle().infoDictionary()["CFBundleName"] = "RT"
        elif sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("atturk.RT")
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
        api = DesktopApi(None, base_url=base_url)
        window = webview.create_window("RT", url, width=1280, height=820, min_size=(900, 600),
                                       text_select=True, zoomable=True, js_api=api)
        api._window = window
        pending_path = path if path.startswith("/") and not path.startswith("//") else "/"
        smoke_done = False
        permissions_ready = False
        engine_error = []

        def initialized(renderer):
            if sys.platform == "win32" and renderer != "edgechromium":
                engine_error.append("WebView2 Runtime non disponibile")
                return False

        def loaded():
            nonlocal pending_path, smoke_done, permissions_ready
            if sys.platform == "win32" and not permissions_ready:
                permissions_ready = True
                try:
                    from rt import window_permissions
                    window_permissions.install_windows(window, base_url)
                except Exception as exc:
                    _log(f"Permesso del microfono non configurato: {exc}")
            if pending_path != "/":
                target, pending_path = pending_path, "/"
                window.load_url(base_url + target)
                return
            if os.environ.get("RT_WINDOW_SMOKE") == "1" and not smoke_done:
                smoke_done = True
                _smoke(window)

        window.events.loaded += loaded
        window.events.initialized += initialized
        if sys.platform == "darwin":
            window.events.shown += _macos_menu
            try:
                from rt import window_permissions
                window_permissions.install_macos()
            except Exception as exc:
                _log(f"Microfono non configurato nella finestra: {exc}")
            try:
                install_macos_open_files(window)
            except Exception as exc:
                _log(f"Open files macOS non configurato: {exc}")

        def _watch_opened_files():
            while not stop_watcher.is_set():
                time.sleep(1)
                try:
                    from rt.core import opened_files
                    items = opened_files.get_unannounced_tokens(since=_window_start_time, exclude=_announced_tokens)
                    if items:
                        for it in items:
                            _announced_tokens.add(it["token"])
                        window.evaluate_js(f"window.rtOpenedFiles && window.rtOpenedFiles({json.dumps(items)})")
                except Exception as exc:
                    _log(f"Errore controllo file aperti: {exc}")

        threading.Thread(target=_watch_opened_files, name="rt-opened-watcher", daemon=True).start()
        with open(_pid_path(), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"{os.getpid()}\n")
        owns_pid = True
        options = {}
        if sys.platform == "win32":
            options["icon"] = os.path.join(paths.project_root(), "rt.ico")
        webview.start(menu=_menu(window, base_url, api=api), private_mode=False,
                      localization=LOCALIZATION,
                      storage_path=os.path.join(paths.data_dir(), "webview"),
                      gui="cocoa" if sys.platform == "darwin" else "edgechromium", **options)
        if engine_error:
            raise RuntimeError(engine_error[0])
        return 0
    except Exception as exc:
        _log(f"Non riesco ad aprire la finestra: {exc}. Apro il browser.")
        if window is not None and window.events.shown.is_set():
            try:
                window.destroy()
            except Exception:
                pass
        if os.environ.get("RT_WINDOW_SMOKE") == "1":
            return 1
        # Il primo caricamento potrebbe avere già consumato il codice.
        webbrowser.open(f"{base_url}/login?code={auth.create_login_code()}")
        return 0
    finally:
        stop_watcher.set()
        if owns_pid and _read_pid() == os.getpid():
            try:
                os.remove(_pid_path())
            except OSError:
                pass
        if lock is not None:
            lock.close()


_last_export_path = None
_import_ready = False


def _chosen_file(window, *, save=False):
    import webview
    chosen = window.create_file_dialog(webview.FileDialog.SAVE if save else webview.FileDialog.OPEN,
        **({'save_filename': f'RT-{time.strftime("%Y-%m-%d")}.rtdb'} if save else {}),
        file_types=('Collezione RT (*.rtdb)', 'Archivio zip (*.zip)') if save else ('Collezione RT (*.rtdb;*.zip)', 'Archivio zip (*.zip)'))
    if isinstance(chosen, (list, tuple)):
        chosen = chosen[0] if chosen else None
    if chosen and save and not (chosen.lower().endswith('.rtdb') or chosen.lower().endswith('.zip')):
        chosen += '.rtdb'
    return chosen


def _export_collection(window):
    if _backup_running:
        _notice(window, "Un trasferimento è già in corso.")
        return
    from rt.db.engine import require_database
    from rt.services.lesson_service import configured_lessons_root
    from rt.storage.migrate import folder_lessons
    try:
        chosen = _chosen_file(window, save=True)
        if not chosen:
            return
        folders = folder_lessons(require_database(), configured_lessons_root())
        if folders and not window.create_confirmation_dialog('Esporta tutto',
                f'{len(folders)} lezioni sono ancora in una cartella: le sposto nel database e continuo?'):
            return
        _stream_backup(window, ['export', chosen, '--yes', '--json'], tipo='esporta')
    except Exception as exc:
        _notice(window, str(exc))


def _restart_after_import(window):
    """Il nuovo launcher aspetta la chiusura di questa finestra prima di avviare i servizi."""
    app = bundle.app_path() if sys.platform == 'darwin' else None
    if app:
        command = ['open', '-n', app]
    elif sys.platform == 'win32' and bundle.kind():
        command = [sys.executable, os.path.join(paths.project_root(), 'bin', 'rt'), 'desktop']
    else:
        _notice(window, 'Riapri RT')
        window.destroy()
        return
    script = (
        'import sys, time, subprocess; '
        'sys.path.insert(0, sys.argv[1]); '
        'from rt.window import _pid_alive; '
        'pid=int(sys.argv[2]); '
        '\nwhile _pid_alive(pid): time.sleep(0.2)\n'
        'subprocess.Popen(sys.argv[3:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)'
    )
    kwargs = {'creationflags': 0x08000000 | 0x00000008} if sys.platform == 'win32' else {'start_new_session': True}
    subprocess.Popen([sys.executable, '-c', script, paths.project_root(), str(os.getpid()), *command],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    window.destroy()


def _import_collection(window, base_url, chosen=None):
    if _backup_running:
        _notice(window, "Un trasferimento è già in corso.")
        return
    from rt.services import backup_service as bs
    try:
        if not chosen:
            chosen = _chosen_file(window)
        if not chosen:
            return
        manifest = bs.inspect_backup_zip(chosen)
        if manifest.get('segreti') is not False:
            raise bs.BackupError('Per importare una collezione usa un file creato con «Esporta tutto».')
        created = manifest.get('created', '').split('T')[0]
        version = manifest.get('rt_version', '')
        if not window.create_confirmation_dialog('Importa',
                f'Sostituisce tutte le lezioni, il database e il calendario attuali. Quelli attuali vengono messi da parte. Collezione del {created} (RT {version}).'):
            return
        def stop():
            from rt.desktop import stop_background
            from rt.db.engine import reset_database_cache
            stop_background(base_url)
            reset_database_cache()
        def ready():
            global _import_ready
            _import_ready = True
        # I servizi sono fermi anche se l'importazione fallisce: RT va riavviato comunque.
        _stream_backup(window, ['restore', chosen, '--yes', '--json'], tipo='importa',
                       before_start=stop, on_success=ready, on_failure=ready)
    except Exception as exc:
        _notice(window, str(exc))


def _restore_pre_update(window, base_url):
    from rt.services import backup_service as bs
    backups = bs.list_pre_update_backups()
    if not backups:
        _notice(window, "Nessun backup trovato prima di un aggiornamento.")
        return
    most_recent = backups[0]
    ver = most_recent.get("version", "?")
    created = most_recent.get("created", "").replace("T", " ")[:16]
    msg = (f"Ripristinare i dati salvati con RT {ver} il {created}, prima dell'aggiornamento?\n\n"
           f"Il database e i file di testo attuali verranno messi da parte. I file audio e le immagini resteranno intatti.")
    if not window.create_confirmation_dialog("Ripristina dati prima di un aggiornamento", msg):
        return

    def stop():
        from rt.desktop import stop_background
        from rt.db.engine import reset_database_cache
        stop_background(base_url)
        reset_database_cache()

    try:
        stop()
        aside = bs.restore_pre_update_backup(most_recent["path"])
        _notice(window, f"Ripristino completato.\nI dati precedenti sono stati messi da parte in:\n{aside}\n\nRT si riavvia.")
        _restart_after_import(window)
    except Exception as exc:
        _notice(window, f"Ripristino non riuscito: {exc}")

