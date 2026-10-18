"""Prove dei download nel motore nativo, usate solo con RT_WINDOW_SMOKE=1 in CI.

Si sceglie la destinazione al posto del dialogo Salva. Il download passa comunque da
WebKit/WebView2: un export ZIP autenticato dall'API e due file creati come blob in JS.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time
import zipfile

from rt.core import paths


def macos_menu() -> list[str]:
    """Controlla il menu nativo dopo la traduzione e la sostituzione di Cmd+Q."""
    from AppKit import NSApplication
    from PyObjCTools import AppHelper
    completed = threading.Event()
    errors = []

    def check():
        try:
            main = NSApplication.sharedApplication().mainMenu()
            items = main.itemAtIndex_(0).submenu().itemArray()
            exits = [item for item in items if item.title() == "Esci da RT"]
            if len(exits) != 1 or exits[0].target() is None or exits[0].keyEquivalent() != "q":
                raise RuntimeError("Il menu deve avere una sola uscita RT, con Cmd+Q e l'azione dei servizi.")
            if "Modifica" not in [item.title() for item in main.itemArray()]:
                raise RuntimeError("Manca il menu Modifica.")
        except Exception as exc:
            errors.append(str(exc))
        finally:
            completed.set()
    AppHelper.callAfter(check)
    if not completed.wait(10):
        raise RuntimeError("Il menu del Mac non ha risposto.")
    if errors:
        raise RuntimeError(errors[0])
    return ["Esci da RT", "Modifica"]


def _lesson() -> int:
    from rt.services.lesson_service import ensure_indexed
    lesson = Path(paths.data_dir()) / "window-smoke-lesson"
    lesson.mkdir(exist_ok=True)
    (lesson / "info.yaml").write_text("titolo: Prova finestra\nmateria: RT\n", encoding="utf-8", newline="\n")
    (lesson / "rielaborato.md").write_text("# Prova finestra\n\nUn export dalla finestra RT.\n",
                                        encoding="utf-8", newline="\n")
    return ensure_indexed([str(lesson)])[os.path.realpath(lesson)]


def downloads(window) -> list[str]:
    target = Path(paths.sub_dir("window-smoke-downloads", create=True))
    destination = [target / "lezione.zip"]
    events = []
    if sys.platform == "darwin":
        from Foundation import NSURL
        from webview.platforms.cocoa import BrowserView

        class RTDownloadSmokeDelegate(BrowserView.DownloadDelegate):
            def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(
                    self, download, response, filename, handler):
                handler(NSURL.fileURLWithPath_(str(destination[0])))

        BrowserView.DownloadDelegate = RTDownloadSmokeDelegate
    else:
        from System import Action
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

        def save(sender, args):
            events.append("salva " + destination[0].name)
            args.ResultFilePath = str(destination[0])
            args.Handled = True

        def permission(sender, args):
            kind = str(args.PermissionKind)
            events.append("permesso " + kind)
            if kind == "MultipleAutomaticDownloads":
                args.State = CoreWebView2PermissionState.Allow
                args.Handled = True

        def configure():
            browser = window.native.browser
            browser.webview.CoreWebView2.DownloadStarting -= browser.on_download_starting
            browser.webview.CoreWebView2.DownloadStarting += save
            browser.webview.CoreWebView2.PermissionRequested += permission
        window.native.Invoke(Action(configure))

    lesson_id = _lesson()
    cases = [
        ("lezione.zip", f"'/api/v1/lessons/{lesson_id}/export?format=zip&scope=all'"),
        ("nota.md", "URL.createObjectURL(new Blob(['# Prova finestra\\n'], {type:'text/markdown;charset=utf-8'}))"),
        ("domande.json", "URL.createObjectURL(new Blob(['{\"questions\":[]}'], {type:'application/json'}))"),
    ]
    completed = []
    for name, href in cases:
        destination[0] = target / name
        destination[0].unlink(missing_ok=True)
        # Gli export da blob usano un link non inserito nella pagina e revocano subito
        # l'URL, come LessonEditor, DetailsPanel ed exportQuestionType nel frontend.
        click = ("a.click(); URL.revokeObjectURL(a.href);" if not name.endswith(".zip")
                 else "document.body.append(a); a.click(); a.remove();")
        script = ("(() => { const a=document.createElement('a'); a.href=" + href + ";"
                  "a.download=" + json.dumps(name) + ";" + click + "})()")
        if sys.platform == "win32":
            # WebView2 blocca il secondo download automatico senza un gesto dell'utente.
            # La prova equivale al clic sul pulsante della web app, senza aprire DevTools.
            window.native.Invoke(Action(lambda: window.native.browser.webview.CoreWebView2
                                        .CallDevToolsProtocolMethodAsync("Runtime.evaluate", json.dumps(
                                            {"expression": script, "userGesture": True}))))
        else:
            window.evaluate_js(script)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                payload = destination[0].read_bytes()
                if name.endswith(".zip"):
                    with zipfile.ZipFile(destination[0]) as archive:
                        assert archive.testzip() is None
                        assert any(member.endswith("/rielaborato.md") for member in archive.namelist())
                elif name.endswith(".md"):
                    assert payload.decode("utf-8") == "# Prova finestra\n"
                else:
                    assert json.loads(payload) == {"questions": []}
                break
            except (OSError, ValueError, AssertionError, zipfile.BadZipFile):
                time.sleep(0.2)
        else:
            found = {p.name: {"size": p.stat().st_size, "inizio": p.read_bytes()[:80].hex()}
                     for p in target.iterdir() if p.is_file()}
            raise RuntimeError(f"Download di {name} non completato nel motore nativo: {found}; eventi: {events}")
        completed.append(name)
    return completed
