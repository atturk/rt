import os

import pytest

from rt.core.lesson_paths import lesson_path
from rt.core.segments import load_segments_json
from rt.core.sources import add_source
from rt.pipeline.prepare import run_prepare
from rt.pipeline.source_update import run_source_update, sources_pending
from rt.services.notes_lesson_service import create_notes_lesson
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from rt.storage import fs
from tests.api_support import isolated_workspace
from tests.test_source_update import write_audio
from tests.test_stable_segments import segment


@pytest.mark.parametrize("mode", ["extend", "rebuild"])
def test_notes_lesson_pipeline_and_audio_later(tmp_path, monkeypatch, mode):
    lesson = create_notes_lesson("First paragraph\n\nSecond paragraph", date="2026-10-12", materia="Test", dest_dir=str(tmp_path))
    result = run_prepare(lesson)
    assert result["segment_count"] == 2 and result["duration_seconds"] == 0
    originals = load_segments_json(lesson_path(lesson, "segments.json")).segments
    assert all(s.flags == ["appunti"] for s in originals)
    from rt.pipeline.outline import run_outline
    from rt.pipeline.rewrite import run_rewrite
    run_outline(lesson, force_mock=True)
    monkeypatch.setattr("rt.services.classifier.classify_units", lambda *a, **k: None)
    run_rewrite(lesson, force_mock=True)
    audio = tmp_path / "later.wav"
    write_audio(audio)
    add_source(lesson, "audio", "later.wav", audio.read_bytes())
    monkeypatch.setattr("rt.pipeline.source_update._transcribe", lambda *a, **k: [segment(1, "new audio")])
    assert run_source_update(lesson, mock=True, mode=mode)["status"] == "draft_validated"
    updated = load_segments_json(lesson_path(lesson, "segments.json")).segments
    assert [s.id for s in updated[:2]] == [s.id for s in originals]
    assert updated[-1].id == "seg_000003"
    # Un prepare forzato deve conservare gli ID e lasciare pendenti altre fonti.
    add_source(lesson, "appunti", "pending.txt", b"not yet used")
    run_prepare(lesson, force=True)
    assert load_segments_json(lesson_path(lesson, "segments.json")).segments == updated
    assert sources_pending(lesson)


@pytest.mark.parametrize("run", [False, True])
def test_create_notes_via_api_without_audio(api_client, rt_db, tmp_path, monkeypatch, run):
    isolated_workspace(tmp_path, monkeypatch)
    response = api_client.post("/api/v1/lessons", data={"date": "2026-10-12", "materia": "Test",
                               "appunti": "Paragraph one\n\nParagraph two", "run": str(run).lower(), "mock": "true", "auto_accept": "true"})
    assert response.status_code == 202
    assert response.json()["type"] == "ingest_notes"
    worker = Worker(DbJobQueue(rt_db), job_types=["ingest_notes"], on_message=lambda *_: None)
    job = worker.run_once()
    assert job.state == "succeeded", job.error
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    assert not api_client.get(f"/api/v1/lessons/{lid}").json()["has_audio"]
    assert api_client.get(f"/api/v1/lessons/{lid}/sources").json()["sources"][0]["tipo"] == "appunti"
    assert api_client.get(f"/api/v1/lessons/{lid}/audio").status_code == 404
    if run:
        segments = load_segments_json(lesson_path(job.lesson_path, "segments.json"))
        assert len(segments.segments) == 2


def test_notes_creation_rejects_empty_and_duplicate(tmp_path):
    with pytest.raises(ValueError):
        create_notes_lesson(" ", date="2026-10-12", materia="Test", dest_dir=str(tmp_path))
    lesson = create_notes_lesson("original", date="2026-10-12", materia="Test", dest_dir=str(tmp_path))
    with pytest.raises(ValueError):
        create_notes_lesson("replacement", date="2026-10-12", materia="Test", dest_dir=str(tmp_path))
    from rt.core.sources import load_sources
    with fs.open(os.path.join(lesson, load_sources(lesson)[0].file)) as stream:
        assert stream.read() == "original"


def test_notes_import_resumes_same_lesson_after_outline_approval(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    response = api_client.post("/api/v1/lessons", data={"date": "2026-10-12", "materia": "Test",
                               "appunti": "Original notes", "run": "true", "mock": "true"})
    assert response.status_code == 202
    worker = Worker(DbJobQueue(rt_db), job_types=["ingest_notes"], on_message=lambda *_: None)
    waiting = worker.run_once()
    assert waiting.state == "waiting_for_decision"
    from rt.services.outline_service import approve_outline
    approve_outline(waiting.lesson_path)
    completed = worker.run_once()
    assert completed.state == "succeeded", completed.error
    assert completed.lesson_path == waiting.lesson_path
    assert len(api_client.get("/api/v1/lessons").json()) == 1
