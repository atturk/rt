"""Segnali visivi e notifiche di sistema per l'app RT (badge sul Dock e notifiche)."""
import logging
import os
import subprocess
import sys
from typing import Optional

from rt.core import paths

log = logging.getLogger(__name__)

BUNDLE_ID = "com.atturk.rt"
_notif_backend_logged = False
_delegate = None
_notify_icon = None


def _log(message: str) -> None:
    try:
        from rt.desktop import _sayer
        _sayer()(message)
    except Exception:
        log.info("%s", message)


def badge(count: int) -> None:
    """Imposta o toglie il badge numerico sull'icona dell'app (Dock su macOS)."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper

        label = str(count) if count > 0 else ""

        def update():
            app = NSApplication.sharedApplication()
            if hasattr(app, "dockTile"):
                dock = app.dockTile()
                if hasattr(dock, "setBadgeLabel_"):
                    dock.setBadgeLabel_(label)

        AppHelper.callAfter(update)
    except Exception as exc:
        _log(f"Impossibile aggiornare il badge Dock: {exc}")


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _notify_macos_center(titolo: str, testo: str, percorso: Optional[str], window, base_url: Optional[str]) -> bool:
    global _notif_backend_logged, _delegate
    from AppKit import NSApplication
    from Foundation import NSBundle, NSObject, NSUserNotification, NSUserNotificationCenter

    bundle_inst = NSBundle.mainBundle()
    if bundle_inst is not None and hasattr(bundle_inst, "infoDictionary"):
        info = bundle_inst.infoDictionary()
        if info is not None and "CFBundleIdentifier" not in info:
            info["CFBundleIdentifier"] = BUNDLE_ID

    center = NSUserNotificationCenter.defaultUserNotificationCenter()
    if center is None:
        return False

    if _delegate is None:
        class _NotificationDelegate(NSObject):
            def userNotificationCenter_didActivateNotification_(self, ucenter, notification):
                try:
                    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                    user_info = notification.userInfo() if hasattr(notification, "userInfo") else None
                    path = user_info.get("percorso") if isinstance(user_info, dict) else None
                    if path and window and hasattr(window, "load_url"):
                        target_url = f"{base_url.rstrip('/')}{path}" if base_url else path
                        window.load_url(target_url)
                except Exception as exc:
                    _log(f"Errore attivazione notifica macOS: {exc}")

        alloc_fn = getattr(_NotificationDelegate, "alloc", None)
        if alloc_fn is not None:
            _delegate = alloc_fn().init()
        else:
            _delegate = _NotificationDelegate()
        if hasattr(center, "setDelegate_"):
            center.setDelegate_(_delegate)

    notif = NSUserNotification.alloc().init()
    if hasattr(notif, "setTitle_"):
        notif.setTitle_(titolo)
    if hasattr(notif, "setInformativeText_"):
        notif.setInformativeText_(testo)
    if hasattr(notif, "setUserInfo_"):
        notif.setUserInfo_({"percorso": percorso or ""})

    if hasattr(center, "deliverNotification_"):
        center.deliverNotification_(notif)

    if not _notif_backend_logged:
        _log("Notifiche: uso NSUserNotificationCenter")
        _notif_backend_logged = True
    return True


def _notify_macos_osascript(titolo: str, testo: str) -> None:
    global _notif_backend_logged
    script = f"display notification {_applescript_string(testo)} with title {_applescript_string(titolo)}"
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    if not _notif_backend_logged:
        _log("Notifiche: uso osascript (display notification)")
        _notif_backend_logged = True


def _notify_windows(titolo: str, testo: str, percorso: Optional[str], window, base_url: Optional[str]) -> None:
    global _notify_icon
    import ctypes

    FLASHW_TRAY = 0x00000002
    FLASHW_TIMERNOFG = 0x0000000C

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("hwnd", ctypes.c_void_p),
            ("dwFlags", ctypes.c_uint),
            ("uCount", ctypes.c_uint),
            ("dwTimeout", ctypes.c_uint),
        ]

    try:
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState  # check
    except Exception:
        pass

    try:
        from System import Action
        from System.Drawing import Icon
        from System.Windows.Forms import NotifyIcon, ToolTipIcon

        if _notify_icon is None:
            _notify_icon = NotifyIcon()
            icon_path = os.path.join(paths.project_root(), "rt.ico")
            if os.path.isfile(icon_path):
                _notify_icon.Icon = Icon(icon_path)

        icon = _notify_icon

        def show_balloon():
            icon.Visible = True

            def on_clicked(sender, args):
                try:
                    if window and hasattr(window, "show"):
                        window.show()
                    if percorso and window and hasattr(window, "load_url"):
                        target_url = f"{base_url.rstrip('/')}{percorso}" if base_url else percorso
                        window.load_url(target_url)
                except Exception as exc:
                    _log(f"Errore click notifica Windows: {exc}")
                finally:
                    icon.Visible = False

            icon.BalloonTipClicked += on_clicked
            icon.ShowBalloonTip(5000, titolo, testo, getattr(ToolTipIcon, "None"))

            if window and hasattr(window, "native") and hasattr(window.native, "Handle"):
                finfo = FLASHWINFO()
                finfo.cbSize = ctypes.sizeof(FLASHWINFO)
                finfo.hwnd = window.native.Handle
                finfo.dwFlags = FLASHW_TRAY | FLASHW_TIMERNOFG
                finfo.uCount = 0
                finfo.dwTimeout = 0
                ctypes.windll.user32.FlashWindowEx(ctypes.byref(finfo))

        if window and hasattr(window, "native") and hasattr(window.native, "Invoke"):
            window.native.Invoke(Action(show_balloon))
    except Exception as exc:
        _log(f"Errore notifica Windows: {exc}")


def notifica(
    titolo: str,
    testo: str,
    percorso: Optional[str] = None,
    window=None,
    base_url: Optional[str] = None,
) -> None:
    """Invia una notifica di sistema (Mac o Windows). Non solleva eccezioni."""
    if sys.platform == "darwin":
        try:
            if not _notify_macos_center(titolo, testo, percorso, window, base_url):
                _notify_macos_osascript(titolo, testo)
        except Exception as exc:
            _log(f"NSUserNotificationCenter non riuscito ({exc}), uso osascript")
            try:
                _notify_macos_osascript(titolo, testo)
            except Exception as sub_exc:
                _log(f"Notifica macOS non riuscita: {sub_exc}")
    elif sys.platform == "win32":
        try:
            _notify_windows(titolo, testo, percorso, window, base_url)
        except Exception as exc:
            _log(f"Notifica Windows non riuscita: {exc}")
    else:
        _log(f"Notifica su {sys.platform} ignorata: {titolo} - {testo}")
