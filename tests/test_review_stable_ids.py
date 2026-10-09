"""V5–V7: verifiche ripetute senza perdere id e decisioni."""
import pytest
from rt.core.idempotency import check_phase_status, PhaseStatus
from rt.core.models import ScienceIssue, ScienceType, ScienceSeverity
from rt.pipeline import review
from rt.pipeline.ledger import load_ledger, record_decision
from tests.test_document_edit import _synthetic_lesson
from tests.api_support import isolated_workspace


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    calls = []
    def critic(client, unit, *args, **kwargs):
        calls.append(unit.unit_id)
        return [ScienceIssue(id='unused', unit_id=unit.unit_id, type=ScienceType.ERR_CONCETTUALE,
                             severity=ScienceSeverity.LOW, claim=unit.content, reason='Errore', suggested_fix='Testo corretto.')]
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    review.run_review(lesson, force=True, force_mock=True)
    return lesson, calls


def decide_all(lesson):
    for issue in review.load_science_issues(lesson):
        record_decision(lesson, issue.id, 'rejected')
    return {i.unit_id:i.id for i in review.load_science_issues(lesson)}


def test_single_review_keeps_valid_phase_and_completion_keeps_decisions(reviewed):
    lesson, calls = reviewed
    ids = decide_all(lesson)
    review.run_review_unit(lesson, '1.1', force_mock=True)
    assert check_phase_status(lesson, 'review')[0] == PhaseStatus.VALID
    calls.clear()
    review.run_review(lesson, force_mock=True)
    assert calls == []
    assert {i.unit_id:i.id for i in review.load_science_issues(lesson)} == ids
    assert {d.issue_id for d in load_ledger(lesson).decisions} == set(ids.values())


def test_force_keeps_found_ids_and_decisions(reviewed):
    lesson, calls = reviewed
    ids = decide_all(lesson)
    review.run_review(lesson, force=True, force_mock=True)
    assert calls == ['1.1','1.2','2.1'] * 2
    assert {i.unit_id:i.id for i in review.load_science_issues(lesson)} == ids
    assert {d.issue_id for d in load_ledger(lesson).decisions} == set(ids.values())


def test_new_issue_never_reuses_a_ledger_id(reviewed, monkeypatch):
    lesson, _ = reviewed
    record_decision(lesson, 'sci_900000', 'rejected')
    def critic(client, unit, *args, **kwargs):
        return [ScienceIssue(id='unused', unit_id=unit.unit_id, type=ScienceType.ERR_CONCETTUALE,
                             severity=ScienceSeverity.LOW, claim='Nuova issue', reason='Errore')]
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    review.run_review_unit(lesson, '1.1', force_mock=True)
    ids = {i.id for i in review.load_science_issues(lesson) if i.unit_id == '1.1'}
    assert ids == {'sci_900001'}
    assert [i.unit_id for i in review.load_science_issues(lesson)] == ['1.1','1.2','2.1']
