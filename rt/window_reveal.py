"""Mostra nel Finder (o in Esplora file) i file appena salvati dalla finestra RT.

Impostazioni › Aspetto › «File salvati»: la preferenza `file.mostra-salvati` (default attiva)
spegne il comportamento. I file che arrivano a raffica (più download di seguito, una cartella
di file esportati) si raccolgono e si mostrano insieme, selezionati, in una sola finestra:
quella della cartella dell'ultimo file salvato.
"""
import os
import subprocess
import sys
import threading

REVEAL_PREFERENCE = "file.mostra-salvati"
_GATHER_SECONDS = 0.8

_lock = threading.Lock()
_pending: list[str] = []
_timer: threading.Timer | None = None
_installed = False


def _log(message: str) -> None:
    from rt import window
    window._log(message)


def enabled() -> bool:
    try:
        from rt.services import preferences_service
        return preferences_service.list_preferences().get(REVEAL_PREFERENCE, True) is not False
    except Exception:
        return True


def saved(paths) -> None:
    """Registra file salvati da mostrare; parte dopo una breve pausa senza nuovi file."""
    global _timer
    with _lock:
        _pending.extend(str(p) for p in paths if p)
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(_GATHER_SECONDS, _flush)
        _timer.daemon = True
        _timer.start()


def _flush() -> None:
    global _timer
    with _lock:
        files = list(dict.fromkeys(_pending))
        _pending.clear()
        _timer = None
    files = [os.path.realpath(f) for f in files if os.path.exists(f)]
    if not files or not enabled():
        return
    folder = os.path.dirname(files[-1])
    reveal([f for f in files if os.path.dirname(f) == folder])


def reveal(files: list[str]) -> None:
    """Apre la cartella dei file con i file selezionati (stessa cartella)."""
    if not files:
        return
    try:
        if sys.platform == "darwin":
            _reveal_mac(files)
        elif sys.platform == "win32":
            if not _reveal_windows(files):
                # La stringa va passata così: explorer non accetta /select, quotato da subprocess.
                subprocess.Popen(f'explorer /select,"{files[0]}"')
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(files[0])])
    except Exception as exc:
        _log(f"Impossibile mostrare i file salvati: {exc}")


def _reveal_mac(files: list[str]) -> None:
    try:
        from AppKit import NSWorkspace
        from Foundation import NSURL
        from PyObjCTools import AppHelper
    except ImportError:
        subprocess.Popen(["open", "-R", files[0]])
        return
    urls = [NSURL.fileURLWithPath_(f) for f in files]
    AppHelper.callAfter(lambda: NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(urls))


def _reveal_windows(files: list[str]) -> bool:
    """SHOpenFolderAndSelectItems seleziona più file; explorer /select ne seleziona uno."""
    import ctypes
    from ctypes import wintypes
    shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
    shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.ILFindLastID.argtypes = [ctypes.c_void_p]
    shell32.ILFindLastID.restype = ctypes.c_void_p
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                                   ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD]
    ole32.CoInitialize(None)
    folder = shell32.ILCreateFromPathW(os.path.dirname(files[0]))
    items = [p for p in (shell32.ILCreateFromPathW(f) for f in files) if p]
    try:
        if not folder or not items:
            return False
        children = (ctypes.c_void_p * len(items))(*[shell32.ILFindLastID(p) for p in items])
        return shell32.SHOpenFolderAndSelectItems(folder, len(items), children, 0) == 0
    finally:
        for p in [folder, *items]:
            if p:
                shell32.ILFree(p)


def install_download_hooks() -> None:
    """Aggancia la fine dei download del motore web (WKDownload sul Mac, WebView2 su Windows).

    Va chiamata prima di creare la finestra: pywebview legge le classi a ogni download (Mac)
    e all'avvio di WebView2 (Windows)."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        if sys.platform == "darwin":
            _install_cocoa()
        elif sys.platform == "win32":
            _install_edge()
    except Exception as exc:
        _log(f"Download non agganciati per «Mostra file salvati»: {exc}")


def _install_cocoa() -> None:
    import objc
    import AppKit
    import Foundation
    from webview.platforms.cocoa import BrowserView

    class RTDownloadDelegate(BrowserView.DownloadDelegate):
        # Come pywebview 6.2.1 (dialogo Salva in Download), più il percorso scelto.
        def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(
                self, download, response, filename, handler):
            panel = AppKit.NSSavePanel.savePanel()
            directory = Foundation.NSSearchPathForDirectoriesInDomains(
                Foundation.NSDownloadsDirectory, Foundation.NSUserDomainMask, True)[0]
            panel.setDirectoryURL_(Foundation.NSURL.fileURLWithPath_(directory))
            panel.setNameFieldStringValue_(filename)
            if panel.runModal() == AppKit.NSFileHandlingPanelOKButton:
                self.rt_path = panel.filename()
                handler(Foundation.NSURL.fileURLWithPath_(self.rt_path))
            else:
                handler(None)

        @objc.typedSelector(b"v@:@")
        def downloadDidFinish_(self, download):
            path = getattr(self, "rt_path", None)
            if path:
                saved([path])

    BrowserView.DownloadDelegate = RTDownloadDelegate


_edge_handlers = []


def _install_edge() -> None:
    from webview.platforms.edgechromium import EdgeChrome
    original = EdgeChrome.on_download_starting

    def on_download_starting(self, sender, args):
        original(self, sender, args)
        if args.Cancel:
            return
        operation = args.DownloadOperation

        def changed(op, _event):
            if str(op.State) == "Completed":
                saved([str(op.ResultFilePath)])
            if str(op.State) != "InProgress" and changed in _edge_handlers:
                _edge_handlers.remove(changed)

        _edge_handlers.append(changed)
        operation.StateChanged += changed

    EdgeChrome.on_download_starting = on_download_starting
