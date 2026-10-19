"""Microfono nella finestra dell'app.

pywebview non attiva i media in WKWebView e non risponde alla richiesta di WebKit, quindi macOS non
chiedeva mai il permesso e "Registra" restava spento. Qui si attivano le preferenze, si chiede
l'accesso ad AVFoundation al primo uso e la voce di menu "Controlla permessi" lo richiede di nuovo o
apre l'impostazione di sistema. Su Windows WebView2 riceve il via libera per la pagina locale: il
consenso vero resta quello di Windows.
"""
import logging
import sys
from urllib.parse import urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
MAC_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
WINDOWS_SETTINGS = "ms-settings:privacy-microphone"
# WKPermissionDecision
PROMPT, GRANT, DENY = 0, 1, 2

log = logging.getLogger(__name__)


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def mic_status() -> str:
    """'authorized', 'denied' (anche limitato), 'undetermined' o 'unknown'."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    except Exception as exc:
        log.warning("Stato del microfono non disponibile: %s", exc)
        return "unknown"
    return {0: "undetermined", 1: "denied", 2: "denied", 3: "authorized"}.get(int(status), "unknown")


def request_mic(callback) -> None:
    """Mostra il prompt di macOS (solo se non ancora deciso); callback(bool) arriva su un altro thread."""
    from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda granted: callback(bool(granted)))


def decide(host: str, status: str, ask) -> int | None:
    """Decisione per una richiesta di WebKit; None quando la risposta arriva da `ask` (prompt di macOS)."""
    if host not in LOCAL_HOSTS:
        return DENY
    if status == "authorized":
        return GRANT
    if status == "undetermined":
        ask()
        return None
    return DENY


def install_macos() -> None:
    """Prima di webview.start: media attivi nel WKWebView e risposta alle richieste del microfono.

    Le classi di pywebview non si sostituiscono con sottoclassi: i loro metodi chiamano
    super(BrowserView.WebKitHost, self) e andrebbero in ricorsione. Si aggiunge il metodo al
    delegato esistente e si prepara la configurazione che pywebview crea."""
    import objc
    from PyObjCTools import AppHelper
    from webview.platforms import cocoa

    selector = b"webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:"
    try:
        # Firma del blocco decisionHandler (se i metadati di pyobjc non la conoscono già).
        objc.registerMetaDataForSelector(b"NSObject", selector, {"arguments": {6: {"callable": {
            "retval": {"type": b"v"}, "arguments": {0: {"type": b"^v"}, 1: {"type": b"q"}}}}}})
    except Exception as exc:
        log.warning("Metadati del microfono non registrati: %s", exc)

    def media_permission(self, webview, origin, frame, kind, handler):
        def answer(granted):
            AppHelper.callAfter(handler, GRANT if granted else DENY)
        result = decide(str(origin.host() or ""), mic_status(), lambda: request_mic(answer))
        if result is not None:
            handler(result)

    objc.classAddMethods(cocoa.BrowserView.BrowserDelegate, [
        objc.selector(media_permission, selector=selector, signature=b"v@:@@@q@?")])

    real = cocoa.WebKit

    def configuration():
        config = real.WKWebViewConfiguration.alloc().init()
        prefs = config.preferences()
        for key, value in (("mediaDevicesEnabled", True), ("mediaRecorderEnabled", True),
                           ("mediaCaptureRequiresSecureConnection", False)):
            try:
                prefs.setValue_forKey_(value, key)
            except Exception as exc:
                log.info("Preferenza %s non disponibile: %s", key, exc)
        return config

    class _Alloc:
        def init(self):
            return configuration()

    class _Configuration:
        @staticmethod
        def alloc():
            return _Alloc()

    class _WebKit:
        """Il modulo WebKit visto da pywebview, con la configurazione già pronta per i media."""
        WKWebViewConfiguration = _Configuration

        def __getattr__(self, name):
            return getattr(real, name)

    cocoa.WebKit = _WebKit()


def install_windows(window, base_url: str) -> None:
    """Dopo l'avvio di WebView2: il microfono è consentito alla sola pagina di RT."""
    from System import Action
    from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState

    def permission(sender, args):
        if args.PermissionKind == CoreWebView2PermissionKind.Microphone and is_local(str(args.Uri)):
            args.State = CoreWebView2PermissionState.Allow
            args.Handled = True

    def configure():
        window.native.browser.webview.CoreWebView2.PermissionRequested += permission
    window.native.Invoke(Action(configure))


def check(window, notice, open_path) -> None:
    """Voce di menu "Controlla permessi"."""
    if sys.platform == "win32":
        open_path(WINDOWS_SETTINGS)
        notice(window, "Attiva il microfono per le app desktop, poi riprova a registrare.")
        return
    status = mic_status()
    if status == "undetermined":
        def done(granted):
            notice(window, "Microfono consentito." if granted else "Microfono non consentito.")
            if granted:
                window.evaluate_js("location.reload()")
        request_mic(done)
    elif status == "authorized":
        notice(window, "Microfono consentito.")
    else:
        open_path(MAC_SETTINGS)
        notice(window, "Attiva RT in Microfono, poi riapri RT.")
