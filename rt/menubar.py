"""
rt.menubar
Icona di RT nella barra dei menu di macOS (processo separato lanciato da com.atturk.rt.menubar).
Su Windows e Linux non fa nulla.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import urllib.error
import urllib.request

BUNDLE_ID = "com.atturk.rt"
ACTIVE_POLL_SECONDS = 3.0
IDLE_POLL_SECONDS = 15.0
MAX_VISIBLE_JOBS = 3
ACTIVE_JOB_STATES = frozenset({"running", "queued", "waiting_for_provider"})
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "menubar")

PHASE_LABELS: Dict[str, str] = {
    "prepare": "Preparazione",
    "outline": "Scaletta",
    "rewrite": "Rielaborazione",
    "review": "Revisione",
    "build": "Documento",
    "recall": "Domande di recall",
    "setup": "Trascrizione e setup",
    "archive": "Archivio delle fonti",
    "add_images": "Immagini",
    "describe_images": "Descrizione delle immagini",
    "enrichment": "Idee per la lezione",
    "enrichment_generate": "Generazione di un'idea",
    "import_lesson_zips": "Importazione da ZIP",
    "export_lessons": "Esportazione di lezioni",
    "batch": "Batch differito",
}

JOB_TYPE_LABELS: Dict[str, str] = {
    "run_pipeline": "Pipeline completa",
    "ingest_audio": "Importazione audio",
    "ingest_sources": "Aggiunta fonti",
    "ingest_notes": "Importazione appunti",
    "update_lesson": "Aggiornamento lezione",
    "run_phase": "Fase singola",
    "rewrite_unit": "Rielaborazione unità",
    "review_unit": "Verifica unità",
    "review_part": "Verifica selezione",
    "add_images": "Immagini",
    "describe_images": "Descrizione immagini",
    "enrichment_analyze": "Idee per la lezione",
    "enrichment_generate": "Generazione idea",
    "recall_generate": "Domande di recall",
    "recall_batch": "Domande di recall",
    "recall_refill": "Rifornimento domande",
    "compact_audio": "Compressione audio",
    "import_lesson_zips": "Importazione ZIP",
    "export_lessons": "Esportazione lezioni",
}


@dataclass(frozen=True)
class MenuItem:
    """Singola voce astratta del menu di stato (separata da AppKit per i test)."""
    kind: str  # "action" | "status" | "separator" | "toggle"
    title: str = ""
    action_id: Optional[str] = None
    enabled: bool = True
    bold: bool = False
    checked: bool = False


def template_icon_path(active: bool = False) -> str:
    """Percorso dell'icona template (16 pt, con @2x automatico in AppKit)."""
    filename = "rt-active-template.png" if active else "rt-template.png"
    return os.path.join(_ASSETS_DIR, filename)


def _strip_folder_date(name: str) -> str:
    return re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\s*", "", name).strip()


def _truncate(text: str, limit: int = 48) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _job_lesson_title(job: Dict[str, Any]) -> str:
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    for candidate in (
        job.get("lesson_title"),
        job.get("titolo"),
        progress.get("lesson_title"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return _truncate(_strip_folder_date(candidate.strip()))
    lesson_path = job.get("lesson_path")
    if isinstance(lesson_path, str) and lesson_path.strip():
        base = os.path.basename(lesson_path.rstrip("/\\"))
        cleaned = _strip_folder_date(base)
        if cleaned:
            return _truncate(cleaned)
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    materia = options.get("materia")
    if isinstance(materia, str) and materia.strip():
        return _truncate(materia.strip())
    job_type = str(job.get("type") or "")
    return JOB_TYPE_LABELS.get(job_type, "Elaborazione")


def _job_phase_label(job: Dict[str, Any]) -> str:
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    phase = progress.get("phase")
    if isinstance(phase, str) and phase.strip():
        key = phase.strip()
        return PHASE_LABELS.get(key, key)
    state = job.get("state")
    if state == "queued":
        return "In coda"
    if state == "waiting_for_provider":
        return "In attesa del provider"
    job_type = str(job.get("type") or "")
    if job_type == "run_phase":
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        p_phase = str(payload.get("phase") or "").strip()
        if p_phase:
            return PHASE_LABELS.get(p_phase, p_phase)
    return JOB_TYPE_LABELS.get(job_type, "In corso")


def progress_percent(progress: Optional[Dict[str, Any]]) -> Optional[int]:
    """Percentuale intera 0..100 dai dati progress del job, o None se assente."""
    if not isinstance(progress, dict):
        return None
    if progress.get("percent") is not None:
        try:
            return max(0, min(100, round(float(progress["percent"]))))
        except (TypeError, ValueError):
            pass
    current = progress.get("current")
    total = progress.get("total")
    try:
        if current is not None and total is not None and float(total) > 0:
            return max(0, min(100, round((float(current) / float(total)) * 100)))
    except (TypeError, ValueError):
        pass
    step = progress.get("step")
    steps = progress.get("total_steps")
    try:
        if step is not None and steps is not None and float(steps) > 0:
            done = float(step) if progress.get("completed") else float(step) - 1.0
            return max(0, min(100, round((done / float(steps)) * 100)))
    except (TypeError, ValueError):
        pass
    return None


def format_job_label(job: Dict[str, Any]) -> str:
    """Formatta «<titolo lezione> — <fase> <percentuale>%»."""
    title = _job_lesson_title(job)
    phase = _job_phase_label(job)
    pct = progress_percent(job.get("progress"))
    if pct is not None:
        return f"{title} — {phase} {pct}%"
    return f"{title} — {phase}"


def filter_active_jobs(jobs: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not jobs:
        return []
    return [
        j for j in jobs
        if isinstance(j, dict) and (j.get("state") is None or j.get("state") in ACTIVE_JOB_STATES)
    ]


def menu_model(
    jobs: Optional[Sequence[Dict[str, Any]]],
    *,
    start_at_login: bool = True,
    api_reachable: bool = True,
) -> List[MenuItem]:
    """Costruisce la lista logica delle voci del menu a partire dallo stato corrente."""
    items: List[MenuItem] = [
        MenuItem(kind="action", title="Apri RT", action_id="open", enabled=True, bold=True),
        MenuItem(kind="separator"),
    ]
    if not api_reachable or jobs is None:
        items.append(MenuItem(kind="status", title="RT si sta avviando…", enabled=False))
    else:
        active = filter_active_jobs(jobs)
        if not active:
            items.append(MenuItem(kind="status", title="Nessuna elaborazione in corso", enabled=False))
        else:
            for job in active[:MAX_VISIBLE_JOBS]:
                items.append(MenuItem(kind="status", title=format_job_label(job), enabled=False))
            remaining = len(active) - MAX_VISIBLE_JOBS
            if remaining > 0:
                items.append(MenuItem(kind="status", title=f"e altre {remaining}…", enabled=False))

    items.extend([
        MenuItem(kind="separator"),
        MenuItem(
            kind="toggle",
            title="Avvia RT all'accesso",
            action_id="toggle_login",
            enabled=True,
            checked=bool(start_at_login),
        ),
        MenuItem(kind="action", title="Esci da RT", action_id="quit", enabled=True),
    ])
    return items


def poll_interval(jobs: Optional[Sequence[Dict[str, Any]]], api_reachable: bool = True) -> float:
    """Intervallo di polling: 3 s con job attivi, 15 s senza."""
    if api_reachable and filter_active_jobs(jobs):
        return ACTIVE_POLL_SECONDS
    return IDLE_POLL_SECONDS


def resolve_base_url() -> str:
    from rt.services.service_manager import api_port
    return f"http://127.0.0.1:{api_port()}"


_SESSION: Optional[str] = None
_SESSION_LOCK = threading.Lock()


def _api_session(renew: bool = False) -> str:
    """Una sola sessione per tutto il processo: crearne e cancellarne una a ogni controllo
    (ogni 3-15 s) riscriveva l'elenco delle sessioni e poteva perdere un login fatto nello stesso istante."""
    global _SESSION
    from rt.api import auth
    with _SESSION_LOCK:
        if renew or _SESSION is None:
            _SESSION = auth.create_session()
        return _SESSION


def fetch_active_jobs(base_url: str, timeout: float = 2.0) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    """Interroga GET /api/v1/jobs?state=active con una sessione riusata (rinnovata se scade)."""
    if not base_url:
        return None, False
    from rt.api import auth

    for renew in (False, True):
        try:
            request = urllib.request.Request(
                base_url.rstrip("/") + "/api/v1/jobs?state=active&limit=200",
                method="GET",
                headers={"Cookie": f"{auth.SESSION_COOKIE}={_api_session(renew)}"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, list):
                return payload, True
            return None, False
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and not renew:
                continue
            return None, False
        except Exception:
            return None, False
    return None, False


def read_start_at_login() -> bool:
    try:
        from rt.core.config import load_config
        return bool(load_config().ui.start_at_login)
    except Exception:
        return True


def toggle_start_at_login(base_url: Optional[str] = None) -> bool:
    """Inverte ui.start_at_login via API (o localmente se l'API non risponde) e aggiorna i plist."""
    next_val = not read_start_at_login()
    saved_via_api = False
    if base_url:
        try:
            from rt.api import auth
            session = auth.create_session()
            csrf = secrets.token_urlsafe(24)
            try:
                body = json.dumps({"avvia_all_accesso": next_val}).encode("utf-8")
                request = urllib.request.Request(
                    base_url.rstrip("/") + "/api/v1/settings/preferences",
                    data=body,
                    method="PUT",
                    headers={
                        "Content-Type": "application/json",
                        "Cookie": f"{auth.SESSION_COOKIE}={session}; {auth.CSRF_COOKIE}={csrf}",
                        auth.CSRF_HEADER: csrf,
                    },
                )
                with urllib.request.urlopen(request, timeout=3.0) as resp:
                    if 200 <= getattr(resp, "status", 200) < 300:
                        saved_via_api = True
            finally:
                auth.drop_session(session)
        except Exception:
            saved_via_api = False

    if not saved_via_api:
        from pathlib import Path
        from rt.core.config import _default_project_root
        from rt.services.settings_service import save_preferences
        save_preferences(Path(_default_project_root()), {"avvia_all_accesso": next_val})
    return next_val


def open_rt_app(base_url: Optional[str] = None) -> None:
    """Riapre RT su macOS con `open -b com.atturk.rt`."""
    if sys.platform != "darwin":
        return
    res = subprocess.run(["open", "-b", BUNDLE_ID], check=False, capture_output=True)
    if res.returncode != 0:
        from rt.core import bundle
        app = bundle.app_path()
        if app:
            subprocess.run(["open", app], check=False, capture_output=True)
        elif base_url:
            import webbrowser
            from rt.api import auth
            webbrowser.open(f"{base_url.rstrip('/')}/login?code={auth.create_login_code()}")


def close_open_window() -> bool:
    """Chiude l'eventuale finestra aperta leggendo il PID da _pid_path()."""
    from rt import window as rt_window
    pid = rt_window._read_pid()
    if pid > 0 and pid != os.getpid() and rt_window._pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False
    return False


def _confirm_quit_macos(message: str) -> bool:
    """Mostra il dialogo di conferma nativo macOS con lo stesso testo di active_jobs_quit_message."""
    import AppKit
    from rt.window import _load_macos_icon

    AppKit.NSApplication.sharedApplication()
    AppKit.NSRunningApplication.currentApplication().activateWithOptions_(
        AppKit.NSApplicationActivateIgnoringOtherApps
    )
    alert = AppKit.NSAlert.alloc().init()
    alert.addButtonWithTitle_("Annulla")
    alert.addButtonWithTitle_("Esci comunque")
    alert.setMessageText_("Esci da RT")
    alert.setInformativeText_(message)
    alert.setAlertStyle_(AppKit.NSWarningAlertStyle)
    img = _load_macos_icon()
    if img:
        alert.setIcon_(img)
    return alert.runModal() == AppKit.NSAlertSecondButtonReturn


def _terminate_app() -> None:
    try:
        import AppKit
        AppKit.NSApplication.sharedApplication().terminate_(None)
    except Exception:
        sys.exit(0)


def quit_rt(
    base_url: str,
    *,
    jobs: Optional[Sequence[Dict[str, Any]]] = None,
    confirm_fn: Optional[Callable[[str], bool]] = None,
    stop_fn: Optional[Callable[[str], None]] = None,
    close_window_fn: Optional[Callable[[], Any]] = None,
    terminate_fn: Optional[Callable[[], Any]] = None,
) -> bool:
    """Chiede conferma se ci sono job attivi, ferma i servizi, chiude la finestra e termina."""
    from rt.window import active_jobs_quit_message

    if jobs is None:
        fetched, _ = fetch_active_jobs(base_url)
        jobs_list = fetched
    else:
        jobs_list = list(jobs)

    warning = active_jobs_quit_message(jobs_list)
    if warning:
        asker = confirm_fn or _confirm_quit_macos
        if not asker(warning):
            return False

    # Evita che launchctl bootout su questo processo interrompa la chiusura della finestra.
    prev_handler = None
    in_main_thread = threading.current_thread() is threading.main_thread()
    if in_main_thread:
        try:
            prev_handler = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        except Exception:
            prev_handler = None

    try:
        if stop_fn is None:
            from rt.desktop import stop_background
            stop_fn = stop_background
        stop_fn(base_url)
        (close_window_fn or close_open_window)()
        (terminate_fn or _terminate_app)()
    except Exception:
        if in_main_thread and prev_handler is not None:
            try:
                signal.signal(signal.SIGTERM, prev_handler)
            except Exception:
                pass
        raise
    return True


def build_nsmenu(items: Sequence[MenuItem], target: Any) -> Any:
    """Converte un menu_model in un AppKit.NSMenu."""
    import AppKit
    from Foundation import NSAttributedString

    menu = AppKit.NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    action_selectors = {
        "open": "onOpenRT:",
        "toggle_login": "onToggleLogin:",
        "quit": "onQuitRT:",
    }

    for entry in items:
        if entry.kind == "separator":
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        sel = action_selectors.get(entry.action_id or "") if entry.enabled else None
        ns_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            entry.title,
            sel,
            "",
        )
        if sel and target is not None:
            ns_item.setTarget_(target)
        ns_item.setEnabled_(bool(entry.enabled))
        if entry.bold:
            font = AppKit.NSFont.boldSystemFontOfSize_(0)
            attrs = {AppKit.NSFontAttributeName: font}
            attr_title = NSAttributedString.alloc().initWithString_attributes_(entry.title, attrs)
            ns_item.setAttributedTitle_(attr_title)
        if entry.kind == "toggle":
            ns_item.setState_(
                AppKit.NSControlStateValueOn if entry.checked else AppKit.NSControlStateValueOff
            )
        menu.addItem_(ns_item)
    return menu


def run_menubar(base_url: Optional[str] = None) -> int:
    """Avvia l'icona di stato nella barra dei menu di macOS. No-op fuori da macOS."""
    if sys.platform != "darwin":
        return 0

    import AppKit
    from Foundation import NSMakeSize, NSObject
    from PyObjCTools import AppHelper

    resolved_url = base_url or resolve_base_url()
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    def _load_template(active: bool):
        path = template_icon_path(active=active)
        img = AppKit.NSImage.alloc().initWithContentsOfFile_(path)
        if img is not None:
            img.setTemplate_(True)
            img.setSize_(NSMakeSize(16.0, 16.0))
        return img

    idle_icon = _load_template(active=False)
    active_icon = _load_template(active=True) or idle_icon

    status_bar = AppKit.NSStatusBar.systemStatusBar()
    status_item = status_bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
    button = status_item.button()
    if button is not None and idle_icon is not None:
        button.setImage_(idle_icon)
        button.setToolTip_("RT")

    state_lock = threading.Lock()
    state: Dict[str, Any] = {
        "jobs": None,
        "api_reachable": False,
        "start_at_login": read_start_at_login(),
    }
    stop_event = threading.Event()
    wake_event = threading.Event()

    class _MenubarDelegate(NSObject):
        def menuNeedsUpdate_(self, menu):
            self._populate(menu)
            wake_event.set()

        def _populate(self, menu):
            menu.removeAllItems()
            with state_lock:
                jobs = state["jobs"]
                api_reachable = state["api_reachable"]
                start_at_login = state["start_at_login"]
            model = menu_model(jobs, start_at_login=start_at_login, api_reachable=api_reachable)
            built = build_nsmenu(model, self)
            for item in list(built.itemArray()):
                built.removeItem_(item)
                menu.addItem_(item)

        def onOpenRT_(self, _sender):
            open_rt_app(resolved_url)

        def onToggleLogin_(self, _sender):
            try:
                updated = toggle_start_at_login(resolved_url)
                with state_lock:
                    state["start_at_login"] = updated
            except Exception:
                pass
            wake_event.set()

        def onQuitRT_(self, _sender):
            with state_lock:
                cached_jobs = state["jobs"]
            stop_event.set()
            wake_event.set()
            if not quit_rt(resolved_url, jobs=cached_jobs):
                stop_event.clear()

    delegate = _MenubarDelegate.alloc().init()
    menu = AppKit.NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    menu.setDelegate_(delegate)
    status_item.setMenu_(menu)

    def _apply_icon(has_active: bool) -> None:
        btn = status_item.button()
        if btn is not None:
            icon = active_icon if has_active else idle_icon
            if icon is not None:
                btn.setImage_(icon)

    def _poll_loop() -> None:
        while not stop_event.is_set():
            jobs, reachable = fetch_active_jobs(resolved_url)
            sal = read_start_at_login()
            with state_lock:
                state["jobs"] = jobs
                state["api_reachable"] = reachable
                state["start_at_login"] = sal
            has_active = bool(reachable and filter_active_jobs(jobs))
            AppHelper.callAfter(lambda active=has_active: _apply_icon(active))
            interval = poll_interval(jobs, api_reachable=reachable)
            wake_event.wait(interval)
            wake_event.clear()

    poller = threading.Thread(target=_poll_loop, name="rt-menubar-poll", daemon=True)
    poller.start()
    try:
        app.run()
    finally:
        stop_event.set()
        wake_event.set()
    return 0


def cmd_menubar(_args: Optional[argparse.Namespace] = None) -> None:
    code = run_menubar()
    if code:
        sys.exit(code)
