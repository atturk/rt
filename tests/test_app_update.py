"""
tests/test_app_update.py
L'app installata (RT.app, setup per Windows) si aggiorna solo alle release stabili, con il
nuovo installer verificato da SHA256SUMS; install.sh, git e Docker restano su 'rt -u'.
"""
import hashlib
import io
import os

import pytest

from rt.core import app_update, bundle

DMG = "RT-4.3.0-macos-arm64.dmg"
EXE = "RT-4.3.0-windows-x64-setup.exe"


@pytest.fixture(autouse=True)
def _reset_update_state():
    yield
    app_update.STATE.phase = "idle"
    app_update.STATE.error = None
    app_update.STATE.downloaded = 0
    app_update.STATE.total = None
    app_update.STATE.target = None
    app_update.STATE.last_check = None
    app_update.STATE.checked_at = 0.0


def release(tag="v4.3.0", prerelease=False, names=(DMG, EXE, "SHA256SUMS")):
    return {"tag_name": tag, "prerelease": prerelease, "draft": False,
            "html_url": f"https://github.com/atturk/rt/releases/tag/{tag}",
            "assets": [{"name": n, "size": 10, "browser_download_url": f"https://example.invalid/{n}"} for n in names]}


def test_newer_stable_with_installer_is_available():
    info = app_update.evaluate(release(), bundle.WINDOWS, "4.2.5")
    assert info.available and info.latest == "4.3.0" and info.asset_name == EXE
    assert app_update.evaluate(release(), bundle.MACOS, "4.2.5").asset_name == DMG


@pytest.mark.parametrize("rel, kind, current", [
    (release(), bundle.WINDOWS, "4.3.0"),                        # già aggiornato
    (release(), bundle.WINDOWS, "4.3.1b1"),                      # beta installata a mano, più recente
    (release(prerelease=True, tag="v4.4.0b1"), bundle.WINDOWS, "4.2.5"),  # le beta non arrivano mai
    (release(names=(DMG, "SHA256SUMS")), bundle.WINDOWS, "4.2.5"),         # installer non ancora allegato
    (release(names=(EXE,)), bundle.WINDOWS, "4.2.5"),                      # manca SHA256SUMS
    (release(), None, "4.2.5"),                                  # install.sh o git: 'rt -u'
])
def test_not_available(rel, kind, current):
    info = app_update.evaluate(rel, kind, current)
    assert not info.available
    assert info.supported is (kind is not None)


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener(files):
    def opener(request, timeout=None):
        return _Resp(files[request.full_url.rsplit("/", 1)[-1]])
    return opener


def _info():
    return app_update.evaluate(release(), bundle.WINDOWS, "4.2.5")


def test_download_verifies_sha256(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    payload = b"setup" * 1000
    sums = f"{hashlib.sha256(payload).hexdigest()}  {EXE}\n".encode()
    seen = []
    path = app_update.download(_info(), lambda done, total: seen.append(done),
                               opener=_opener({EXE: payload, "SHA256SUMS": sums}))
    assert open(path, "rb").read() == payload and seen[-1] == len(payload)

    bad = f"{'0' * 64}  {EXE}\n".encode()
    os.remove(path)
    with pytest.raises(app_update.AppUpdateError, match="SHA256SUMS"):
        app_update.download(_info(), opener=_opener({EXE: payload, "SHA256SUMS": bad}))
    assert not os.path.exists(path) and not os.path.exists(path + ".part")


class _DroppingResp(_Resp):
    """Risposta che smette di ricevere dati a metà, come quando cade o cambia la rete."""

    def __init__(self, payload, error):
        super().__init__(payload)
        self.error = error
        self.sent = False

    def read(self, size=-1):
        if self.sent:
            if self.error:
                raise self.error
            return b""
        self.sent = True
        return super().read(len(self.getvalue()) // 2)


@pytest.mark.parametrize("error", [TimeoutError("timed out"), ConnectionResetError(54, "reset"), None])
def test_download_dropped_connection_says_so(tmp_path, monkeypatch, error):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    payload = b"x" * (3 << 20)
    sums = f"{hashlib.sha256(payload).hexdigest()}  {EXE}\n".encode()
    info = _info()
    info.asset_size = len(payload)
    timeouts = []

    def opener(request, timeout=None):
        timeouts.append(timeout)
        name = request.full_url.rsplit("/", 1)[-1]
        return _Resp(sums) if name == "SHA256SUMS" else _DroppingResp(payload, error)
    with pytest.raises(app_update.AppUpdateError) as exc:
        app_update.download(info, opener=opener)
    assert str(exc.value).startswith("La connessione si è interrotta durante il download dell'aggiornamento dopo 1,5 MB su 3,0 MB")
    assert "timed out" not in str(exc.value)
    assert timeouts == [app_update.READ_TIMEOUT] * 2
    assert not list((tmp_path / "updates").glob("*.part"))


def test_download_without_network_says_so(tmp_path, monkeypatch):
    import urllib.error
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))

    def opener(request, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))
    with pytest.raises(app_update.AppUpdateError, match="Non riesco a raggiungere il server degli aggiornamenti"):
        app_update.download(_info(), opener=opener)


def test_bundle_marker_and_app_path(tmp_path):
    root = tmp_path / "RT.app" / "Contents" / "Resources" / "app"
    root.mkdir(parents=True)
    assert bundle.kind(str(root)) is None
    (root / "BUNDLE").write_text("macos\n")
    assert bundle.kind(str(root)) == bundle.MACOS
    assert bundle.app_path(str(root)) == str(tmp_path / "RT.app")
    assert bundle.app_path(str(tmp_path)) is None


def test_rt_u_in_the_app_uses_the_installer(tmp_path, monkeypatch, capsys):
    from rt.core import version
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "BUNDLE").write_text("windows")
    (tmp_path / "VERSION").write_text("4.2.5")
    monkeypatch.setattr(app_update, "_get_json", lambda url, timeout: release(tag="v4.2.5"))
    assert version.run_update(str(tmp_path)) == 0
    assert "già aggiornato" in capsys.readouterr().out
    assert version.run_update(str(tmp_path), version.BETA) == 0
    assert version.get_update_channel() == "beta"


def test_effective_channel(tmp_path, monkeypatch):
    from rt.core import version
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    # Senza file: "stable" per versioni stabili, "beta" per prerelease
    assert not os.path.exists(version.channel_file())
    assert app_update.effective_channel("4.2.5") == "stable"
    assert app_update.effective_channel("4.3.0b1") == "beta"

    # Con file impostato: segue il file
    version.set_update_channel("beta")
    assert app_update.effective_channel("4.2.5") == "beta"
    version.set_update_channel("stable")
    assert app_update.effective_channel("4.3.0b1") == "stable"


def test_beta_channel_picks_highest_release_with_installer_and_sums(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    (tmp_path / "BUNDLE").write_text("windows")
    (tmp_path / "VERSION").write_text("4.2.5")
    from rt.core import version
    version.set_update_channel("beta")

    # Lista di release restituita da GitHub
    # 4.4.0b2: manca SHA256SUMS -> da scartare
    # 4.4.0b1: valida con EXE e SHA256SUMS -> deve scegliere questa
    # 4.3.0: stabile precedente
    rel_4_4_b2 = release(tag="v4.4.0b2", prerelease=True, names=(EXE,))
    rel_4_4_b1 = release(tag="v4.4.0b1", prerelease=True, names=(
        "RT-4.4.0b1-windows-x64-setup.exe", "SHA256SUMS"))
    rel_4_3_0 = release(tag="v4.3.0", prerelease=False, names=(EXE, "SHA256SUMS"))

    monkeypatch.setattr(app_update, "_get_json", lambda url, timeout: [rel_4_4_b2, rel_4_4_b1, rel_4_3_0])
    info = app_update.check(project_root=str(tmp_path))
    assert info.available
    assert info.latest == "4.4.0b1"
    assert info.prerelease is True
    assert info.asset_name == "RT-4.4.0b1-windows-x64-setup.exe"


def test_download_ready_file_and_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    payload = b"setup-payload-content" * 50
    sums = f"{hashlib.sha256(payload).hexdigest()}  {EXE}\n".encode()

    info = _info()
    path = app_update.download(info, opener=_opener({EXE: payload, "SHA256SUMS": sums}))
    assert os.path.exists(path)

    # ready_file() lo ritrova
    found = app_update.ready_file(info)
    assert found == path

    # Con file troncato ready_file() dà None
    with open(path, "wb") as f:
        f.write(payload[:20])
    assert app_update.ready_file(info) is None


def test_start_install_rejects_altered_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    payload = b"valid-setup" * 100
    sums = f"{hashlib.sha256(payload).hexdigest()}  {EXE}\n".encode()

    info = _info()
    path = app_update.download(info, opener=_opener({EXE: payload, "SHA256SUMS": sums}))
    assert app_update.ready_file(info) == path

    # Modifica il contenuto mantenendo la stessa dimensione
    with open(path, "wb") as f:
        f.write(b"x" * len(payload))
    assert os.path.getsize(path) == len(payload)

    with pytest.raises(app_update.AppUpdateError, match="Hash dell'installer"):
        app_update.start_install(info)
    # L'installer è stato eliminato da cleanup
    assert not os.path.exists(path)


def test_cleanup_keeps_only_specified_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    updates = tmp_path / "updates"
    updates.mkdir()

    keep_exe = updates / EXE
    keep_exe.write_text("keep-me")
    other_dmg = updates / DMG
    other_dmg.write_text("delete-me")
    part_file = updates / "other.exe.part"
    part_file.write_text("partial")
    ready_json = updates / "ready.json"
    ready_json.write_text(f'{{"version": "4.3.0", "asset_name": "{EXE}", "sha256": "abc", "size": 7}}')

    app_update.cleanup(EXE)
    assert keep_exe.is_file()
    assert ready_json.is_file()
    assert not other_dmg.exists()
    assert not part_file.exists()

    # cleanup(None) cancella tutto
    app_update.cleanup(None)
    assert not keep_exe.exists()
    assert not ready_json.exists()


def test_api_download_does_not_install_and_install_requires_ready(api_client, monkeypatch, tmp_path):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    info = app_update.UpdateCheck(
        supported=True,
        current="4.2.5",
        latest="4.3.0",
        available=True,
        asset_name=EXE,
        asset_size=100,
        notes_url="https://example.com",
    )
    monkeypatch.setattr(app_update, "cached_check", lambda refresh=False: info)
    started = []
    monkeypatch.setattr(app_update, "start_download", lambda inf: started.append(inf) or True)

    # POST /system/update avvia solo il download
    res = api_client.post("/api/v1/system/update")
    assert res.status_code == 202
    assert len(started) == 1

    # POST /system/update/install dà 409 not_ready se il file non c'è
    res_inst = api_client.post("/api/v1/system/update/install")
    assert res_inst.status_code == 409
    assert res_inst.json()["error"]["code"] == "not_ready"


def test_api_reports_update_state(api_client):
    data = api_client.get("/api/v1/system/update").json()
    assert data["supported"] is False and data["available"] is False
    assert data["progress"]["phase"] == "idle"
    assert data["releases_url"].endswith("/releases")
    res = api_client.post("/api/v1/system/update")
    assert res.status_code == 409 and res.json()["error"]["code"] == "update_unsupported"


def test_desktop_setup_runs_once_per_version(tmp_path, monkeypatch):
    from rt import desktop
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    assert desktop.needs_setup("4.2.5")
    (tmp_path / "rt-data.json").write_text("{}")
    (tmp_path / desktop.STAMP_FILE).write_text("4.2.5\n")
    assert not desktop.needs_setup("4.2.5")
    assert desktop.needs_setup("4.3.0")


def test_macos_update_closes_window_before_swapping_apps(tmp_path, monkeypatch):
    from unittest.mock import Mock
    app = tmp_path / "RT.app"
    app.mkdir()
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path / "dati"))
    monkeypatch.setattr(bundle, "app_path", lambda root=None: str(app))
    monkeypatch.setattr(app_update, "_run", lambda command: None)
    monkeypatch.setattr(app_update.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(app_update.subprocess, "run", Mock())
    popen = Mock()
    monkeypatch.setattr(app_update.subprocess, "Popen", popen)
    app_update.install_macos(str(tmp_path / "nuova.dmg"))
    command = popen.call_args.args[0]
    script = command[-1]
    assert 'kill "$PID"' in script
    assert script.index('kill "$PID"') < script.index('mv "$APP"')
    assert 'open "$APP" --args --after-update' in script
    assert popen.call_args.kwargs["env"]["WINDOW_PID"] == str(tmp_path / "dati" / "run" / "window.pid")


def test_copy_dmg_preserves_existing_target(tmp_path):
    target = tmp_path / "RT.app"
    target.mkdir()
    personal = target / "personale.txt"
    personal.write_text("da conservare")
    with pytest.raises(app_update.AppUpdateError, match="esiste già"):
        app_update.copy_app_from_dmg(str(tmp_path / "RT.dmg"), str(target))
    assert personal.read_text() == "da conservare"


def test_refresh_reaches_github_at_most_once_a_minute(monkeypatch):
    calls = []
    found = app_update.UpdateCheck(supported=True, current="4.3.0", latest="4.3.1", available=True)
    monkeypatch.setattr(app_update, "effective_channel", lambda current: "stable")
    monkeypatch.setattr(app_update, "check", lambda: calls.append(1) or found)
    for _ in range(20):
        assert app_update.cached_check(refresh=True) is found
    assert len(calls) == 1
    app_update.STATE.checked_at -= app_update.REFRESH_MIN_SECONDS
    app_update.cached_check(refresh=True)
    assert len(calls) == 2


def test_rate_limited_github_keeps_the_last_good_check(monkeypatch):
    found = app_update.UpdateCheck(supported=True, current="4.3.0", latest="4.3.1", available=True)
    limited = app_update.UpdateCheck(supported=True, current="4.3.0", error="GitHub non risponde (HTTP 429).")
    results = iter([found, limited])
    monkeypatch.setattr(app_update, "effective_channel", lambda current: "stable")
    monkeypatch.setattr(app_update, "check", lambda: next(results))
    assert app_update.cached_check(refresh=True) is found
    app_update.STATE.checked_at -= app_update.REFRESH_MIN_SECONDS
    assert app_update.cached_check(refresh=True) is found
    # il download usa ancora il controllo riuscito
    assert app_update.cached_check().available


ATOM = """<feed><entry><link rel="alternate" type="text/html" href="https://github.com/atturk/rt/releases/tag/v4.4.0b1"/></entry>
<entry><link rel="alternate" type="text/html" href="https://github.com/atturk/rt/releases/tag/v4.3.3.1"/></entry>
<entry><link rel="alternate" type="text/html" href="https://github.com/atturk/rt/releases/tag/v4.3.3"/></entry></feed>"""


def _feed(monkeypatch, sums_for=None):
    def get_text(url, timeout):
        if url.endswith(".atom"):
            return ATOM
        if sums_for and url.endswith(f"/{sums_for}/SHA256SUMS"):
            return f"{'a' * 64}  RT-{sums_for[1:]}-macos-arm64.dmg\n"
        raise app_update.urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(app_update, "_get_text", get_text)


def test_api_limit_falls_back_to_the_release_feed(monkeypatch):
    def limited(url, timeout):
        raise app_update.urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, None)
    monkeypatch.setattr(app_update, "_get_json", limited)
    monkeypatch.setattr(app_update, "get_current_version", lambda root: "4.3.3")
    monkeypatch.setattr(app_update.bundle, "kind", lambda root=None: bundle.MACOS)
    monkeypatch.setattr(app_update, "effective_channel", lambda current: "stable")
    monkeypatch.setattr(app_update, "cleanup", lambda keep=None: None)
    _feed(monkeypatch, sums_for="v4.3.3.1")
    info = app_update.check(project_root="/x")
    assert info.error is None and info.available and info.latest == "4.3.3.1"
    assert info.asset_url == "https://github.com/atturk/rt/releases/download/v4.3.3.1/RT-4.3.3.1-macos-arm64.dmg"
    assert info.sums_url.endswith("/download/v4.3.3.1/SHA256SUMS")


def test_feed_beta_channel_and_missing_installer(monkeypatch):
    _feed(monkeypatch)
    info = app_update.check_from_feed(bundle.MACOS, "4.3.3", "beta", 5)
    # La beta più recente non ha ancora l'installer allegato: nessun download offerto.
    assert info.latest == "4.4.0b1" and info.prerelease and not info.available
    assert app_update.check_from_feed(bundle.MACOS, "4.3.3.1", "stable", 5).available is False


def test_install_runs_in_background_and_reports_errors(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    payload = b"valid-setup" * 100
    sums = f"{hashlib.sha256(payload).hexdigest()}  {EXE}\n".encode()
    info = _info()
    app_update.download(info, opener=_opener({EXE: payload, "SHA256SUMS": sums}))
    gate, done = threading.Event(), threading.Event()

    def slow_install(path, project_root=None):
        gate.wait(5)
        done.set()
        raise app_update.AppUpdateError("Il .dmg non contiene RT.app.")
    monkeypatch.setattr(app_update, "install", slow_install)
    app_update.start_install(info)
    # La richiesta è già tornata mentre l'installazione è ancora in corso.
    assert app_update.STATE.snapshot()["phase"] == "installing"
    with pytest.raises(app_update.AppUpdateError, match="già in corso"):
        app_update.start_install(info)
    gate.set()
    done.wait(5)
    for _ in range(50):
        if app_update.STATE.snapshot()["phase"] == "error":
            break
        threading.Event().wait(0.05)
    assert app_update.STATE.snapshot()["error"] == "Il .dmg non contiene RT.app."
    log = (tmp_path / "updates" / "install.log").read_text()
    assert "installo RT 4.3.0" in log and "errore: Il .dmg non contiene RT.app." in log
