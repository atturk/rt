"""Studio e menu contestuale della lezione (RT 4.2): unità dello Studio, domande generate su una
parte, Verifica di una parte con l'unità madre come contesto, Genera dall'editor con il regista."""
import pytest

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker


@pytest.fixture
def ready(tmp_path, monkeypatch, rt_db, api_client):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = make_lesson(root)
    assert not run_mock_pipeline(path).error
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    return path, lid, Worker(DbJobQueue(rt_db), worker_id="study-test", mock=True)


def _drain(worker):
    while worker.run_once() is not None:
        pass


def _job(api_client, accepted):
    return api_client.get(f"/api/v1/jobs/{accepted['job_id']}").json()


def test_study_units_have_text_audio_span_and_pending_questions(api_client, ready):
    path, lid, worker = ready
    study = api_client.get(f"/api/v1/lessons/{lid}/study").json()
    assert study["ready"] and study["id"] == lid
    units = study["units"]
    from rt.pipeline.ledger import load_resolved_draft
    assert [u["id"] for u in units] == [u.unit_id for u in load_resolved_draft(path).units]
    first = units[0]
    assert first["html"].startswith("<") and first["title"]
    assert first["start"] is not None and first["end"] is not None and first["end"] >= first["start"]
    assert all(u["questions"] == sum(u["pending"].values()) for u in units)

    accepted = api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={"qtype": "quiz", "mock": True}).json()
    _drain(worker)
    assert _job(api_client, accepted)["state"] == "succeeded"
    units = api_client.get(f"/api/v1/lessons/{lid}/study").json()["units"]
    with_questions = [u for u in units if u["pending"].get("quiz")]
    assert with_questions
    # Lo stesso conteggio di POST /recall/next?unit_id=: tante domande quante ne dichiara l'unità.
    unit = with_questions[0]
    asked = []
    while True:
        r = api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "mista", "unit_id": unit["id"]})
        if r.status_code == 404:
            break
        assert unit["id"] in r.json()["unit_ids"]
        asked.append(r.json()["id"])
        api_client.post(f"/api/v1/lessons/{lid}/recall/answer", json={"question_id": asked[-1], "choice": 0})
    assert len(asked) == unit["questions"]


def test_questions_generated_only_for_the_requested_part(api_client, ready):
    path, lid, worker = ready
    units = api_client.get(f"/api/v1/lessons/{lid}/study").json()["units"]
    target = units[-1]["id"]
    bad = api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={"unit_ids": ["99.9"], "mock": True})
    assert bad.status_code == 422
    accepted = api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={"unit_ids": [target], "mock": True})
    assert accepted.status_code == 202
    _drain(worker)
    assert _job(api_client, accepted.json())["state"] == "succeeded"
    from rt.pipeline.recall import load_recall_bank
    questions = load_recall_bank(path).questions
    assert questions and all(q.unit_ids == [target] for q in questions)
    assert {q.type.value for q in questions} <= {"quiz", "mirata"}


def test_parent_unit_context_is_the_other_subunits_of_the_same_unit():
    from types import SimpleNamespace as U
    from rt.pipeline.review import parent_unit_context
    units = [U(unit_id="1.1", title="Uno", content="a"), U(unit_id="2.1", title="Sistole", content="b"),
             U(unit_id="2.2", title="Diastole", content="c"), U(unit_id="2.3", title="Curva", content="d")]
    assert parent_unit_context(units, "2.2") == "2.1 Sistole\nb\n\n2.3 Curva\nd"
    assert parent_unit_context(units, "1.1") is None


def test_review_of_a_part_asks_for_the_parent_unit_as_context(api_client, ready, monkeypatch):
    path, lid, worker = ready
    from rt.pipeline import review
    unit = review.load_draft(path).units[0].unit_id
    seen = []
    original = review.run_review_unit

    def spy(lesson_dir, unit_id, force_mock=False, parent_context=False, force=False):
        seen.append((unit_id, parent_context))
        return original(lesson_dir, unit_id, force_mock=force_mock, parent_context=parent_context, force=force)
    monkeypatch.setattr(review, "run_review_unit", spy)
    accepted = api_client.post(f"/api/v1/lessons/{lid}/jobs", json={
        "type": "run_phase", "phase": "review", "units": [unit], "parent_context": True, "mock": True}).json()
    _drain(worker)
    assert _job(api_client, accepted)["state"] == "succeeded"
    # Senza la richiesta il revisore vede solo la subunità, come prima.
    api_client.post(f"/api/v1/lessons/{lid}/jobs", json={"type": "run_phase", "phase": "review", "units": [unit], "mock": True})
    _drain(worker)
    assert seen == [(unit, True), (unit, False)]
    from rt.llm.prompts import build_science_review_user_prompt
    assert "CONTESTO" in build_science_review_user_prompt("1.1", "testo", parent_context="2.1 altro")
    assert "CONTESTO" not in build_science_review_user_prompt("1.1", "testo")


def test_generate_from_the_editor_writes_and_saves_the_prompt(api_client, ready, monkeypatch):
    path, lid, worker = ready
    from rt.services import enrichment_service as service
    rows = service.units(path)
    macro = rows[0]["macro_id"]
    touched = [u["id"] for u in rows if u["macro_id"] == macro]
    base = f"/api/v1/lessons/{lid}/enrichment"
    assert api_client.post(base + "/generate", json={"request": "  ", "unit_ids": touched}).status_code == 422
    assert api_client.post(base + "/generate", json={"request": "Un grafico", "unit_ids": ["99.9"]}).status_code == 422
    accepted = api_client.post(base + "/generate", json={
        "kind": "image", "request": "Il cuore in sezione", "selection": "testo scelto", "unit_ids": touched, "mock": True})
    assert accepted.status_code == 202, accepted.text
    element = api_client.get(base).json()["elements"][0]
    assert element["kind"] == "image" and element["unit_id"] == touched[-1] and element["status"] == "queued"
    assert element["request"] == "Il cuore in sezione" and element["context_unit_ids"] == touched
    # Il regista riceve richiesta, selezione e tutta l'unità madre.
    text = service.request_context(path, service.get_element(service.load(path), element["id"]))
    assert "Il cuore in sezione" in text and "testo scelto" in text
    assert all(f"Subunità {u['id']}" in text for u in rows if u["macro_id"] == macro)
    _drain(worker)
    assert _job(api_client, accepted.json())["state"] == "succeeded"
    done = api_client.get(base).json()["elements"][0]
    assert done["status"] == "ready" and done["asset_image"] and done["mode"] == "static"
    assert done["prompt"] == "Rappresenta fedelmente: Il cuore in sezione"
    # Rigenera riusa il prompt salvato (niente regista).
    again = api_client.post(base + "/generate", json={"element_id": done["id"], "mock": True}).json()
    from rt.api.jobs import queue
    assert "write" not in queue().get(again["job_id"]).payload
    _drain(worker)
    assert api_client.get(base).json()["elements"][0]["prompt"] == done["prompt"]


@pytest.mark.parametrize('qtype', ['mista', 'quiz', 'mirata'])
@pytest.mark.parametrize('explicit', [False, True])
def test_next_returns_remaining_with_same_filters(api_client, ready, qtype, explicit, monkeypatch):
    from rt.services import recall_service, study_progress_service
    from rt.api.routers import recall as router
    monkeypatch.setattr(router, '_refill_later', lambda *args: None)
    path, lid, _worker = ready
    recall_service.generate_pool(path, force_mock=True)
    uid = api_client.get(f'/api/v1/lessons/{lid}/study').json()['units'][0]['id']
    study_progress_service.set_status(lid, path, uid, 'ignorata' if explicit else 'da-imparare')
    params = {'qtype': qtype, **({'unit_id': uid} if explicit else {})}
    count = recall_service.pending_count(path, qtype, unit_id=uid if explicit else None)
    assert count > 0
    for remaining in range(count - 1, -1, -1):
        response = api_client.post(f'/api/v1/lessons/{lid}/recall/next', params=params)
        assert response.status_code == 200
        assert response.json()['remaining'] == remaining
        if explicit:
            assert uid in response.json()['unit_ids']
    assert api_client.post(f'/api/v1/lessons/{lid}/recall/next', params=params).status_code == 404


def test_study_suggested_qtype_and_recommended_job(api_client, ready, monkeypatch):
    from rt.core.config import RTConfig, JevConfig
    from rt.services import question_types, section_labels
    path, lid, worker = ready
    cfg = RTConfig(jev=JevConfig(relevance_mode="shadow", relevance_model="typesafe/jev-1.13"))
    monkeypatch.setattr(question_types, "load_config", lambda: cfg)
    monkeypatch.setattr(section_labels, "load_config", lambda: cfg)
    question_types.refresh(path, force_mock=True)
    response = api_client.get(f"/api/v1/lessons/{lid}/study").json()
    assert response["suggestions"] is True
    assert response["units"][0]["suggested_qtype"] in ("quiz", "mirata")
    for unit_ids in (None, [response["units"][0]["id"]]):
        accepted = api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={
            "qtype": "consigliato", "count": 2, "unit_ids": unit_ids, "mock": True,
        })
        assert accepted.status_code == 202
        _drain(worker)
        job = _job(api_client, accepted.json())
        assert job["type"] == "recall_generate" and job["state"] == "succeeded"
    monkeypatch.setattr(question_types, "load_config", RTConfig)
    response = api_client.get(f"/api/v1/lessons/{lid}/study").json()
    assert response["suggestions"] is False and response["units"][0]["suggested_qtype"] is None
