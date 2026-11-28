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
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    monkeypatch.setattr(components, "browser_available", lambda: True)
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    monkeypatch.setattr("rt.core.config.effective_engine", lambda cfg=None: "macparakeet")

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
    assert items["browser"]["required"] is False
    assert items["browser"]["name"] == "Browser per PDF e catture"
    assert "esportare in PDF" in items["browser"]["description"]

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


def test_ensure_capture_browser_uses_component_manager(isolated_data, monkeypatch):
    monkeypatch.setattr(desktop.bundle, "kind", lambda: "macos")
    monkeypatch.setattr(components, "browser_available", lambda: True)

    spawned = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            spawned.append(cmd)

    monkeypatch.setattr(components.subprocess, "Popen", FakePopen)
    messages = []
    desktop.ensure_capture_browser(messages.append)

    assert len(spawned) == 1
    assert spawned[0] == [sys.executable, "-m", "rt.core.components", "--install-browser"]
    assert any("browser per PDF e catture" in m for m in messages)
    status = components.get_component(components.BROWSER_ID)
    assert status["state"] in ("downloading", "paused") or (isolated_data / "models" / "components.json").is_file()


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
