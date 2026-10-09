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
    review.run_review_unit(lesson, '1.1', force_mock=True, force=True)
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
    review.run_review_unit(lesson, '1.1', force_mock=True, force=True)
    ids = {i.id for i in review.load_science_issues(lesson) if i.unit_id == '1.1'}
    assert ids == {'sci_900001'}
    assert [i.unit_id for i in review.load_science_issues(lesson)] == ['1.1','1.2','2.1']


def test_pipeline_change_reviews_only_changed_unit(reviewed):
    from rt.pipeline.rewrite import load_draft, save_draft
    lesson, calls = reviewed
    ids = decide_all(lesson)
    draft = load_draft(lesson)
    draft.units[0].content += ' Testo riscritto dalla pipeline.'
    save_draft(draft, lesson)
    calls.clear()
    review.run_review(lesson, force_mock=True)
    assert calls == ['1.1']
    assert set(ids.values()) - {ids['1.1']} <= {d.issue_id for d in load_ledger(lesson).decisions}


def test_single_review_skips_current_text_unless_forced(reviewed):
    lesson, calls = reviewed
    calls.clear()
    result = review.run_review_unit(lesson, '1.1', force_mock=True)
    assert result['status'] == 'skipped' and result['reason'] == 'già verificata'
    assert calls == []
    result = review.run_review_unit(lesson, '1.1', force_mock=True, force=True)
    assert calls == ['1.1'] and result['issues'] == 1


def test_manual_change_is_skipped_but_later_pipeline_rewrite_is_reviewed(reviewed):
    from tests.test_document_edit import _preview
    from rt.services.document_edit_service import save_document_edit
    from rt.pipeline.rewrite import load_draft, save_draft
    lesson, calls = reviewed
    save_document_edit(lesson, _preview(lesson).replace("Testo dell'unità 1.1.", 'Testo corretto a mano.'))
    calls.clear()
    review.run_review(lesson, force_mock=True)
    assert calls == []
    draft = load_draft(lesson)
    draft.units[0].content = 'Nuova rielaborazione della pipeline.'
    save_draft(draft, lesson)
    calls.clear()
    review.run_review(lesson, force_mock=True)
    assert calls == ['1.1']


@pytest.mark.parametrize('manual', [False, True])
def test_skipped_review_state_comes_from_ledger(reviewed, manual):
    from tests.test_document_edit import _preview
    from rt.services.document_edit_service import save_document_edit
    from rt.core.state import WorkflowState
    lesson, _ = reviewed
    decide_all(lesson)
    if manual:
        save_document_edit(lesson, _preview(lesson).replace("Testo dell'unità 1.1.", 'Testo corretto a mano.'))
    result = review.run_review(lesson, force_mock=True)
    assert result['action'] == 'SKIP'
    assert result['next_state'] == WorkflowState.READY_TO_BUILD.value


def test_legacy_decision_not_applied_has_a_build_warning(reviewed):
    from rt.services.review_service import build_warnings
    lesson, _ = reviewed
    first = review.load_science_issues(lesson)[0]
    record_decision(lesson, first.id, 'accepted', 'Precisare che il contenuto va corretto')
    warnings = build_warnings(lesson)
    assert any(w['code'] == 'decision_not_applied' and w['count'] == 1 for w in warnings)


def test_issues_of_units_gone_from_the_draft_are_dropped(reviewed):
    """Scaletta rifatta: le issue (e le decisioni) di un'unità che non c'è più non restano nel file."""
    from rt.pipeline.rewrite import load_draft, save_draft
    lesson, calls = reviewed
    ids = decide_all(lesson)
    draft = load_draft(lesson)
    draft.units = [u for u in draft.units if u.unit_id != '2.1']
    save_draft(draft, lesson)
    calls.clear()
    review.run_review(lesson, force_mock=True)
    assert calls == []
    assert {i.unit_id for i in review.load_science_issues(lesson)} == {'1.1', '1.2'}
    assert {d.issue_id for d in load_ledger(lesson).decisions} == {ids['1.1'], ids['1.2']}
