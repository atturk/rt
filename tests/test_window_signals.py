"""Test dei segnali visivi della finestra (badge Dock e notifiche di sistema)."""
import sys
from types import ModuleType
from unittest.mock import Mock, call

import pytest

from rt import window_signals


def test_badge_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    app = Mock()
    dock = Mock()
    app.dockTile.return_value = dock

    appkit = ModuleType("AppKit")
    appkit.NSApplication = Mock()
    appkit.NSApplication.sharedApplication.return_value = app

    called_callbacks = []
    pyobjc = ModuleType("PyObjCTools")
    app_helper = ModuleType("PyObjCTools.AppHelper")
    app_helper.callAfter = lambda fn: called_callbacks.append(fn) or fn()
    pyobjc.AppHelper = app_helper

    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "PyObjCTools", pyobjc)
    monkeypatch.setitem(sys.modules, "PyObjCTools.AppHelper", app_helper)

    # Con count > 0 imposta la stringa
    window_signals.badge(3)
    dock.setBadgeLabel_.assert_called_with("3")

    # badge(0) toglie il numero (stringa vuota)
    window_signals.badge(0)
    dock.setBadgeLabel_.assert_called_with("")


def test_badge_non_macos_does_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    # Nessun errore, non chiama AppKit
    window_signals.badge(5)


def test_notifica_macos_with_user_notification_center(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    center = Mock()
    notif = Mock()

    foundation = ModuleType("Foundation")
    foundation.NSBundle = Mock()
    bundle_inst = Mock()
    info_dict = {}
    bundle_inst.infoDictionary.return_value = info_dict
    foundation.NSBundle.mainBundle.return_value = bundle_inst
    foundation.NSUserNotificationCenter = Mock()
    foundation.NSUserNotificationCenter.defaultUserNotificationCenter.return_value = center
    foundation.NSUserNotification = Mock()
    foundation.NSUserNotification.alloc.return_value.init.return_value = notif
    class _FakeNSObject:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    foundation.NSObject = _FakeNSObject

    appkit = ModuleType("AppKit")
    appkit.NSApplication = Mock()

    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setitem(sys.modules, "AppKit", appkit)

    window_signals.notifica("Pipeline", "Lezione finita", percorso="/job/123")

    assert info_dict.get("CFBundleIdentifier") == window_signals.BUNDLE_ID
    notif.setTitle_.assert_called_with("Pipeline")
    notif.setInformativeText_.assert_called_with("Lezione finita")
    notif.setUserInfo_.assert_called_with({"percorso": "/job/123"})
    center.deliverNotification_.assert_called_with(notif)


def test_notifica_macos_fallback_to_osascript(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    foundation = ModuleType("Foundation")
    foundation.NSBundle = Mock()
    foundation.NSBundle.mainBundle.return_value = None
    foundation.NSUserNotificationCenter = Mock()
    foundation.NSUserNotificationCenter.defaultUserNotificationCenter.return_value = None

    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    run_mock = Mock()
    monkeypatch.setattr(window_signals.subprocess, "run", run_mock)

    # Notifica con caratteri speciali e virgolette
    window_signals.notifica('Job "Speciale"', 'Testo con "virgolette" e \\slash')

    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "osascript"
    assert cmd[1] == "-e"
    script = cmd[2]
    assert 'display notification "Testo con \\"virgolette\\" e \\\\slash" with title "Job \\"Speciale\\""' in script


def test_notifica_linux_does_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    run_mock = Mock()
    monkeypatch.setattr(window_signals.subprocess, "run", run_mock)

    window_signals.notifica("Titolo", "Testo")
    run_mock.assert_not_called()
