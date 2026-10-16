"""Test per AU2d: alleggerimento audio delle lezioni e pulizia orfani."""
import json
import os
from unittest.mock import patch

from rt.core.idempotency import compute_file_sha256
from rt.core.source_selection import selection
from rt.core.sources import Source, _save, load_sources
from rt.pipeline.source_update import _write_state, prepare_source_update, sources_pending
from rt.services.audio_compaction import compact_audio_lessons, preview_compact_audio
from rt.storage import fs


def _setup_mock_lesson(lesson_dir):
    fs.makedirs(os.path.join(lesson_dir, "sources"), exist_ok=True)
    wav_path = os.path.join(lesson_dir, "sources", "registrazione.wav")
    with fs.open(wav_path, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 2000)

    # Crea orphan audio file
    orphan_path = os.path.join(lesson_dir, "audio-abcdef1234567890abcdef1234567890.m4a")
    with fs.open(orphan_path, "wb") as f:
        f.write(b"ORPHAN_MERGED_AUDIO" * 50)

    # Info yaml
    info_path = os.path.join(lesson_dir, "info.yaml")
    with fs.open(info_path, "w", encoding="utf-8") as f:
        f.write("titolo: Lezione Test\nfile_audio: sources/registrazione.wav\n")

    # Sources.json
    s1 = Source(
        id="src_000001",
        file="sources/registrazione.wav",
        nome="registrazione.wav",
        tipo="audio",
        ordine=1,
        aggiunta_il="2026-01-01T10:00:00Z",
        impronta=compute_file_sha256(wav_path),
    )
    _save(lesson_dir, [s1])

    # source_update.json
    state = {
        "next_segment": 2,
        "used": ["src_000001"],
        "principale": "src_000001",
        "sources": {
            "src_000001": {
                "segments": [
                    {
                        "id": "seg_000001",
                        "index": 1,
                        "start_seconds": 0.0,
                        "end_seconds": 5.0,
                        "start_formatted": "00:00",
                        "end_formatted": "00:05",
                        "text_raw": "Trascrizione esistente",
                        "flags": [],
                    }
                ],
                "duration": 5.0,
                "fingerprint": s1.impronta,
            }
        },
    }
    _write_state(lesson_dir, state)

    # segments.json
    from rt.core.models import Segment
    from rt.core.segments import save_segments_json
    save_segments_json(
        [Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=5.0,
                 start_formatted="00:00", end_formatted="00:05",
                 text_raw="Trascrizione esistente", flags=[])],
        os.path.join(lesson_dir, "segments.json"),
        lesson_id="test",
        audio_duration_seconds=5.0,
    )

    # History version con una fonte tolta in .wav
    hist_dir = os.path.join(lesson_dir, "history", "v1")
    fs.makedirs(hist_dir, exist_ok=True)
    hist_wav_path = os.path.join(lesson_dir, "sources", "vecchio_rimosso.wav")
    with fs.open(hist_wav_path, "wb") as f:
        f.write(b"RIFF" + b"\x00" * 1500)
    with fs.open(os.path.join(hist_dir, "sources.json"), "w", encoding="utf-8") as f:
        json.dump([
            {
                "id": "src_000002",
                "file": "sources/vecchio_rimosso.wav",
                "nome": "vecchio_rimosso.wav",
                "tipo": "audio",
                "ordine": 1,
                "aggiunta_il": "2026-01-01T10:00:00Z",
                "impronta": compute_file_sha256(hist_wav_path),
            }
        ], f)


def test_compact_audio_preview_and_conversion(tmp_path):
    lesson_dir = str(tmp_path / "lezione1")
    _setup_mock_lesson(lesson_dir)

    preview = preview_compact_audio([lesson_dir])
    assert preview["file_convertibili"] == 2
    assert preview["file_orfani"] == 1
    assert preview["spazio_stimato_liberato"] > 0

    assert not sources_pending(lesson_dir)
    sel_before = selection(lesson_dir)

    def fake_transcode(in_path, out_path):
        with fs.open(out_path, "wb") as out_f:
            out_f.write(b"M4A_COMPACTED_AUDIO_BYTES")
        return True

    with patch("rt.services.audio_compaction.transcode_audio_for_storage", side_effect=fake_transcode):
        res = compact_audio_lessons([lesson_dir])

    assert res["file_convertiti"] == 2
    assert res["file_orfani_cancellati"] == 1

    # File originali eliminati, file m4a presenti
    assert not fs.isfile(os.path.join(lesson_dir, "sources", "registrazione.wav"))
    assert fs.isfile(os.path.join(lesson_dir, "sources", "registrazione.m4a"))
    assert not fs.isfile(os.path.join(lesson_dir, "sources", "vecchio_rimosso.wav"))
    assert fs.isfile(os.path.join(lesson_dir, "sources", "vecchio_rimosso.m4a"))
    assert not fs.isfile(os.path.join(lesson_dir, "audio-abcdef1234567890abcdef1234567890.m4a"))

    # Verifica fonti e info.yaml
    sources = load_sources(lesson_dir)
    assert len(sources) == 1
    s = sources[0]
    assert s.file == "sources/registrazione.m4a"
    assert s.impronta == compute_file_sha256(os.path.join(lesson_dir, "sources", "registrazione.m4a"))

    from rt.core.state import read_info_yaml
    info = read_info_yaml(os.path.join(lesson_dir, "info.yaml"))
    assert info.get("file_audio") == "sources/registrazione.m4a"

    # sources_pending e selection non cambiano
    assert not sources_pending(lesson_dir)
    sel_after = selection(lesson_dir)
    assert sel_after == sel_before

    # prepare_source_update non deve ritrascrivere
    with patch("rt.pipeline.source_update._transcribe") as mock_transcribe:
        prepare_source_update(lesson_dir, mock=True)
        assert not mock_transcribe.called
    assert not sources_pending(lesson_dir)


def test_compact_audio_failure_retains_original(tmp_path):
    lesson_dir = str(tmp_path / "lezione_fail")
    _setup_mock_lesson(lesson_dir)

    def fail_transcode(in_path, out_path):
        return False

    with patch("rt.services.audio_compaction.transcode_audio_for_storage", side_effect=fail_transcode):
        res = compact_audio_lessons([lesson_dir])

    assert res["file_convertiti"] == 0
    # Originale conservato
    assert fs.isfile(os.path.join(lesson_dir, "sources", "registrazione.wav"))
    sources = load_sources(lesson_dir)
    assert sources[0].file == "sources/registrazione.wav"


def test_compact_audio_api_endpoints(api_client, tmp_path, monkeypatch):
    lesson_dir = str(tmp_path / "lezione_api")
    _setup_mock_lesson(lesson_dir)

    monkeypatch.setattr("rt.services.audio_compaction.all_lessons_list", lambda explicit=None: [lesson_dir])

    # Preview GET
    resp = api_client.get("/api/v1/system/compact-audio/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_convertibili"] == 2
    assert data["file_orfani"] == 1
    assert data["spazio_stimato_liberato"] > 0

    # Start POST
    post_resp = api_client.post("/api/v1/system/compact-audio")
    assert post_resp.status_code == 202
    job_info = post_resp.json()
    assert job_info["type"] == "compact_audio"
    assert job_info["state"] in ("queued", "running", "done")
