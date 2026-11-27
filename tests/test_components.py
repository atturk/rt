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

    res = api_client.get("/api/v1/components")
    assert res.status_code == 200
    items = {c["id"]: c for c in res.json()}
    assert set(items) == {"transcription", "browser"}
    assert items["transcription"]["state"] == "not_downloaded"
    assert items["transcription"]["required"] is True
    assert items["browser"]["state"] == "not_downloaded"
    assert items["browser"]["required"] is False

    assert api_client.post("/api/v1/components/unknown/download").status_code == 404
    assert api_client.post("/api/v1/components/unknown/cancel").status_code == 404
    assert api_client.delete("/api/v1/components/unknown").status_code == 404


def test_transcription_download_progress_lock_pause_resume_and_delete(api_client, isolated_data, monkeypatch):
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    models_root = isolated_data / "models"
    lock_seen = []
    started = threading.Event()
    allow_finish = threading.Event()

    def fake_download(name, quantization, *, vad=False, on_progress=None, on_stats=None, cancel_token=None):
        lock_seen.append((name, (models_root / ".lock").exists()))
        target = models_root / name
        partial = models_root / f"{name}.partial"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "weights.bin.part").write_bytes(b"123456")
        if name == onnx_stt.MODEL_NAME:
            if on_stats:
                on_stats({
                    "downloaded_bytes": 335 * 1024 * 1024,
                    "total_bytes": 670 * 1024 * 1024,
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
        (target / "model.onnx").write_bytes(b"ok" * 100)
        return str(target)

    monkeypatch.setattr(onnx_stt, "_download_resumable", fake_download)

    # 1. Avvio download e seconda chiamata idempotente (niente doppio download)
    res = api_client.post("/api/v1/components/transcription/download")
    assert res.status_code == 202
    assert started.wait(timeout=3.0)
    assert lock_seen == [(onnx_stt.MODEL_NAME, True)]

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
    assert (models_root / f"{onnx_stt.MODEL_NAME}.partial" / "weights.bin.part").is_file()
    assert not (models_root / ".lock").exists()

    # 3. Riprendi e completa -> ready
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

    # 4. Elimina -> pulisce file e stato in memoria
    onnx_stt._loaded["asr"] = object()
    deleted = api_client.delete("/api/v1/components/transcription")
    assert deleted.status_code == 200
    assert deleted.json()["state"] == "not_downloaded"
    assert not onnx_stt.model_ready()
    assert "asr" not in onnx_stt._loaded


def test_browser_download_parses_progress_logs_and_deletes(api_client, isolated_data, monkeypatch):
    monkeypatch.setattr(components, "browser_available", lambda: True)

    class FakeProc:
        def __init__(self, *a, **kw):
            self.pid = 424242
            self.stdout = io.BytesIO(
                b"Downloading Chromium\r"
                b"|====      |  45% of 165.4 MiB\r"
                b"|==========| 100% of 165.4 MiB\n"
            )
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self):
            target = isolated_data / "browsers" / "chromium-1234"
            target.mkdir(parents=True, exist_ok=True)
            (target / "chrome").write_bytes(b"binary")
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
    log_text = (isolated_data / "logs" / "browser-install.log").read_text(encoding="utf-8")
    assert "45% of 165.4 MiB" in log_text

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
    assert any("browser per le catture" in m for m in messages)
    status = components.get_component(components.BROWSER_ID)
    assert status["state"] in ("downloading", "paused") or (isolated_data / "models" / "components.json").is_file()


def test_worker_waits_for_active_download_and_emits_progress(isolated_data, monkeypatch):
    models_root = isolated_data / "models"
    lpath = components.lock_path_for(components.TRANSCRIPTION_ID)
    acquire_file_lock(lpath)
    components._write_component_state(components.TRANSCRIPTION_ID, {
        "state": "downloading",
        "auto_resume": True,
        "downloaded_bytes": 280 * 1024 * 1024,
        "total_bytes": 670 * 1024 * 1024,
        "percent": 42,
        "eta_label": "circa 6 min",
    })

    def finish_other_download():
        time.sleep(0.15)
        (models_root / onnx_stt.MODEL_NAME).mkdir(parents=True, exist_ok=True)
        (models_root / onnx_stt.VAD_NAME).mkdir(parents=True, exist_ok=True)
        release_file_lock(lpath)

    t = threading.Thread(target=finish_other_download, daemon=True)
    t.start()

    seen = []
    model_path, vad_path = components.ensure_transcription_model(on_progress=seen.append)
    t.join(timeout=2.0)

    assert model_path == str(models_root / onnx_stt.MODEL_NAME)
    assert vad_path == str(models_root / onnx_stt.VAD_NAME)
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
