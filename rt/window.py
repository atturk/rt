"""
La finestra dell'app RT. API e worker continuano a lavorare quando si chiude.
pywebview viene caricato solo nell'app installata, mai per 'rt web'.
"""
import ctypes
import importlib
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

from rt.core import bundle, paths

INFO_PATH = "/impostazioni/info-aggiornamenti"
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


def _maintenance(window, command: str) -> None:
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
                raise RuntimeError(output.strip() or "Backup non riuscito.")
            prefix = "✅ Backup completo: "
            target = next((line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)), "")
            if not target:
                raise RuntimeError("Il backup non ha indicato dove ha salvato i dati.")
            _notice(window, output.strip())
            _open_path(os.path.dirname(target))
        except Exception as exc:
            _log(f"{command}: {exc}")
            _notice(window, str(exc))
    threading.Thread(target=work, name=f"rt-{command}", daemon=True).start()


def _menu(window, base_url: str):
    from webview.menu import Menu, MenuAction, MenuSeparator

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
    return [Menu("__app__" if sys.platform == "darwin" else "RT", [
        MenuAction("Controlla aggiornamenti…", lambda: window.load_url(base_url + INFO_PATH)),
        MenuSeparator(),
        MenuAction("Apri cartella dati", lambda: _open_path(paths.data_dir())),
        MenuAction("Mostra registri", lambda: _open_path(paths.sub_dir("logs", create=True))),
        MenuAction("Backup…", lambda: _maintenance(window, "backup")),
        MenuAction("Diagnostica", lambda: _maintenance(window, "doctor")),
        MenuSeparator(),
        MenuAction("Apri nel browser", browser),
        MenuAction("Ricarica", lambda: window.load_url(window.get_current_url() or base_url)),
        MenuSeparator(),
        MenuAction("Esci da RT", quit_rt),
    ])]


def _macos_menu() -> None:
    """Mantiene Modifica e assegna Cmd+Q all'uscita che ferma anche i servizi."""
    from AppKit import NSApplication
    from PyObjCTools import AppHelper

    def configure():
        menu = NSApplication.sharedApplication().mainMenu().itemAtIndex_(0).submenu()
        for item in list(menu.itemArray()):
            if item.keyEquivalent() == "q" and item.title() != "Esci da RT":
                menu.removeItem_(item)
            elif item.title() == "Esci da RT":
                item.setKeyEquivalent_("q")
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
            from rt._window_smoke import downloads
            result["downloads"] = downloads(window)
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        target = os.path.join(paths.sub_dir("logs", create=True), "window-smoke.json")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            json.dump(result, f, ensure_ascii=False)
            f.write("\n")
        window.destroy()


def open_window(base_url: str, path: str = "/") -> int:
    """Apre una sessione nella finestra; se non riesce usa il browser."""
    from rt.api import auth
    url = f"{base_url}/login?code={auth.create_login_code()}"
    window = None
    owns_pid = False
    lock = None
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
        import webview
        if sys.platform == "darwin":
            from Foundation import NSBundle
            NSBundle.mainBundle().infoDictionary()["CFBundleName"] = "RT"
        elif sys.platform == "win32":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("atturk.RT")
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
        window = webview.create_window("RT", url, width=1280, height=820, min_size=(900, 600),
                                       text_select=True, zoomable=True)
        pending_path = path if path.startswith("/") and not path.startswith("//") else "/"
        smoke_done = False
        engine_error = []

        def initialized(renderer):
            if sys.platform == "win32" and renderer != "edgechromium":
                engine_error.append("WebView2 Runtime non disponibile")
                return False

        def loaded():
            nonlocal pending_path, smoke_done
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
        with open(_pid_path(), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"{os.getpid()}\n")
        owns_pid = True
        options = {}
        if sys.platform == "win32":
            options["icon"] = os.path.join(paths.project_root(), "rt.ico")
        webview.start(menu=_menu(window, base_url), private_mode=False,
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
        if owns_pid and _read_pid() == os.getpid():
            try:
                os.remove(_pid_path())
            except OSError:
                pass
        if lock is not None:
            lock.close()
