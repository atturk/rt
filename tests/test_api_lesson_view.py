"""
tests/test_api_lesson_view.py
RT4-F2: quello che serve alla vista lezione della SPA oltre agli endpoint della fase E:
unità marcate nell'HTML del documento, audio riproducibile dal browser e forma d'onda.
"""
import array
import os
import subprocess
import time

import pytest

from tests.api_support import add_audio, isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(root)
    assert run_mock_pipeline(lesson_dir, auto_accept=True).status.value == "completed"
    return lesson_dir


def _lesson_id(client):
    return client.get("/api/v1/lessons").json()[0]["id"]


def test_document_marks_unit_headings_and_timecodes(api_client, lesson):
    doc = api_client.get(f"/api/v1/lessons/{_lesson_id(api_client)}/document").json()
    section = doc["sections"][0]
    unit = section["unit_id"]
    assert f'<h3 data-unit-id="{unit}" id="unit-{unit}">' in doc["html"]
    assert f'<p data-unit-timecode="{unit}">{section["start_formatted"]}</p>' in doc["html"]


def test_document_marks_only_known_units(api_client, lesson):
    from rt.core.lesson_paths import lesson_path
    from rt.storage import fs
    with fs.open(lesson_path(lesson, "rielaborato.md"), "w", encoding="utf-8") as f:
        f.write("# Titolo\n\n### 9.9 Non esiste\n00:02\n\n### Senza id\n")
    html = api_client.get(f"/api/v1/lessons/{_lesson_id(api_client)}/document").json()["html"]
    assert "data-unit-id" not in html and "data-unit-timecode" not in html


def test_waveform_is_computed_in_background(api_client, lesson, monkeypatch):
    import rt.services.audio_service as audio_service
    lesson_id = _lesson_id(api_client)
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/audio/waveform").status_code == 404
    add_audio(lesson)
    monkeypatch.setattr(audio_service, "compute_waveform", lambda path: [3, 40, 72])
    first = api_client.get(f"/api/v1/lessons/{lesson_id}/audio/waveform").json()
    deadline = time.monotonic() + 5
    res = first
    while not res["ready"] and time.monotonic() < deadline:
        time.sleep(0.05)
        res = api_client.get(f"/api/v1/lessons/{lesson_id}/audio/waveform").json()
    assert res == {"ready": True, "peaks": [3, 40, 72]}


def test_levels_from_samples_normalizes():
    from rt.services.audio_service import levels_from_samples
    samples = array.array("h", [0] * 100 + [1000] * 100 + [30000] * 100)
    levels = levels_from_samples(samples, bars=3)
    assert levels[0] == 3 and levels[-1] == 72 and 3 <= levels[1] <= 72
    assert levels_from_samples(array.array("h")) == []


def test_playable_audio_keeps_original_when_remux_impossible(tmp_path, rt_db, monkeypatch):
    from rt.services import audio_service
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....WAVE")
    assert audio_service.playable_audio(str(wav)) == str(wav)
    mp4 = tmp_path / "b.m4a"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypM4A ")
    assert audio_service.playable_audio(str(mp4)) == str(mp4)
    adts = tmp_path / "c.m4a"
    adts.write_bytes(b"\xff\xf1\x50\x80" + b"\x00" * 20)

    def no_ffmpeg(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(subprocess, "run", no_ffmpeg)
    assert audio_service.playable_audio(str(adts)) == str(adts)


def test_playable_audio_remuxes_adts_once(tmp_path, rt_db, monkeypatch):
    from rt.services import audio_service
    adts = tmp_path / "c.m4a"
    adts.write_bytes(b"\xff\xf1\x50\x80" + b"\x00" * 20)
    calls = []

    def fake_ffmpeg(cmd, **kwargs):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypM4A remuxed")
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    first = audio_service.playable_audio(str(adts))
    assert first != str(adts) and open(first, "rb").read().endswith(b"remuxed")
    assert audio_service.playable_audio(str(adts)) == first and len(calls) == 1
    assert not os.path.exists(first + ".tmp.m4a")
