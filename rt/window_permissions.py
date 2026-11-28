"""Microfono nella finestra dell'app.

pywebview non attiva i media in WKWebView e non risponde alla richiesta di WebKit, quindi macOS non
chiedeva mai il permesso e "Registra" restava spento. Qui si attivano le preferenze, si chiede
l'accesso ad AVFoundation al primo uso e la voce di menu "Controlla permessi" lo richiede di nuovo o
apre l'impostazione di sistema. Su Windows WebView2 riceve il via libera per la pagina locale: il
consenso vero resta quello di Windows.
"""
import logging
import os
import subprocess
import sys
import threading
from urllib.parse import urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
MAC_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
MAC_SETTINGS_FILES = "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"
MAC_SETTINGS_AUTOMATION = "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
MAC_SETTINGS_BACKGROUND = "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"
MAC_SETTINGS_LOCAL_NETWORK = "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"
WINDOWS_SETTINGS = "ms-settings:privacy-microphone"
WINDOWS_SETTINGS_FIREWALL = "windowsdefender://network/"

SETTINGS_URLS = {
    "darwin": {
        "microfono": MAC_SETTINGS,
        "file_e_cartelle": MAC_SETTINGS_FILES,
        "automazione": MAC_SETTINGS_AUTOMATION,
        "elementi_background": MAC_SETTINGS_BACKGROUND,
        "rete_locale": MAC_SETTINGS_LOCAL_NETWORK,
    },
    "win32": {
        "microfono": WINDOWS_SETTINGS,
        "firewall": WINDOWS_SETTINGS_FIREWALL,
    },
}
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


def request_mic_sync(timeout: float = 60.0) -> dict:
    """Richiede il microfono su macOS se ancora 'undetermined' e attende l'esito."""
    if sys.platform != "darwin":
        return {"status": "unknown"}
    status = mic_status()
    if status != "undetermined":
        return {"status": status}
    done = threading.Event()
    result = {"status": status}

    def callback(granted: bool) -> None:
        result["status"] = "authorized" if granted else "denied"
        done.set()

    try:
        request_mic(callback)
        done.wait(timeout=timeout)
    except Exception as exc:
        log.warning("Richiesta microfono non riuscita: %s", exc)
    return result


def _folder_access_status() -> dict:
    """Stato non bloccante dell'accesso alla cartella lezioni se è in Scrivania/Documenti/Download."""
    from rt.desktop import _lessons_root
    root = _lessons_root()
    if sys.platform != "darwin" or not root:
        return {"rilevante": False, "stato": "not_needed", "percorso": root}
    real_root = os.path.realpath(os.path.expanduser(root))
    protected = [os.path.realpath(os.path.expanduser(f"~/{name}")) for name in ("Desktop", "Documents", "Downloads")]
    if not any(real_root == base or real_root.startswith(base + os.sep) for base in protected):
        return {"rilevante": False, "stato": "not_needed", "percorso": root}
    try:
        os.listdir(root)
        stato = "authorized"
    except PermissionError:
        stato = "denied"
    except OSError:
        stato = "authorized"
    return {"rilevante": True, "stato": stato, "percorso": root}


def permissions_status() -> dict:
    """Stato dei permessi dell'app desktop senza mostrare alert bloccanti."""
    from rt.core.lan import lan_enabled
    from rt.core.materials import _effective_soffice
    from rt.services import service_manager as sm

    platform = sys.platform
    try:
        lan_active = bool(lan_enabled())
    except Exception:
        lan_active = False

    if platform == "darwin":
        try:
            bg_disabled = bool(sm.background_disabled())
        except Exception:
            bg_disabled = False
        return {
            "platform": platform,
            "microfono": mic_status(),
            "file_e_cartelle": _folder_access_status(),
            "automazione_keynote": {"rilevante": _effective_soffice() is None},
            "elementi_background": {"stato": "denied" if bg_disabled else "authorized"},
            "rete_locale": {"attivo": lan_active},
        }
    if platform == "win32":
        return {
            "platform": platform,
            "microfono": "unknown",
            "rete_locale": {"attivo": lan_active},
        }
    return {"platform": platform, "microfono": "unknown"}


def open_system_settings(chiave: str) -> dict:
    """Apre una sezione delle impostazioni di sistema da whitelist."""
    target = SETTINGS_URLS.get(sys.platform, {}).get(chiave)
    if not target:
        return {"ok": False, "errore": "Impostazione di sistema non disponibile."}
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
        elif sys.platform == "win32":
            try:
                os.startfile(target)
            except OSError:
                if chiave == "firewall":
                    subprocess.Popen(["control", "firewall.cpl"], creationflags=0x08000000)
                else:
                    raise
        else:
            return {"ok": False, "errore": "Piattaforma non supportata."}
        return {"ok": True}
    except Exception as exc:
        log.warning("Apertura impostazioni di sistema (%s) non riuscita: %s", chiave, exc)
        return {"ok": False, "errore": str(exc)}


def check(window, base_url: str = "") -> None:
    """Voce di menu 'Controlla permessi': apre la pagina /permessi nella finestra."""
    target = f"{base_url.rstrip('/')}/permessi" if base_url else "/permessi"
    window.load_url(target)
