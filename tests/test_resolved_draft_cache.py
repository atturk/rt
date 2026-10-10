"""V3a: una sola applicazione dopo la decisione, invalidazione e copie difensive."""
import pytest
from rt.core.models import DecisionLedger
from rt.pipeline import ledger, review
from rt.pipeline.anchors import make_anchor
from rt.pipeline.rewrite import load_draft, save_draft
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson
from tests.test_review_anchor_application import issue


@pytest.mark.parametrize('database', [False, True])
def test_decision_and_four_reads_apply_ledger_once(tmp_path, monkeypatch, request, database):
    if database:
        request.getfixturevalue('rt_db')
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': 'Testo errato.'})
    old = issue('sci_000001', '1.1', make_anchor('Testo errato.', 6, 12))
    review.save_science_issues([old], lesson)
    ledger.write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    ledger.load_resolved_draft(lesson)
    calls = []
    original = ledger.apply_decisions_to_draft
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(ledger, 'apply_decisions_to_draft', counted)
    ledger.record_decision(lesson, old.id, 'accepted', 'corretto')
    for _ in range(4):
        assert ledger.load_resolved_draft(lesson).units[0].content == 'Testo corretto.'
    assert len(calls) == 1
    # Modificare un oggetto letto non contamina la lettura successiva.
    leaked = ledger.load_resolved_draft(lesson)
    leaked.units[0].content = 'Mutato dal chiamante'
    assert ledger.load_resolved_draft(lesson).units[0].content == 'Testo corretto.'
    assert len(calls) == 1
    assert ledger.revert_last_decision(lesson, old.id)
    assert ledger.load_resolved_draft(lesson).units[0].content == 'Testo errato.'
    assert len(calls) == 2


def test_cache_invalidated_by_draft_issues_manual_edits_and_external_ledger(tmp_path, monkeypatch):
    import json
    from rt.core.lesson_paths import lesson_path
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {'1.1': 'Testo errato.'})
    old = issue('sci_000001', '1.1', make_anchor('Testo errato.', 6, 12))
    review.save_science_issues([old], lesson)
    ledger.write_ledger_file(DecisionLedger(schema_version='2.0'), lesson)
    calls = []
    original = ledger.apply_decisions_to_draft
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(ledger, 'apply_decisions_to_draft', counted)
    assert ledger.load_resolved_draft(lesson).units[0].content == 'Testo errato.'
    draft = load_draft(lesson)
    draft.units[0].content = 'Testo cambiato.'
    save_draft(draft, lesson)
    assert ledger.load_resolved_draft(lesson).units[0].content == 'Testo cambiato.'
    review.save_science_issues([], lesson)
    ledger.load_resolved_draft(lesson)
    with open(lesson_path(lesson, 'document_edits.json'), 'w') as file:
        json.dump({'schema_version': '1.0', 'units': {}}, file)
    ledger.load_resolved_draft(lesson)
    # Scrittura esterna: anche il fallback senza DB segue mtime e dimensione.
    with open(ledger.get_ledger_path(lesson), 'w') as file:
        file.write(DecisionLedger(schema_version='2.0', decisions=[]).model_dump_json(indent=4))
    ledger.load_resolved_draft(lesson)
    assert len(calls) == 5


def test_db_version_grows_on_append_and_undo(tmp_path, monkeypatch, rt_db):
    from rt.db.ledger_store import ledger_version
    lesson = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    before = ledger_version(lesson)
    ledger.record_decision(lesson, 'test', 'rejected')
    after = ledger_version(lesson)
    assert after > before
    assert ledger.revert_last_decision(lesson, 'test')
    assert ledger_version(lesson) > after
