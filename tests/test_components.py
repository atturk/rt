"""Test per il gestore dei componenti scaricabili (/api/v1/components, desktop browser, attesa job)."""
import io
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from rt import desktop
from rt.core import components, onnx_stt
from rt.core.filelock import acquire_file_lock, release_file_lock
from rt.services.context import CancelToken, RunCancelled, RunContext
from rt.services.pipeline_service import emit_stt_progress


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RT_STT_MODELS_DIR", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "browsers"))
    components._active.clear()
    onnx_stt.clear_loaded()
    yield tmp_path
    components._active.clear()
    onnx_stt.clear_loaded()


def test_components_api_initial_and_404(api_client, isolated_data, monkeypatch):
    from rt.llm import enrichment_media

    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    monkeypatch.setattr(components, "browser_available", lambda: True)
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    monkeypatch.setattr("rt.core.config.effective_engine", lambda cfg=None: "macparakeet")
    monkeypatch.setattr(enrichment_media, "detect_system_browser", lambda: None)

    res = api_client.get("/api/v1/components")
    assert res.status_code == 200
    items = {c["id"]: c for c in res.json()}
    assert set(items) == {"macparakeet", "transcription", "browser"}
    assert items["macparakeet"]["state"] == "not_downloaded"
    assert items["macparakeet"]["required"] is True
    assert items["transcription"]["state"] == "not_downloaded"
    assert items["transcription"]["required"] is False
    assert items["transcription"]["approx_bytes"] == 900 * 1024 * 1024
    assert items["transcription"]["description"] == "non necessario: alternativa al motore scelto, puoi eliminarlo"
    assert items["transcription"]["detail"] == "Parakeet TDT 0.6B v3 di NVIDIA, CC-BY-4.0"
    assert items["browser"]["state"] == "not_downloaded"
    assert items["browser"]["required"] is True
    assert items["browser"]["system_browser"] is None
    assert items["browser"]["in_use"] is None
    assert items["browser"]["name"] == "Browser per PDF e catture"
    assert items["browser"]["detail"] == "Chrome Headless Shell (versione minima)"
    assert items["browser"]["description"] == "Serve per esportare in PDF e per le visualizzazioni: scaricalo"

    monkeypatch.setattr(
        enrichment_media,
        "detect_system_browser",
        lambda: enrichment_media.SystemBrowser(name="Microsoft Edge", channel="msedge"),
    )
    items_with_edge = {c["id"]: c for c in api_client.get("/api/v1/components").json()}
    assert items_with_edge["browser"]["required"] is False
    assert items_with_edge["browser"]["system_browser"] == "Microsoft Edge"
    assert items_with_edge["browser"]["in_use"] == "system"

    monkeypatch.setattr("rt.core.config.effective_engine", lambda cfg=None: "parakeet")
    items_onnx = {c["id"]: c for c in api_client.get("/api/v1/components").json()}
    assert items_onnx["macparakeet"]["required"] is False
    assert items_onnx["transcription"]["required"] is True

    assert api_client.post("/api/v1/components/unknown/download").status_code == 404
    assert api_client.post("/api/v1/components/unknown/cancel").status_code == 404
    assert api_client.delete("/api/v1/components/unknown").status_code == 404


def test_transcription_download_progress_lock_pause_resume_and_delete(api_client, isolated_data, monkeypatch):
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    models_root = isolated_data / "models"
    # Pre-popola vecchio modello int8 e VAD Silero per verificare la pulizia post-download
    legacy_int8 = models_root / onnx_stt.LEGACY_MODEL_NAME
    legacy_vad = models_root / onnx_stt.LEGACY_VAD_NAME
    legacy_int8.mkdir(parents=True)
    legacy_vad.mkdir(parents=True)
    (legacy_int8 / "encoder-model.int8.onnx").write_bytes(b"old")
    (legacy_vad / "silero_vad.onnx").write_bytes(b"vad")

    lock_seen = []
    started = threading.Event()
    allow_finish = threading.Event()

    def fake_download(name=onnx_stt.MODEL_DIR_NAME, quantization=onnx_stt.QUANTIZATION, *, on_progress=None, on_stats=None, cancel_token=None):
        lock_seen.append((name, (models_root / ".lock").exists()))
        target = models_root / name
        partial = models_root / f"{name}.partial"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "encoder-model.q8pc.onnx.part").write_bytes(b"123456")
        if on_stats:
            on_stats({
                "downloaded_bytes": 450 * 1024 * 1024,
                "total_bytes": 900 * 1024 * 1024,
                "percent": 50,
                "eta_seconds": 120.0,
                "eta_label": "circa 2 min",
            })
        started.set()
        while not allow_finish.is_set():
            if cancel_token is not None and getattr(cancel_token, "cancelled", False):
                raise RuntimeError("Trascrizione annullata")
            time.sleep(0.02)
        target.mkdir(parents=True, exist_ok=True)
        (target / "encoder-model.q8pc.onnx").write_bytes(b"ok" * 100)
        return str(target)

    monkeypatch.setattr(onnx_stt, "_download_resumable", fake_download)

    # 1. Avvio download e seconda chiamata idempotente (niente doppio download)
    res = api_client.post("/api/v1/components/transcription/download")
    assert res.status_code == 202
    assert started.wait(timeout=3.0)
    assert lock_seen == [(onnx_stt.MODEL_DIR_NAME, True)]

    res_dup = api_client.post("/api/v1/components/transcription/download")
    assert res_dup.status_code == 202

    listed = {c["id"]: c for c in api_client.get("/api/v1/components").json()}
    t = listed["transcription"]
    assert t["state"] == "downloading"
    assert t["percent"] == 50
    assert t["eta_label"] == "circa 2 min"

    # 2. Pausa: ferma il thread, mantiene i .part e passa a paused
    paused = api_client.post("/api/v1/components/transcription/cancel")
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    assert (models_root / f"{onnx_stt.MODEL_DIR_NAME}.partial" / "encoder-model.q8pc.onnx.part").is_file()
    assert not (models_root / ".lock").exists()

    # 3. Riprendi e completa -> ready (e vecchio int8 + silero eliminati)
    allow_finish.set()
    resumed = api_client.post("/api/v1/components/transcription/download")
    assert resumed.status_code == 202
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        t = {c["id"]: c for c in api_client.get("/api/v1/components").json()}["transcription"]
        if t["state"] == "ready":
            break
        time.sleep(0.02)
    assert t["state"] == "ready"
    assert t["percent"] == 100
    assert onnx_stt.model_ready()
    assert not legacy_int8.exists()
    assert not legacy_vad.exists()

    # 4. Elimina -> pulisce file e stato in memoria
    onnx_stt._loaded["asr"] = object()
    deleted = api_client.delete("/api/v1/components/transcription")
    assert deleted.status_code == 200
    assert deleted.json()["state"] == "not_downloaded"
    assert not onnx_stt.model_ready()
    assert "asr" not in onnx_stt._loaded


def test_browser_download_parses_progress_logs_and_deletes(api_client, isolated_data, monkeypatch):
    monkeypatch.setattr(components, "browser_available", lambda: True)
    commands = []

    class FakeProc:
        def __init__(self, cmd, *a, **kw):
            commands.append(cmd)
            self.pid = 424242
            self.stdout = io.BytesIO(
                b"Downloading Chromium\r"
                b"|====      |  45% of 105.4 MiB\r"
                b"|==========| 100% of 105.4 MiB\n"
            )
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self):
            target = isolated_data / "browsers" / "chromium_headless_shell-1243"
            target.mkdir(parents=True, exist_ok=True)
            (target / "chrome-headless-shell").write_bytes(b"binary")
            return 0

    monkeypatch.setattr(components.subprocess, "Popen", FakeProc)

    res = api_client.post("/api/v1/components/browser/download")
    assert res.status_code == 202
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        b = {c["id"]: c for c in api_client.get("/api/v1/components").json()}["browser"]
        if b["state"] == "ready":
            break
        time.sleep(0.02)
    assert b["state"] == "ready"
    assert commands == [[sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"]]
    log_text = (isolated_data / "logs" / "browser-install.log").read_text(encoding="utf-8")
    assert "45% of 105.4 MiB" in log_text

    deleted = api_client.delete("/api/v1/components/browser")
    assert deleted.status_code == 200
    assert deleted.json()["state"] == "not_downloaded"
    assert not components.browser_ready()


def test_resume_interrupted_downloads_restarts_only_auto_resume(isolated_data, monkeypatch):
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    started = []
    monkeypatch.setattr(components, "start_download", lambda cid: started.append(cid) or components.get_component(cid))

    components._write_component_state(components.TRANSCRIPTION_ID, {
        "state": "downloading",
        "auto_resume": True,
        "percent": 35,
    })
    components._write_component_state(components.BROWSER_ID, {
        "state": "paused",
        "auto_resume": False,
        "percent": 20,
    })

    resumed = components.resume_interrupted_downloads()
    assert resumed == ["transcription"]
    assert started == ["transcription"]


def test_ensure_capture_browser_does_not_download_and_cleans_old_browsers(isolated_data, monkeypatch):
    monkeypatch.setattr(desktop.bundle, "kind", lambda: "macos")
    monkeypatch.setattr(components, "current_playwright_headless_revision", lambda: "1243")

    browsers = isolated_data / "browsers"
    old_full = browsers / "chromium-1200"
    old_shell = browsers / "chromium_headless_shell-1100"
    cur_shell = browsers / "chromium_headless_shell-1243" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    old_full.mkdir(parents=True)
    (old_full / "big.bin").write_bytes(b"x" * 2048)
    old_shell.mkdir(parents=True)
    (old_shell / "old.bin").write_bytes(b"y" * 1024)
    cur_shell.parent.mkdir(parents=True)
    cur_shell.write_bytes(b"shell")

    monkeypatch.setattr(
        components.subprocess,
        "Popen",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Nessun download automatico all'avvio")),
    )
    messages = []
    desktop.ensure_capture_browser(messages.append)

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and (old_full.exists() or old_shell.exists()):
        time.sleep(0.02)

    assert messages == []
    assert not old_full.exists()
    assert not old_shell.exists()
    assert cur_shell.is_file()
    assert components.get_component(components.BROWSER_ID)["state"] == "ready"


def test_worker_waits_for_active_download_and_emits_progress(isolated_data, monkeypatch):
    models_root = isolated_data / "models"
    lpath = components.lock_path_for(components.TRANSCRIPTION_ID)
    acquire_file_lock(lpath)
    components._write_component_state(components.TRANSCRIPTION_ID, {
        "state": "downloading",
        "auto_resume": True,
        "downloaded_bytes": 450 * 1024 * 1024,
        "total_bytes": 900 * 1024 * 1024,
        "percent": 42,
        "eta_label": "circa 6 min",
    })

    def finish_other_download():
        time.sleep(0.15)
        (models_root / onnx_stt.MODEL_DIR_NAME).mkdir(parents=True, exist_ok=True)
        release_file_lock(lpath)

    t = threading.Thread(target=finish_other_download, daemon=True)
    t.start()

    seen = []
    model_path = components.ensure_transcription_model(on_progress=seen.append)
    t.join(timeout=2.0)

    assert model_path == str(models_root / onnx_stt.MODEL_DIR_NAME)
    assert any("42%" in m and "circa 6 min" in m for m in seen)


def test_worker_wait_respects_cancel_token(isolated_data):
    lpath = components.lock_path_for(components.TRANSCRIPTION_ID)
    acquire_file_lock(lpath)
    try:
        token = CancelToken()
        token.cancel()
        with pytest.raises(RunCancelled):
            components.ensure_transcription_model(cancel_token=token)
    finally:
        release_file_lock(lpath)


def test_emit_stt_progress_extracts_percentage():
    events = []
    reporter = SimpleNamespace(emit=events.append)
    ctx = RunContext(reporter=reporter)
    emit_stt_progress(ctx, "prepare", "Scarico il modello di trascrizione: 42% (281 di 670 MB, circa 6 minuti)")
    assert len(events) == 1
    assert events[0].phase == "prepare"
    assert events[0].current == 42
    assert events[0].total == 100


def test_cancel_never_kills_other_process_downloading_model(isolated_data, monkeypatch):
    """La pausa da Impostazioni non deve mai terminare il worker che scarica il modello per una
    lezione (né un PID salvato e magari riusato): risponde «occupato»."""
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    killed = []
    monkeypatch.setattr(components.os, "kill", lambda pid, sig: killed.append(pid))
    lock = components.lock_path_for(components.TRANSCRIPTION_ID)
    import os as _os
    _os.makedirs(_os.path.dirname(lock), exist_ok=True)
    acquire_file_lock(lock, retries=1, stale_sec=30)
    try:
        components._write_component_state(components.TRANSCRIPTION_ID, {"state": "downloading", "pid": 424242})
        with pytest.raises(components.ComponentBusy):
            components.cancel_download(components.TRANSCRIPTION_ID)
    finally:
        release_file_lock(lock)
    assert killed == []
    components._write_component_state(components.BROWSER_ID, {"state": "downloading", "pid": 424243, "helper_pid": 424244})
    components.cancel_download(components.BROWSER_ID)
    assert killed == []


def _make_macparakeet_tarball(script_bytes: bytes, *, extra_files: dict[str, bytes] | None = None, member_name: str = components.MACPARAKEET_TARBALL_MEMBER) -> bytes:
    import io as _io
    import tarfile as _tarfile

    buf = _io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if extra_files:
            for name, content in extra_files.items():
                info = _tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, _io.BytesIO(content))
        info = _tarfile.TarInfo(member_name)
        info.size = len(script_bytes)
        info.mode = 0o644
        tar.addfile(info, _io.BytesIO(script_bytes))
    return buf.getvalue()


def _serve_bytes(payload: bytes):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                start = int(rng.removeprefix("bytes=").split("-", 1)[0] or "0")
                chunk = payload[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/macparakeet-cli.tar.gz"


@pytest.mark.skipif(sys.platform == "win32", reason="macparakeet esiste solo su macOS: il finto eseguibile è uno script shell")
def test_macparakeet_download_verifies_sha256_extracts_member_and_deletes(api_client, isolated_data, monkeypatch):
    import hashlib
    import os as _os
    import stat as _stat
    from rt.pipeline import setup

    fake_home = isolated_data / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows: expanduser usa USERPROFILE
    monkeypatch.delenv("RT_MACPARAKEET_MODELS_DIR", raising=False)
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    monkeypatch.setattr("rt.core.config.effective_engine", lambda cfg=None: "macparakeet")
    monkeypatch.setattr(setup.shutil, "which", lambda _n: None)
    monkeypatch.setattr(setup, "_MACPARAKEET_SYSTEM_PATHS", ())

    script = (
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        "if sys.argv[1:4] == ['models', 'download', 'parakeet-v3']:\n"
        "    models = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'FluidAudio', 'Models', 'parakeet-v3')\n"
        "    os.makedirs(models, exist_ok=True)\n"
        "    with open(os.path.join(models, 'model.bin'), 'wb') as f:\n"
        "        f.write(b'M' * 4096)\n"
        "    print('Downloading parakeet-v3 60%', flush=True)\n"
        "    time.sleep(0.05)\n"
        "    print('100%', flush=True)\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    ).encode("utf-8")

    tarball = _make_macparakeet_tarball(script, extra_files={"macparakeet-cli-5.1.0-darwin-arm64/README.txt": b"ignore"})
    tar_sha = hashlib.sha256(tarball).hexdigest()
    bin_sha = hashlib.sha256(script).hexdigest()

    srv, url = _serve_bytes(tarball)
    try:
        monkeypatch.setattr(components, "MACPARAKEET_URL", url)
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_BYTES", len(tarball))
        monkeypatch.setattr(components, "MACPARAKEET_MODEL_APPROX_BYTES", 8192)

        # 1. SHA256 del .tar.gz errato -> errore e nessun binario installato
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_SHA256", "0" * 64)
        monkeypatch.setattr(components, "MACPARAKEET_BINARY_SHA256", bin_sha)
        with pytest.raises(components.ComponentError, match="SHA256"):
            components.ensure_macparakeet()
        assert not components.macparakeet_bin_path().endswith(".part")
        assert not _os.path.exists(components.macparakeet_bin_path())

        # 2. SHA256 del binario errato -> errore e nessun binario installato
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_SHA256", tar_sha)
        monkeypatch.setattr(components, "MACPARAKEET_BINARY_SHA256", "f" * 64)
        with pytest.raises(components.ComponentError, match="SHA256"):
            components.ensure_macparakeet()
        assert not _os.path.exists(components.macparakeet_bin_path())

        # 3. Tutto valido -> scarica via API, verifica entrambi gli SHA256, estrae solo il membro, scarica modello
        monkeypatch.setattr(components, "MACPARAKEET_BINARY_SHA256", bin_sha)
        res = api_client.post("/api/v1/components/macparakeet/download")
        assert res.status_code == 202

        deadline = time.monotonic() + 5.0
        item = {}
        while time.monotonic() < deadline:
            item = {c["id"]: c for c in api_client.get("/api/v1/components").json()}["macparakeet"]
            if item["state"] == "ready":
                break
            assert item["state"] != "error", item.get("error")
            time.sleep(0.02)

        assert item["state"] == "ready"
        assert item["percent"] == 100
        bin_path = isolated_data / "bin" / "macparakeet-cli"
        assert bin_path.is_file()
        assert _stat.S_IMODE(bin_path.stat().st_mode) == 0o755
        assert not (isolated_data / "bin" / "README.txt").exists()
        assert not (isolated_data / "bin" / "macparakeet-cli.tar.gz.part").exists()
        assert setup.find_macparakeet_binary() == str(bin_path)
        model_dir = fake_home / "Library" / "Application Support" / "FluidAudio" / "Models" / "parakeet-v3"
        assert (model_dir / "model.bin").is_file()

        # 4. Elimina -> rimuove binario e cartella del modello
        deleted = api_client.delete("/api/v1/components/macparakeet")
        assert deleted.status_code == 200
        assert deleted.json()["state"] == "not_downloaded"
        assert not bin_path.exists()
        assert not model_dir.exists()
    finally:
        srv.shutdown()
        srv.server_close()


def test_macparakeet_rejects_path_traversal_member(isolated_data, monkeypatch):
    import hashlib
    from rt.pipeline import setup

    script = b"#!/bin/sh\nexit 0\n"
    tarball = _make_macparakeet_tarball(script, member_name="../evil")
    srv, url = _serve_bytes(tarball)
    try:
        monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
        monkeypatch.setattr(setup.shutil, "which", lambda _n: None)
        monkeypatch.setattr(setup, "_MACPARAKEET_SYSTEM_PATHS", ())
        monkeypatch.setattr(components, "MACPARAKEET_URL", url)
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_MEMBER", "../evil")
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_SHA256", hashlib.sha256(tarball).hexdigest())
        monkeypatch.setattr(components, "MACPARAKEET_BINARY_SHA256", hashlib.sha256(script).hexdigest())
        with pytest.raises(components.ComponentError, match="Percorso non sicuro"):
            components.ensure_macparakeet()
        assert not (isolated_data / "evil").exists()
        assert not (isolated_data / "bin" / "macparakeet-cli").exists()
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(sys.platform == "win32", reason="macparakeet esiste solo su macOS: il finto eseguibile è uno script shell")
def test_macparakeet_folder_growth_progress_and_pause_resume(isolated_data, monkeypatch):
    import hashlib
    from rt.pipeline import setup

    fake_home = isolated_data / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows: expanduser usa USERPROFILE
    monkeypatch.delenv("RT_MACPARAKEET_MODELS_DIR", raising=False)
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    monkeypatch.setattr(setup.shutil, "which", lambda _n: None)
    monkeypatch.setattr(setup, "_MACPARAKEET_SYSTEM_PATHS", ())
    monkeypatch.setattr(components, "MACPARAKEET_MODEL_APPROX_BYTES", 10_000)

    # Script che NON stampa percentuali: l'avanzamento viene calcolato dalla crescita della cartella.
    script = (
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        "models = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'FluidAudio', 'Models', 'parakeet-v3')\n"
        "os.makedirs(models, exist_ok=True)\n"
        "with open(os.path.join(models, 'weights.bin'), 'wb') as f:\n"
        "    f.write(b'W' * 5000)\n"
        "    f.flush()\n"
        "    time.sleep(0.3)\n"
        "    f.write(b'W' * 5000)\n"
        "    f.flush()\n"
    ).encode("utf-8")

    tarball = _make_macparakeet_tarball(script)
    srv, url = _serve_bytes(tarball)
    try:
        monkeypatch.setattr(components, "MACPARAKEET_URL", url)
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_BYTES", len(tarball))
        monkeypatch.setattr(components, "MACPARAKEET_TARBALL_SHA256", hashlib.sha256(tarball).hexdigest())
        monkeypatch.setattr(components, "MACPARAKEET_BINARY_SHA256", hashlib.sha256(script).hexdigest())

        seen = []
        bin_path = components.ensure_macparakeet(on_progress=seen.append)
        assert bin_path == str(isolated_data / "bin" / "macparakeet-cli")
        assert any("Scarico il motore di trascrizione:" in m and "%" in m for m in seen)
        assert components.get_component("macparakeet")["state"] == "ready"
    finally:
        srv.shutdown()
        srv.server_close()


def test_find_capture_browser_executable_finds_headless_shell(tmp_path, monkeypatch):
    from rt.llm.enrichment_media import find_capture_browser_executable

    browsers = tmp_path / "browsers"
    shell_bin = browsers / "chromium_headless_shell-1243" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    shell_bin.parent.mkdir(parents=True)
    shell_bin.write_bytes(b"shell")

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    monkeypatch.delenv("RT_ENRICHMENT_CHROMIUM", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    fake_playwright = SimpleNamespace(
        chromium=SimpleNamespace(executable_path=str(browsers / "chromium-1243" / "chrome-mac-arm64" / "Google Chrome"))
    )
    assert find_capture_browser_executable(fake_playwright) == str(shell_bin)


def test_detect_system_browser_windows_mac_linux(isolated_data, monkeypatch):
    import os as _os
    from rt.llm import enrichment_media

    # 1. Windows: Edge ha precedenza su Chrome
    monkeypatch.setattr(enrichment_media.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles(x86)", "C:/PF86")
    monkeypatch.setenv("ProgramFiles", "C:/PF")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Local")
    edge_path = _os.path.join("C:/PF86", "Microsoft", "Edge", "Application", "msedge.exe")
    chrome_path = _os.path.join("C:/PF", "Google", "Chrome", "Application", "chrome.exe")

    present = {edge_path, chrome_path}
    monkeypatch.setattr(enrichment_media.os.path, "isfile", lambda p: p in present)
    sb = enrichment_media.detect_system_browser()
    assert sb == enrichment_media.SystemBrowser(name="Microsoft Edge", channel="msedge")

    # Solo Chrome presente su Windows
    present = {chrome_path}
    sb = enrichment_media.detect_system_browser()
    assert sb == enrichment_media.SystemBrowser(name="Google Chrome", channel="chrome")

    # Niente su Windows
    present = set()
    assert enrichment_media.detect_system_browser() is None

    # 2. Mac: Chrome prima di Edge prima di Chromium
    monkeypatch.setattr(enrichment_media.sys, "platform", "darwin")
    fake_home = isolated_data / "fake_home"
    mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    mac_edge = _os.path.join(str(fake_home), "Applications", "Microsoft Edge.app", "Contents", "MacOS", "Microsoft Edge")
    mac_chromium = "/Applications/Chromium.app/Contents/MacOS/Chromium"

    present = {mac_chrome, mac_edge, mac_chromium}
    assert enrichment_media.detect_system_browser() == enrichment_media.SystemBrowser(name="Google Chrome", channel="chrome")

    present = {mac_edge, mac_chromium}
    assert enrichment_media.detect_system_browser() == enrichment_media.SystemBrowser(name="Microsoft Edge", channel="msedge")

    present = {mac_chromium}
    assert enrichment_media.detect_system_browser() == enrichment_media.SystemBrowser(name="Chromium", executable_path=mac_chromium)

    present = set()
    assert enrichment_media.detect_system_browser() is None

    # 3. Linux/Docker: chromium poi google-chrome
    monkeypatch.setattr(enrichment_media.sys, "platform", "linux")
    monkeypatch.setattr(enrichment_media.shutil, "which", lambda cmd: "/usr/bin/chromium" if cmd == "chromium" else "/usr/bin/google-chrome")
    assert enrichment_media.detect_system_browser() == enrichment_media.SystemBrowser(name="Chromium", executable_path="/usr/bin/chromium")
    monkeypatch.setattr(enrichment_media.shutil, "which", lambda cmd: "/usr/bin/google-chrome" if cmd == "google-chrome" else None)
    assert enrichment_media.detect_system_browser() == enrichment_media.SystemBrowser(name="Google Chrome", executable_path="/usr/bin/google-chrome")
    monkeypatch.setattr(enrichment_media.shutil, "which", lambda _cmd: None)
    assert enrichment_media.detect_system_browser() is None


def test_launch_capture_browser_priority_fallback_and_missing(isolated_data, monkeypatch, caplog):
    from rt.llm import enrichment_media

    monkeypatch.delenv("RT_ENRICHMENT_CHROMIUM", raising=False)
    browsers = isolated_data / "browsers"
    shell_bin = browsers / "chromium_headless_shell-1243" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    shell_bin.parent.mkdir(parents=True)
    shell_bin.write_bytes(b"shell")

    edge = enrichment_media.SystemBrowser(name="Microsoft Edge", channel="msedge")
    chrome = enrichment_media.SystemBrowser(name="Google Chrome", channel="chrome")
    monkeypatch.setattr(
        enrichment_media,
        "_iter_system_browser_candidates",
        lambda: [(edge, "/fake/msedge"), (chrome, "/fake/chrome")],
    )

    calls = []
    fake_browser = object()

    def make_p(fail_on=()):
        def fake_launch(**kw):
            calls.append(kw)
            key = kw.get("channel") or kw.get("executable_path") or "component"
            if key in fail_on:
                raise RuntimeError(f"boom {key}")
            return fake_browser

        return SimpleNamespace(chromium=SimpleNamespace(launch=fake_launch, executable_path=""))

    # 1. Componente pronto -> usato per primo anche se c'è Edge
    calls.clear()
    with caplog.at_level("INFO"):
        res = enrichment_media.launch_capture_browser(make_p())
    assert res is fake_browser
    assert calls == [{"headless": True}]
    assert any("uso browser scaricato" in r.message for r in caplog.records)

    # 2. Componente che non parte -> passa a Edge (sistema)
    calls.clear()
    caplog.clear()
    with caplog.at_level("WARNING"):
        res = enrichment_media.launch_capture_browser(make_p(fail_on=("component",)))
    assert res is fake_browser
    assert calls == [{"headless": True}, {"headless": True, "channel": "msedge"}]
    assert any("browser scaricato non si avvia" in r.message for r in caplog.records)

    # 3. Componente assente -> usa subito canale di sistema (Edge)
    shell_bin.unlink()
    calls.clear()
    res = enrichment_media.launch_capture_browser(make_p())
    assert res is fake_browser
    assert calls == [{"headless": True, "channel": "msedge"}]

    # 4. Edge non parte -> passa a Chrome
    calls.clear()
    res = enrichment_media.launch_capture_browser(make_p(fail_on=("msedge",)))
    assert res is fake_browser
    assert calls == [{"headless": True, "channel": "msedge"}, {"headless": True, "channel": "chrome"}]

    # 5. Tutti i candidati falliscono -> RuntimeError con motivo e suggerimento
    with pytest.raises(RuntimeError, match="boom chrome.*Impostazioni › Lavorazione delle lezioni › Componenti"):
        enrichment_media.launch_capture_browser(make_p(fail_on=("msedge", "chrome")))

    # 6. Nessun candidato -> BrowserMissingError
    monkeypatch.setattr(enrichment_media, "_iter_system_browser_candidates", lambda: [])
    with pytest.raises(enrichment_media.BrowserMissingError):
        enrichment_media.launch_capture_browser(make_p())


def test_browser_ready_ignores_full_chromium_and_checks_headless_executable(isolated_data):
    browsers = isolated_data / "browsers"
    full_dir = browsers / "chromium-1243" / "chrome-mac-arm64"
    full_dir.mkdir(parents=True)
    (full_dir / "Google Chrome").write_bytes(b"full")
    assert not components.browser_ready()

    empty_shell = browsers / "chromium_headless_shell-1243"
    empty_shell.mkdir(parents=True)
    assert not components.browser_ready()

    shell_exe = empty_shell / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    shell_exe.parent.mkdir(parents=True)
    shell_exe.write_bytes(b"shell")
    assert components.browser_ready()


def test_cleanup_old_browsers_and_skips_when_download_active(isolated_data, monkeypatch):
    monkeypatch.setattr(components, "current_playwright_headless_revision", lambda: "1243")
    browsers = isolated_data / "browsers"
    old_full = browsers / "chromium-1243"
    old_shell = browsers / "chromium_headless_shell-1100"
    cur_shell = browsers / "chromium_headless_shell-1243" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    for folder in (old_full, old_shell):
        folder.mkdir(parents=True)
        (folder / "data.bin").write_bytes(b"a" * (1024 * 1024))
    cur_shell.parent.mkdir(parents=True)
    cur_shell.write_bytes(b"keep")

    # Con download attivo non tocca nulla
    lpath = components.lock_path_for(components.BROWSER_ID)
    acquire_file_lock(lpath)
    try:
        assert components.cleanup_old_browsers() == 0
        assert old_full.exists()
        assert old_shell.exists()
    finally:
        release_file_lock(lpath)

    freed = components.cleanup_old_browsers()
    assert freed == 2 * 1024 * 1024
    assert not old_full.exists()
    assert not old_shell.exists()
    assert cur_shell.is_file()
    log_text = (isolated_data / "logs" / "browser-install.log").read_text(encoding="utf-8")
    assert "Pulizia browser obsoleti" in log_text
    assert "2.0 MB" in log_text


def test_component_meta_browser_three_cases(isolated_data, monkeypatch):
    from rt.llm import enrichment_media

    monkeypatch.setattr(components, "browser_available", lambda: True)

    # Caso 1: non scaricato, niente browser
    monkeypatch.setattr(enrichment_media, "detect_system_browser", lambda: None)
    meta_missing = components._component_meta(components.BROWSER_ID)
    assert meta_missing["required"] is True
    assert meta_missing["system_browser"] is None
    assert meta_missing["in_use"] is None
    assert meta_missing["detail"] == "Chrome Headless Shell (versione minima)"
    assert meta_missing["description"] == "Serve per esportare in PDF e per le visualizzazioni: scaricalo"

    # Caso 2: non scaricato, browser di sistema rilevato
    monkeypatch.setattr(
        enrichment_media,
        "detect_system_browser",
        lambda: enrichment_media.SystemBrowser(name="Google Chrome", channel="chrome"),
    )
    meta_sys = components._component_meta(components.BROWSER_ID)
    assert meta_sys["required"] is False
    assert meta_sys["system_browser"] == "Google Chrome"
    assert meta_sys["in_use"] == "system"
    assert meta_sys["description"] == (
        "Rilevato Google Chrome: RT usa quello, scaricare questo componente non è necessario. "
        "Se lo scarichi, RT usa questo"
    )

    # Caso 3: componente pronto (ha precedenza sul browser di sistema)
    shell_exe = isolated_data / "browsers" / "chromium_headless_shell-1243" / "chrome-headless-shell"
    shell_exe.parent.mkdir(parents=True)
    shell_exe.write_bytes(b"shell")
    meta_ready = components._component_meta(components.BROWSER_ID)
    assert meta_ready["required"] is False
    assert meta_ready["system_browser"] == "Google Chrome"
    assert meta_ready["in_use"] == "component"
    assert meta_ready["description"] == "RT usa il browser scaricato per esportare in PDF e per le visualizzazioni"


def test_snapshot_triggers_fallback_download_on_missing_browser(isolated_data, monkeypatch):
    from rt.llm import enrichment_media

    started = []
    monkeypatch.setattr(components, "browser_available", lambda: True)
    monkeypatch.setattr(enrichment_media, "detect_system_browser", lambda: None)
    monkeypatch.setattr(
        components,
        "start_download",
        lambda cid: started.append(cid) or {**components.get_component(cid), "state": "downloading"},
    )

    class FakeSyncPlaywright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: None, executable_path=""))

        def __exit__(self, *a):
            return False

    import playwright.sync_api as sync_api
    monkeypatch.setattr(sync_api, "sync_playwright", FakeSyncPlaywright)
    monkeypatch.setattr(
        enrichment_media,
        "launch_capture_browser",
        lambda _p: (_ for _ in ()).throw(enrichment_media.BrowserMissingError("manca")),
    )

    with pytest.raises(enrichment_media.BrowserMissingError):
        enrichment_media.snapshot("<html></html>")
    assert started == [components.BROWSER_ID]
