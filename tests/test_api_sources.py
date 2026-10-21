import os
import pytest

from rt.core.lesson_paths import lesson_path
from rt.pipeline.rewrite import load_draft
from rt.services.jobs import DbJobQueue, job_needs_stt
from rt.services.worker import Worker
from tests.api_support import isolated_workspace, make_lesson, add_audio, run_mock_pipeline


@pytest.fixture
def source_lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = make_lesson(root)
    add_audio(lesson)
    assert run_mock_pipeline(lesson, with_review=False).status.value == "completed"
    return lesson


def lesson_id(client):
    return client.get("/api/v1/lessons").json()[0]["id"]


def test_sources_api_is_explicit_and_job_can_be_undone(api_client, source_lesson, rt_db):
    lid = lesson_id(api_client)
    url = f"/api/v1/lessons/{lid}"
    old_draft = load_draft(source_lesson)
    from rt.core.models import ScienceIssue
    from rt.pipeline.review import save_science_issues
    from rt.pipeline.ledger import record_decision, load_ledger
    from rt.services.study_notes_service import add_study_note, list_study_notes
    from rt.pipeline.anchors import make_anchor
    from rt.core.segments import load_segments_json
    old_segments = load_segments_json(lesson_path(source_lesson, "segments.json")).segments
    unit = old_draft.units[0]
    save_science_issues([ScienceIssue(id="existing-risk", type="ERR_ASR_ST", severity="low",
                                     unit_id=unit.unit_id, segment_id=old_segments[0].id,
                                     claim=unit.content, reason="already checked")], source_lesson)
    record_decision(source_lesson, "existing-risk", "rejected")
    ledger = load_ledger(source_lesson)
    note = add_study_note(lid, unit.unit_id, "chiedi", make_anchor(unit.content, 0, 10).model_dump(),
                          request="Explain this", response={"answer": "Existing study note"})
    original_bytes = open(lesson_path(source_lesson, "segments.json"), "rb").read()
    view = api_client.get(url + "/sources").json()
    assert len(view["sources"]) == 1 and not view["has_unused_sources"]
    response = api_client.post(url + "/sources", data={"tipo": "appunti", "testo": "Nuovi appunti", "ordine": 1})
    assert response.status_code == 201
    assert open(lesson_path(source_lesson, "segments.json"), "rb").read() == original_bytes
    assert api_client.get(url + "/sources").json()["has_unused_sources"]
    job = api_client.post(url + "/update", json={"mode": "extend", "mock": True})
    assert job.status_code == 202 and job.json()["type"] == "update_lesson"
    assert api_client.post(url + "/sources", data={"tipo": "appunti", "testo": "Busy"}).status_code == 409
    worker = Worker(DbJobQueue(rt_db), job_types=["update_lesson"], on_message=lambda *_: None)
    done = worker.run_once()
    assert done.state == "succeeded", done.error
    new_draft = load_draft(source_lesson)
    assert len(new_draft.units) == len(old_draft.units) + 1
    assert next(u for u in new_draft.units if u.unit_id == old_draft.units[0].unit_id) == old_draft.units[0]
    by_id = {s.id: s for s in load_segments_json(lesson_path(source_lesson, "segments.json")).segments}
    assert all(by_id[s.id].text_raw == s.text_raw for s in old_segments)
    assert load_ledger(source_lesson) == ledger
    assert list_study_notes(lid) == [note]
    assert api_client.get(url + "/sources").json()["can_undo"]
    assert api_client.post(url + "/update/undo").status_code == 200
    assert load_draft(source_lesson) == old_draft
    assert open(lesson_path(source_lesson, "segments.json"), "rb").read() == original_bytes
    assert api_client.post(url + "/update/undo").status_code == 409


def test_sources_reject_invalid_payload_and_remove_without_changing_draft(api_client, source_lesson):
    lid = lesson_id(api_client)
    url = f"/api/v1/lessons/{lid}"
    for data in ({"tipo": "materiale", "testo": "later"}, {"tipo": "appunti", "testo": " "},
                 {"tipo": "appunti", "testo": "notes", "ordine": 99}):
        assert api_client.post(url + "/sources", data=data).status_code == 422
    assert api_client.post(url + "/sources", data={"tipo": "audio"}, files={"file": ("unsafe.txt", b"x")}).status_code == 415
    old = load_draft(source_lesson)
    source = api_client.post(url + "/sources", data={"tipo": "appunti", "testo": "notes"}).json()
    assert api_client.delete(url + "/sources/" + source["id"]).status_code == 204
    assert load_draft(source_lesson) == old
    assert api_client.delete(url + "/sources/missing").status_code == 404


def test_update_jobs_require_stt_only_for_untranscribed_audio(source_lesson):
    from rt.core.sources import add_source
    assert not job_needs_stt("update_lesson", {}, source_lesson)
    add_source(source_lesson, "audio", "part.wav", b"audio")
    assert job_needs_stt("update_lesson", {}, source_lesson)
    assert not job_needs_stt("update_lesson", {"mock": True}, source_lesson)


def test_sources_respect_editor_lease(api_client, source_lesson):
    url = f"/api/v1/lessons/{lesson_id(api_client)}"
    assert api_client.post(url + "/document/lease").status_code == 200
    assert api_client.post(url + "/sources", data={"tipo": "appunti", "testo": "notes"}).status_code == 409
    assert api_client.post(url + "/update", json={}).status_code == 409


def test_audio_upload_preserves_original_and_does_not_start_update(api_client, source_lesson):
    url = f"/api/v1/lessons/{lesson_id(api_client)}"
    from rt.storage import fs
    with fs.open(source_lesson + "/lezione.m4a", "rb") as stream:
        original = stream.read()
    before = load_draft(source_lesson)
    response = api_client.post(url + "/sources", data={"tipo": "audio"}, files={"file": ("lezione.m4a", original, "audio/mp4")})
    assert response.status_code == 201
    assert response.json()["file"] != "lezione.m4a"
    with fs.open(source_lesson + "/lezione.m4a", "rb") as stream:
        assert stream.read() == original
    assert load_draft(source_lesson) == before


def test_audio_upload_is_streamed_with_limit_and_cleaned_up(api_client, source_lesson, monkeypatch):
    import os
    from rt.core.sources import load_sources
    from rt.services.lesson_service import work_dir
    from rt.storage import fs
    url = f"/api/v1/lessons/{lesson_id(api_client)}"
    uploads = os.path.join(work_dir(), "uploads")
    before = len(load_sources(source_lesson))
    monkeypatch.setenv("RT_API_MAX_UPLOAD_MB", str(2048 / (1024 * 1024)))
    response = api_client.post(url + "/sources", data={"tipo": "audio"}, files={"file": ("big.m4a", b"x" * 4096, "audio/mp4")})
    assert response.status_code == 413
    assert len(load_sources(source_lesson)) == before
    assert not os.path.isdir(uploads) or not os.listdir(uploads)
    response = api_client.post(url + "/sources", data={"tipo": "audio"}, files={"file": ("small.m4a", b"y" * 1024, "audio/mp4")})
    assert response.status_code == 201
    with fs.open(os.path.join(source_lesson, response.json()["file"]), "rb") as stream:
        assert stream.read() == b"y" * 1024
    assert not os.listdir(uploads)


def test_undo_is_blocked_by_documents_job_but_sources_are_not(api_client, source_lesson, monkeypatch, rt_db):
    from types import SimpleNamespace
    url = f"/api/v1/lessons/{lesson_id(api_client)}"
    assert api_client.post(url + "/sources", data={"tipo": "appunti", "testo": "notes"}).status_code == 201
    assert api_client.post(url + "/update", json={"mode": "extend", "mock": True}).status_code == 202
    worker = Worker(DbJobQueue(rt_db), job_types=["update_lesson"], on_message=lambda *_: None)
    assert worker.run_once().state == "succeeded"
    with monkeypatch.context() as patch:
        fake = SimpleNamespace(list=lambda **kwargs: [SimpleNamespace(type="documents")])
        patch.setattr("rt.services.source_mutation.get_job_queue", lambda: fake)
        assert api_client.post(url + "/sources", data={"tipo": "appunti", "testo": "more"}).status_code == 201
        response = api_client.post(url + "/update/undo")
        assert response.status_code == 409 and response.json()["error"]["code"] == "lesson_busy"
    assert api_client.post(url + "/update/undo").status_code == 200


def test_remove_and_restore_used_source_api(api_client, source_lesson):
    lid = lesson_id(api_client)
    url = f'/api/v1/lessons/{lid}/sources'
    first = api_client.get(url).json()['sources'][0]
    assert api_client.delete(url + '/' + first['id']).status_code == 204
    view = api_client.get(url).json()
    assert view['sources'] == []
    assert view['fonti_tolte_usate'] == [first['id']]
    assert view['solo_ricostruzione'] and not view['has_unused_sources']
    view = api_client.post(url + '/restore-removed').json()
    assert view['sources'][0]['id'] == first['id']
    assert not view['solo_ricostruzione'] and not view['has_unused_sources']


def test_post_source_multiple_audio_merged_with_parts(api_client, source_lesson, monkeypatch):
    url = f"/api/v1/lessons/{lesson_id(api_client)}"
    monkeypatch.setattr("rt.pipeline.source_update._duration", lambda path: 120.0 if "part1" in path else 60.0)
    monkeypatch.setattr("rt.pipeline.setup.merge_audio_for_transcription",
                        lambda audios, out: open(out, "wb").write(b"fake-merged"))
    files = [
        ("file", ("part1.m4a", b"audio1", "audio/mp4")),
        ("file", ("part2.m4a", b"audio2", "audio/mp4")),
    ]
    response = api_client.post(url + "/sources", data={"tipo": "audio", "unisci": "true"}, files=files)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["tipo"] == "audio"
    assert data["parti"] == [
        {"nome": "part1.m4a", "durata": "2 min", "durata_s": 120.0},
        {"nome": "part2.m4a", "durata": "1 min", "durata_s": 60.0},
    ]
    # Check GET /sources reflects the parts
    view = api_client.get(url + "/sources").json()
    merged = next(s for s in view["sources"] if s["id"] == data["id"])
    assert merged["parti"] == data["parti"]


def test_post_source_multiple_audio_separate_when_unisci_false(api_client, source_lesson):
    url = f"/api/v1/lessons/{lesson_id(api_client)}"
    files = [
        ("file", ("partA.m4a", b"audioA", "audio/mp4")),
        ("file", ("partB.m4a", b"audioB", "audio/mp4")),
    ]
    response = api_client.post(url + "/sources", data={"tipo": "audio", "unisci": "false"}, files=files)
    assert response.status_code == 201, response.text
    data = response.json()
    assert isinstance(data, list) and len(data) == 2
    assert [os.path.basename(s["file"]) for s in data] == ["partA.m4a", "partB.m4a"]
    assert all(s["parti"] is None for s in data)
