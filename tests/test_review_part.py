"""VC2: verifica di una selezione, con lo stesso critic di V4 e merge di V1.5."""
import copy

import pytest

from rt.core.manifest import load_manifest
from rt.core.models import DecisionLedger
from rt.llm.prompts import ReviewFindingList, SCIENCE_REVIEW_SYSTEM_PROMPT
from rt.pipeline import review
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import load_ledger, record_decision, write_ledger_file
from rt.pipeline.review_units import load_review_units
from rt.pipeline.rewrite import load_draft, save_draft
from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson
from tests.test_review_anchor_application import issue
from tests.test_review_stable_ids import reviewed  # noqa: F401


def part(uid, text, quote=None, last=False):
    quote = quote or text
    start = text.rindex(quote) if last else text.index(quote)
    return {'unit_id': uid, 'anchor': make_anchor(text, start, start + len(quote)).model_dump()}


def critic(monkeypatch, quotes):
    calls = []
    def respond(self, **kwargs):
        calls.append(kwargs)
        return ReviewFindingList.model_validate({'issues': [
            {'tipo': 'concettuale', 'gravita': 'bassa', 'citazione': quote,
             'sostituzione': 'Testo corretto.', 'motivazione': 'Errore nel tratto.'}
            for quote in quotes]})
    monkeypatch.setattr(review.LLMClient, 'call_structured', respond)
    return calls


def test_same_v4_prompt_schema_context_and_second_occurrence(tmp_path, monkeypatch):
    text = 'Prima: valore errato. Seconda: valore errato. Fuori: contesto.'
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': text})
    write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    calls = critic(monkeypatch, ['valore errato', 'Fuori: contesto.', 'Citazione inventata'])
    selection = part('1.1', text, 'valore errato', last=True)
    assert review.run_review_part(lesson, selection, force_mock=True)['issues'] == 2
    assert len(calls) == 1
    call = calls[0]
    assert call['response_model'] is ReviewFindingList
    assert call['system_prompt'] == SCIENCE_REVIEW_SYSTEM_PROMPT
    assert call['job_name'] == 'review' and call['lesson_dir'] == lesson
    assert text in call['prompt'] and 'TRATTO DA CONTROLLARE' in call['prompt']
    assert 'BIOCHIMICA' in call['prompt_prefix'] and 'Acidi grassi' in call['prompt_prefix']
    found, unanchored = review.load_science_issues(lesson)
    assert found.origin == unanchored.origin == 'parte'
    assert found.anchor.start == text.rindex('valore errato')
    assert found.anchor.quote == 'valore errato' and not found.unanchored
    assert unanchored.anchor is None and unanchored.unanchored
    assert load_review_units(lesson) == {}  # una parte non verifica l'intera unità
    assert 'review' not in load_manifest(lesson).phase_records


@pytest.mark.parametrize('decision', ['accepted', 'edited', 'rejected'])
def test_keeps_decisions_outside_open_and_other_units(tmp_path, monkeypatch, decision):
    text = 'Prima. Dentro errato. Fuori errato.'
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': text})
    write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    inside = issue('sci_000010', '1.1', make_anchor(text, 7, 20))
    outside = issue('sci_000011', '1.1', make_anchor(text, 21, len(text)))
    decided = issue('sci_000012', '1.1', make_anchor(text, 0, 6))
    other_text = load_draft(lesson).units[1].content
    other = issue('sci_000013', '1.2', make_anchor(other_text, 0, len(other_text)))
    review.save_science_issues([inside, outside, decided, other], lesson)
    record_decision(lesson, decided.id, decision, resolved_text='Prima corretta.')
    before = load_ledger(lesson).model_dump()
    critic(monkeypatch, ['Dentro errato.'])
    assert review.run_review_part(lesson, part('1.1', text, 'Dentro errato.'), True)['issues'] == 1
    rows = review.load_science_issues(lesson)
    assert [i.id for i in rows] == ['sci_000011', 'sci_000012', 'sci_000014', 'sci_000013']
    assert rows[0] == outside and rows[1] == decided and rows[-1] == other
    assert rows[2].origin == 'parte'
    assert load_ledger(lesson).model_dump() == before


def test_refusal_is_inherited_and_checkpoint_does_not_advance(reviewed, monkeypatch):
    lesson, _ = reviewed
    first = review.load_science_issues(lesson)[0]
    record_decision(lesson, first.id, 'rejected')
    before = copy.deepcopy(load_manifest(lesson).phase_records['review'])
    registry = load_review_units(lesson)
    critic(monkeypatch, [first.claim])
    assert review.run_review_part(lesson, part('1.1', first.claim), True)['issues'] == 0
    after = load_manifest(lesson).phase_records['review']
    assert load_review_units(lesson) == registry
    for key in before:
        if key != 'artifact_fingerprints':
            assert after[key] == before[key]
    from rt.core.idempotency import check_phase_status, PhaseStatus
    assert check_phase_status(lesson, 'review')[0] == PhaseStatus.VALID
    assert review.load_science_issues(lesson)[0] == first


def test_selection_moves_but_changed_selection_never_calls_model(tmp_path, monkeypatch):
    text = 'Prima. Il valore è errato. Dopo.'
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': text})
    selection = part('1.1', text, 'Il valore è errato.')
    draft = load_draft(lesson)
    draft.units[0].content = 'Introduzione. ' + text
    save_draft(draft, lesson)
    calls = critic(monkeypatch, ['Il valore è errato.'])
    review.run_review_part(lesson, selection, True)
    assert review.load_science_issues(lesson)[0].anchor.start == 21
    draft.units[0].content = draft.units[0].content.replace('errato', 'esatto')
    save_draft(draft, lesson)
    with pytest.raises(ValueError, match='cambiato'):
        review.run_review_part(lesson, selection, True)
    assert len(calls) == 1


def test_change_during_model_call_does_not_publish_findings(tmp_path, monkeypatch):
    text = 'Prima. Il valore è errato. Dopo.'
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': text})
    def change(self, **kwargs):
        draft = load_draft(lesson)
        draft.units[0].content = text.replace('errato', 'esatto')
        save_draft(draft, lesson)
        return ReviewFindingList(issues=[])
    monkeypatch.setattr(review.LLMClient, 'call_structured', change)
    with pytest.raises(ValueError, match='cambiato'):
        review.run_review_part(lesson, part('1.1', text, 'Il valore è errato.'), True)
    assert review.load_science_issues(lesson) == []


def test_partial_checkpoint_remains_partial(tmp_path, monkeypatch):
    from rt.core.idempotency import check_phase_status, PhaseStatus
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    critic(monkeypatch, ["Testo dell'unità 1.1."])
    review.run_review_unit(lesson, '1.1', force_mock=True, force=True)
    before = copy.deepcopy(load_manifest(lesson).phase_records['review'])
    registry = load_review_units(lesson)
    assert check_phase_status(lesson, 'review')[0] == PhaseStatus.PARTIAL
    unit = load_draft(lesson).units[1]
    critic(monkeypatch, [unit.content])
    review.run_review_part(lesson, part(unit.unit_id, unit.content), True)
    assert check_phase_status(lesson, 'review')[0] == PhaseStatus.PARTIAL
    after = load_manifest(lesson).phase_records['review']
    for key in before:
        if key not in {'artifact_fingerprints', 'issue_sequence'}:
            assert after[key] == before[key]
    assert load_review_units(lesson) == registry


def test_api_and_real_mock_worker_multiple_units(tmp_path, monkeypatch, rt_db, api_client):
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    url = f'/api/v1/lessons/{lesson_id}/jobs'
    parts = [part(u.unit_id, u.content) for u in load_draft(lesson).units[:2]]
    for invalid in ([], [parts[0], parts[0]], [part('1.1', 'Testo assente.')]):
        response = api_client.post(url, json={'type': 'review_part', 'parts': invalid, 'mock': True})
        assert response.status_code == 422, response.text
    assert api_client.post(url, json={'type': 'review_part', 'parts': [part('9.9', 'Assente')]}).status_code == 404
    response = api_client.post(url, json={'type': 'review_part', 'parts': parts, 'mock': True})
    assert response.status_code == 202, response.text
    queue = DbJobQueue(rt_db)
    job_id = response.json()['job_id']
    queued = queue.get(job_id)
    assert queued.type == 'review_part' and queued.payload['units'] == ['1.1', '1.2']
    Worker(queue, worker_id='part-test').run_once()
    done = queue.get(job_id)
    assert done.state == 'succeeded', done.error
    assert [r['unit_id'] for r in done.result['units']] == ['1.1', '1.2']
    assert done.result['issues'] == len(review.load_science_issues(lesson))
    assert all(i.origin == 'parte' for i in review.load_science_issues(lesson))
    events = list(queue.events(job_id))
    assert [e.payload['unit_id'] for e in events if e.type == 'review_unit_done'] == ['1.1', '1.2']
    assert load_review_units(lesson) == {}
