"""
rt.core.app_update
Aggiornamento dell'app installata (RT.app, setup per Windows) dalle release STABILI di
GitHub: si scarica il nuovo installer della release più recente, si verifica con SHA256SUMS
e lo si installa sopra l'app. Le beta non arrivano mai da qui: chi vuole provarle scarica
l'installer a mano dalla pagina delle release.

- Windows: il setup parte in modalità silenziosa, chiude RT, sostituisce i file e lo riavvia.
- macOS: il .dmg si monta, la nuova RT.app si copia accanto a quella in uso e un processo
  separato le scambia e riapre RT, che riavvia i servizi con il codice nuovo.

Lo stato dell'operazione (scaricamento, installazione, errore) vive nel processo che la
esegue: la pagina Info lo legge con GET /api/v1/system/update.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, Optional

from rt.core import bundle, paths
from rt.core.version import (BETA, OFFLINE_ENV, RELEASES_API, STABLE, channel_file, format_version,
                             get_current_version, get_update_channel, is_prerelease, parse_version,
                             set_update_channel)

RELEASES_PAGE = "https://github.com/atturk/rt/releases"
ASSET_NAMES = {
    bundle.MACOS: "RT-{version}-macos-arm64.dmg",
    bundle.WINDOWS: "RT-{version}-windows-x64-setup.exe",
}
CHECK_TTL_SECONDS = 6 * 3600


class AppUpdateError(RuntimeError):
    pass


@dataclass
class UpdateCheck:
    supported: bool
    current: str
    latest: Optional[str] = None
    available: bool = False
    asset_url: Optional[str] = None
    asset_name: Optional[str] = None
    asset_size: Optional[int] = None
    sums_url: Optional[str] = None
    notes_url: Optional[str] = None
    error: Optional[str] = None
    checked_at: float = field(default_factory=time.time)
    channel: str = "stable"
    prerelease: bool = False


def effective_channel(current: str) -> str:
    """Il valore di get_update_channel() se il file del canale esiste; altrimenti beta
    se is_prerelease(current), altrimenti stable."""
    if os.path.exists(channel_file()):
        return get_update_channel()
    return "beta" if is_prerelease(current) else "stable"


def asset_name(kind: str, version: str) -> str:
    return ASSET_NAMES[kind].format(version=version)


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "RT-Updater",
                                               "Accept": "application/vnd.github.v3+json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def evaluate(release: Dict, kind: Optional[str], current: str, allow_prerelease: bool = False) -> UpdateCheck:
    """Confronta la release con la versione installata."""
    check = UpdateCheck(supported=kind is not None, current=current)
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if not tag or release.get("draft"):
        return check
    is_pre = bool(release.get("prerelease")) or is_prerelease(format_version(tag))
    if is_pre and not allow_prerelease:
        return check
    latest = format_version(tag)
    check.latest = latest
    check.prerelease = is_pre
    check.notes_url = release.get("html_url") or f"{RELEASES_PAGE}/tag/{tag}"
    if kind is None:
        return check
    assets = {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)}
    wanted = assets.get(asset_name(kind, latest))
    sums = assets.get("SHA256SUMS")
    newer = (parse_version(latest) or ()) > (parse_version(current) or ())
    if newer and wanted and sums:
        check.available = True
        check.asset_url = wanted.get("browser_download_url")
        check.asset_name = wanted.get("name")
        check.asset_size = wanted.get("size")
        check.sums_url = sums.get("browser_download_url")
    return check


def check(timeout: float = 8.0, project_root: Optional[str] = None) -> UpdateCheck:
    root = project_root or paths.project_root()
    current = get_current_version(root)
    kind = bundle.kind(root)
    channel = effective_channel(current)
    if os.environ.get(OFFLINE_ENV) == "1":
        return UpdateCheck(supported=kind is not None, current=current, channel=channel,
                           error="Controllo degli aggiornamenti disattivato (RT_UPDATE_OFFLINE=1).")
    try:
        if channel == "beta":
            releases = _get_json(f"{RELEASES_API}?per_page=30", timeout)
            best_rel = None
            best_ver = None
            for rel in releases if isinstance(releases, list) else []:
                if not isinstance(rel, dict) or rel.get("draft"):
                    continue
                tag = rel.get("tag_name")
                if not tag:
                    continue
                v = parse_version(format_version(tag))
                if not v:
                    continue
                if kind is not None:
                    assets = {a.get("name"): a for a in rel.get("assets") or [] if isinstance(a, dict)}
                    if not (assets.get(asset_name(kind, format_version(tag))) and assets.get("SHA256SUMS")):
                        continue
                if best_ver is None or v > best_ver:
                    best_ver = v
                    best_rel = rel
            if best_rel is None:
                info = UpdateCheck(supported=kind is not None, current=current, channel=channel)
            else:
                info = evaluate(best_rel, kind, current, allow_prerelease=True)
                info.channel = channel
        else:
            release = _get_json(f"{RELEASES_API}/latest", timeout)
            info = evaluate(release, kind, current, allow_prerelease=False)
            info.channel = channel
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateCheck(supported=kind is not None, current=current, channel=channel)
        return UpdateCheck(supported=kind is not None, current=current, channel=channel,
                           error=f"GitHub non risponde (HTTP {exc.code}).")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return UpdateCheck(supported=kind is not None, current=current, channel=channel,
                           error=f"Impossibile controllare gli aggiornamenti: {getattr(exc, 'reason', exc)}.")
    cleanup(info.asset_name if info.available else None)
    return info


# ------------------------------------------------------------------ download e verifica

def _updates_dir() -> str:
    target = os.path.join(paths.data_dir(), "updates")
    os.makedirs(target, exist_ok=True)
    return target


def expected_sha256(sums_text: str, name: str) -> Optional[str]:
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    return None


def download(info: UpdateCheck, on_progress: Callable[[int, Optional[int]], None] = lambda done, total: None,
             opener: Callable = urllib.request.urlopen) -> str:
    """Scarica l'installer e lo verifica con SHA256SUMS; restituisce il percorso del file."""
    if not (info.asset_url and info.asset_name and info.sums_url):
        raise AppUpdateError("Nessun aggiornamento da scaricare.")
    headers = {"User-Agent": "RT-Updater"}
    try:
        with opener(urllib.request.Request(info.sums_url, headers=headers), timeout=30) as resp:
            sums = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise AppUpdateError(f"Impossibile scaricare SHA256SUMS: {exc}") from None
    expected = expected_sha256(sums, info.asset_name)
    if not expected:
        raise AppUpdateError(f"SHA256SUMS non elenca {info.asset_name}.")
    target = os.path.join(_updates_dir(), info.asset_name)
    partial = target + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        with opener(urllib.request.Request(info.asset_url, headers=headers), timeout=60) as resp, \
                open(partial, "wb") as out:
            total = info.asset_size or int(resp.headers.get("Content-Length") or 0) or None
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                on_progress(done, total)
    except (urllib.error.URLError, OSError) as exc:
        _remove(partial)
        raise AppUpdateError(f"Download interrotto: {exc}") from None
    if digest.hexdigest() != expected:
        _remove(partial)
        raise AppUpdateError("Il file scaricato non corrisponde a SHA256SUMS: aggiornamento annullato.")
    os.replace(partial, target)
    ready_data = {
        "version": info.latest,
        "asset_name": info.asset_name,
        "sha256": digest.hexdigest(),
        "size": os.path.getsize(target),
    }
    with open(os.path.join(_updates_dir(), "ready.json"), "w", encoding="utf-8") as f:
        json.dump(ready_data, f)
    return target


def ready_file(info: Optional[UpdateCheck]) -> Optional[str]:
    """Il percorso dell'installer se ready.json indica la stessa version e lo stesso asset_name di info,
    e il file esiste con la stessa dimensione. Altrimenti None."""
    if not info or not info.latest or not info.asset_name:
        return None
    ready_json_path = os.path.join(_updates_dir(), "ready.json")
    if not os.path.isfile(ready_json_path):
        return None
    try:
        with open(ready_json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != info.latest or data.get("asset_name") != info.asset_name:
        return None
    installer_path = os.path.join(_updates_dir(), info.asset_name)
    if not os.path.isfile(installer_path):
        return None
    try:
        actual_size = os.path.getsize(installer_path)
    except OSError:
        return None
    expected_size = data.get("size")
    if expected_size is None or actual_size != expected_size:
        return None
    return installer_path


def cleanup(keep: Optional[str] = None) -> None:
    """Toglie da updates/ gli installer, i .part e ready.json che non riguardano keep."""
    updates = _updates_dir()
    ready_json_path = os.path.join(updates, "ready.json")
    if os.path.isfile(ready_json_path):
        if not keep:
            _remove(ready_json_path)
        else:
            try:
                with open(ready_json_path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict) or data.get("asset_name") != keep:
                    _remove(ready_json_path)
            except (OSError, ValueError):
                _remove(ready_json_path)
    try:
        entries = os.listdir(updates)
    except OSError:
        return
    for name in entries:
        if name == "ready.json" or name.endswith(".log"):
            continue
        is_installer = name.endswith(".dmg") or name.endswith(".exe") or name.endswith(".part")
        if not is_installer:
            continue
        if keep and (name == keep or name == f"{keep}.part"):
            continue
        _remove(os.path.join(updates, name))


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ------------------------------------------------------------------ installazione

def _detached() -> Dict:
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: il setup sopravvive alla chiusura di RT
        return {"creationflags": 0x00000008 | 0x00000200, "close_fds": True}
    return {"start_new_session": True, "close_fds": True}


def install_windows(installer: str) -> None:
    """Il setup chiude RT (anche worker e finestre), sostituisce i file e lo riapre."""
    subprocess.Popen([installer, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                      f"/LOG={os.path.join(_updates_dir(), 'setup.log')}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **_detached())


def copy_app_from_dmg(dmg: str, target: str) -> None:
    """Copia RT.app dal .dmg in target, senza quarantena: niente avviso di Gatekeeper per
    un'app non firmata che RT ha scaricato e verificato da sé."""
    if os.path.lexists(target):
        raise AppUpdateError(f"{target} esiste già: non la sostituisco.")
    mount = tempfile.mkdtemp(prefix="rt-update-")
    try:
        _run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mount, dmg])
        try:
            source = os.path.join(mount, "RT.app")
            if not os.path.isdir(source):
                raise AppUpdateError("Il .dmg non contiene RT.app.")
            _run(["ditto", source, target])
        finally:
            subprocess.run(["hdiutil", "detach", mount, "-force"], capture_output=True, check=False)
    finally:
        shutil.rmtree(mount, ignore_errors=True)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", target], capture_output=True, check=False)


def install_macos(dmg: str, project_root: Optional[str] = None) -> None:
    """Copia la nuova RT.app accanto a quella in uso; un processo separato le scambia e riapre
    RT (che riavvia i servizi con il codice nuovo)."""
    app = bundle.app_path(project_root)
    if not app:
        raise AppUpdateError("Non trovo RT.app: scarica l'aggiornamento dalla pagina delle release.")
    parent = os.path.dirname(app)
    if not os.access(parent, os.W_OK):
        raise AppUpdateError(f"Non posso scrivere in {parent}: scarica l'aggiornamento dalla pagina delle release.")
    staging = app + ".update"
    shutil.rmtree(staging, ignore_errors=True)
    copy_app_from_dmg(dmg, staging)
    old = app + ".old"
    script = ('sleep 1; '
              'if [ -f "$WINDOW_PID" ]; then '
              'PID=$(cat "$WINDOW_PID"); '
              'case "$PID" in ""|*[!0-9]*) ;; *) kill "$PID" 2>/dev/null || true ;; esac; '
              'rm -f "$WINDOW_PID"; fi; '
              'rm -rf "$OLD"; mv "$APP" "$OLD" && mv "$NEW" "$APP" && rm -rf "$OLD" && '
              'open "$APP" --args --after-update')
    subprocess.Popen(["/bin/sh", "-c", script],
                     env={**os.environ, "APP": app, "NEW": staging, "OLD": old,
                          "WINDOW_PID": os.path.join(paths.data_dir(), "run", "window.pid")},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **_detached())


def _run(command) -> None:
    try:
        res = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AppUpdateError(f"{command[0]}: {exc}") from None
    if res.returncode != 0:
        raise AppUpdateError(f"{command[0]}: {(res.stderr or res.stdout).strip()}")


def install(installer: str, project_root: Optional[str] = None) -> None:
    kind = bundle.kind(project_root)
    if kind == bundle.WINDOWS:
        install_windows(installer)
    elif kind == bundle.MACOS:
        install_macos(installer, project_root)
    else:
        raise AppUpdateError("Questa installazione si aggiorna con 'rt -u'.")


def start_install(info: UpdateCheck) -> None:
    """Verifica di nuovo lo SHA256 del file su disco contro ready.json, poi phase = 'installing' e install(path)."""
    path = ready_file(info)
    if not path:
        raise AppUpdateError("File di aggiornamento non pronto per l'installazione.")
    ready_json_path = os.path.join(_updates_dir(), "ready.json")
    try:
        with open(ready_json_path, encoding="utf-8") as f:
            data = json.load(f)
        expected_sha = data.get("sha256")
    except (OSError, ValueError):
        cleanup(None)
        raise AppUpdateError("ready.json non valido.") from None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
    except OSError as exc:
        cleanup(None)
        raise AppUpdateError(f"Impossibile leggere l'installer: {exc}") from None
    if not expected_sha or digest.hexdigest().lower() != expected_sha.lower():
        cleanup(None)
        with STATE.lock:
            STATE.phase = "error"
            STATE.error = "Hash dell'installer non corrispondente: file eliminato."
        raise AppUpdateError("Hash dell'installer non corrispondente.")

    with STATE.lock:
        STATE.phase = "installing"
        STATE.target = info.latest
    install(path)


# ------------------------------------------------------------------ stato per l'API

class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.phase = "idle"  # idle | downloading | ready | installing | error
        self.downloaded = 0
        self.total: Optional[int] = None
        self.error: Optional[str] = None
        self.target: Optional[str] = None
        self.last_check: Optional[UpdateCheck] = None

    def snapshot(self) -> Dict:
        with self.lock:
            return {"phase": self.phase, "downloaded": self.downloaded, "total": self.total,
                    "error": self.error, "target": self.target}


STATE = _State()


def cached_check(refresh: bool = False) -> UpdateCheck:
    last = STATE.last_check
    if not refresh and last is not None and last.error is None and time.time() - last.checked_at < CHECK_TTL_SECONDS:
        return last
    result = check()
    STATE.last_check = result
    return result


def start_download(info: UpdateCheck) -> bool:
    """Scarica in un thread; False se un download o aggiornamento è già in corso."""
    with STATE.lock:
        if STATE.phase in ("downloading", "installing"):
            return False
        STATE.phase, STATE.downloaded, STATE.total = "downloading", 0, info.asset_size
        STATE.error, STATE.target = None, info.latest

    def progress(done: int, total: Optional[int]) -> None:
        with STATE.lock:
            STATE.downloaded, STATE.total = done, total

    def work() -> None:
        try:
            download(info, progress)
            with STATE.lock:
                STATE.phase = "ready"
        except AppUpdateError as exc:
            with STATE.lock:
                STATE.phase, STATE.error = "error", str(exc)
        except Exception as exc:  # noqa: BLE001
            with STATE.lock:
                STATE.phase, STATE.error = "error", f"Download non riuscito: {exc}"

    threading.Thread(target=work, name="rt-app-download", daemon=True).start()
    return True


start = start_download


def as_dict(info: UpdateCheck) -> Dict:
    data = asdict(info)
    data.pop("sums_url", None)
    data["ready"] = bool(ready_file(info))
    return data


# ------------------------------------------------------------------ 'rt -u' dall'app

def run_cli(project_root: str, wants_beta: bool = False) -> int:
    if wants_beta:
        try:
            set_update_channel(BETA)
        except OSError as exc:
            print(f"❌ Impossibile impostare il canale beta: {exc}", file=sys.stderr)
            return 1
    info = check(project_root=project_root)
    if info.error:
        print(f"❌ {info.error}", file=sys.stderr)
        return 1
    if not info.available:
        if info.latest and is_prerelease(info.current):
            print(f"Hai la beta {info.current}: l'app passerà alla prossima versione stabile appena esce.")
        else:
            print(f"Sei già aggiornato all'ultima versione ({info.current}).")
        return 0
    print(f"Scarico RT {info.latest}...")
    last = [-1]

    def progress(done: int, total: Optional[int]) -> None:
        if total:
            percent = done * 100 // total
            if percent // 10 != last[0]:
                last[0] = percent // 10
                print(f"  {percent}%", flush=True)
    try:
        path = download(info, progress)
        install(path, project_root)
    except AppUpdateError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✅ Installo RT {info.latest}: RT si chiude e si riapre da solo.")
    return 0
