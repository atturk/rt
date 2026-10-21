"""Le issue di unità sparite escono dalla review, conservando la storia."""
from pathlib import Path

import pytest

from rt.core.lesson_paths import lesson_path
from rt.core.models import DecisionLedger
from rt.pipeline import review
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import (
    apply_decisions_to_draft, get_ledger_path, load_ledger, load_resolved_draft,
    reconfirmation_issue_ids, write_ledger_file,
)
from rt.pipeline.rewrite import load_draft
from rt.services import review_service as service
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson
from tests.test_review_anchor_application import decision, issue


@pytest.fixture
def vanished(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = _synthetic_lesson(root)
    text = 'Testo errato.'
    issues = [issue(f'sci_{i:06d}', '7.2', make_anchor(text, 0, len(text)), kind)
              for i, kind in enumerate(['ERR_ASR_ST', 'ERR_REWRITE_DRIFT', 'ERR_CONCETTUALE'], 1)]
    issues[2].suggested_fix = 'Testo corretto.'
    review.save_science_issues(issues, lesson)
    write_ledger_file(DecisionLedger(schema_version='2.0', decisions=[decision(i, 'Testo corretto.') for i in issues]), lesson)
    return lesson, issues


def test_drop_archives_decided_issues_without_changing_ledger(vanished, request):
    lesson, issues = vanished
    snapshot = Path(get_ledger_path(lesson)).read_bytes()
    assert review.drop_vanished_unit_issues(lesson) == 3
    archived = review.load_obsolete_science_issues(lesson)
    assert [i['id'] for i in archived] == [i.id for i in issues]
    assert all(i['obsoleta_il'] for i in archived)
    assert Path(get_ledger_path(lesson)).read_bytes() == snapshot
    api_client = request.getfixturevalue('api_client')
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    response = api_client.get(f'/api/v1/lessons/{lesson_id}/issues?status=all').json()
    assert response['items'] == []
    assert response['review_complete'] is True
    assert service.orphan_issue_ids(lesson) == []
    assert reconfirmation_issue_ids(lesson) == set()
    assert not any(w['code'] in {'orphan_issues', 'decision_not_applied', 'pending_issues'} for w in service.build_warnings(lesson))
    assert api_client.get('/api/v1/lessons').json()[0]['pending_issues'] == 0


def test_first_open_cleans_up_second_open_does_not_write(vanished):
    lesson, _ = vanished
    before = Path(get_ledger_path(lesson)).read_bytes()
    load_resolved_draft(lesson)
    paths = [Path(review.get_science_issues_path(lesson)), Path(lesson_path(lesson, 'science_issues_obsolete.json'))]
    stamps = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    load_resolved_draft(lesson)
    assert stamps == [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    assert review.drop_vanished_unit_issues(lesson) == 0
    assert Path(get_ledger_path(lesson)).read_bytes() == before


def test_force_review_removes_decided_issues(vanished, monkeypatch):
    lesson, issues = vanished
    monkeypatch.setattr(review, '_validated_review_issues', lambda *a, **kw: [])
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    review.run_review(lesson, force=True, force_mock=True)
    assert review.load_science_issues(lesson) == []
    assert {i['id'] for i in review.load_obsolete_science_issues(lesson)} == {i.id for i in issues}
    assert len(load_ledger(lesson).decisions) == 3


def test_existing_units_and_segment_only_issues_are_unchanged(vanished):
    lesson, _ = vanished
    keep = issue('sci_000004', '1.1', make_anchor('Testo.', 0, 6))
    segment_only = keep.model_copy(update={'id': 'sci_000005', 'unit_id': None})
    review.save_science_issues(review.load_science_issues(lesson) + [keep, segment_only], lesson)
    assert review.drop_vanished_unit_issues(lesson) == 3
    assert review.load_science_issues(lesson) == [keep, segment_only]
    later = keep.model_copy(update={'id': 'sci_000006', 'unit_id': '8.1'})
    review.save_science_issues([keep, segment_only, later], lesson)
    assert review.drop_vanished_unit_issues(lesson) == 1
    assert [i['id'] for i in review.load_obsolete_science_issues(lesson)] == ['sci_000001', 'sci_000002', 'sci_000003', 'sci_000006']


@pytest.mark.parametrize('issue_index', [0, 1, 2])
@pytest.mark.parametrize('kind', ['accepted', 'rejected', 'edited'])
@pytest.mark.parametrize('reconfirming', [False, True])
def test_missing_unit_decision_is_final(vanished, kind, reconfirming, issue_index):
    lesson, issues = vanished
    # Simula un'issue già arrivata al pannello mentre cambia la bozza.
    target = issues[issue_index]
    if not reconfirming:
        write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    recorded = service.record_review_decision(lesson, target.id, kind, 'Testo nuovo.', channel='web', validate=reconfirming or kind != 'rejected')
    assert recorded.original_context == ''
    missing = set()
    apply_decisions_to_draft(load_draft(lesson), DecisionLedger(schema_version='2.0', decisions=[recorded]), [target], missing_decisions=missing)
    assert missing == set()


def test_archived_open_ids_are_never_reused(vanished):
    lesson, _ = vanished
    opened = issue('sci_900000', '7.2', make_anchor('Testo.', 0, 6))
    review.save_science_issues([opened], lesson)
    review.drop_vanished_unit_issues(lesson)
    fresh = opened.model_copy(update={'id': 'unused', 'unit_id': '1.1'})
    _, _, sequence = review.merge_unit_findings(lesson, [], [fresh], load_draft(lesson).units, {'1.1'})
    assert sequence == 900001
    assert fresh.id == 'sci_900001'


@pytest.mark.parametrize('target_unit_id', [None, '1.1'])
def test_rewrite_cleans_up_without_opening_review(vanished, target_unit_id):
    from rt.pipeline.rewrite import run_rewrite
    lesson, issues = vanished
    snapshot = Path(get_ledger_path(lesson)).read_bytes()
    run_rewrite(lesson, target_unit_id=target_unit_id, force=True, force_mock=True)
    assert review.load_science_issues(lesson) == []
    assert {i['id'] for i in review.load_obsolete_science_issues(lesson)} == {i.id for i in issues}
    assert Path(get_ledger_path(lesson)).read_bytes() == snapshot


def test_review_manual_edit_skip_still_archives(vanished, monkeypatch):
    from rt.core.idempotency import PhaseStatus
    lesson, issues = vanished
    monkeypatch.setattr(review, 'check_phase_status', lambda *a: (PhaseStatus.STALE, 'manual edit'))
    monkeypatch.setattr(review, '_only_manual_edits', lambda *a: True)
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    result = review.run_review(lesson, force_mock=True)
    assert result['action'] == 'SKIP'
    assert result['total_science_issues'] == 0
    assert {i['id'] for i in review.load_obsolete_science_issues(lesson)} == {i.id for i in issues}
