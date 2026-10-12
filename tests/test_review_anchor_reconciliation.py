"""La verifica conserva le decisioni e ritrova i rifiuti sullo stesso tratto."""
import pytest
from rt.core.models import Draft, DecisionLedger, ScienceIssue, ReviewDecision
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import load_ledger, write_ledger_file, load_resolved_draft, get_ledger_path
from rt.pipeline import review
from rt.pipeline.rewrite import load_draft
from tests.test_review_anchor_application import unit, issue, decision
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_closed_kept_open_replaced_and_rejection_inherited(tmp_path):
    text = 'Primo errore. Secondo errore. Terzo errore.'
    accepted = issue('sci_000001', '1.1', make_anchor(text, 0, 12))
    edited = issue('sci_000002', '1.1', make_anchor(text, 14, 28))
    rejected = issue('sci_000003', '1.1', make_anchor(text, 30, 42))
    opened = issue('sci_000100', '1.1', make_anchor(text, 0, 12))
    outside = issue('sci_000004', '1.2', make_anchor(text, 0, 12))
    prior = [accepted, edited, rejected, opened, outside]
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(accepted, 'Uno'),
                decision(edited, 'Due', 'edited'), decision(rejected, rejected.claim, 'rejected')])
    write_ledger_file(ledger, str(tmp_path))
    snapshot = open(get_ledger_path(str(tmp_path)), 'rb').read()
    fresh = issue('unused', '1.1', make_anchor(text, 0, 5))
    reformulated = issue('unused', '1.1', make_anchor(text, 36, 42))
    combined, orphaned, sequence = review.merge_unit_findings(str(tmp_path), prior,
                [fresh, reformulated], [unit('1.1', text), unit('1.2', text)], {'1.1'})
    assert orphaned == [] and sequence == 101
    assert {i.id for i in combined} == {'sci_000001', 'sci_000002', 'sci_000003', 'sci_000004', 'sci_000101'}
    assert combined[:3] == [accepted, edited, rejected]
    assert next(i for i in combined if i.id == 'sci_000003').claim == rejected.claim
    assert open(get_ledger_path(str(tmp_path)), 'rb').read() == snapshot


@pytest.mark.parametrize('other_type,other_unit', [('ERR_ASR_LLM', '1.1'), ('ERR_CONCETTUALE', '1.2')])
def test_rejection_is_not_inherited_on_other_type_or_unit(tmp_path, other_type, other_unit):
    text = 'Passaggio identico.'
    old = issue('sci_000001', '1.1', make_anchor(text, 0, len(text)))
    write_ledger_file(DecisionLedger(schema_version='2.0', decisions=[decision(old, text, 'rejected')]), str(tmp_path))
    fresh = issue('unused', other_unit, make_anchor(text, 0, len(text)), other_type)
    combined, _, sequence = review.merge_unit_findings(str(tmp_path), [old], [fresh],
                            [unit('1.1', text), unit('1.2', text)], {other_unit})
    assert len(combined) == 2 and sequence == 2
    assert fresh.id == 'sci_000002'


def test_adjacent_spans_do_not_inherit_rejection(tmp_path):
    text = 'Prima.Seconda.'
    old = issue('sci_000001', '1.1', make_anchor(text, 0, 6))
    write_ledger_file(DecisionLedger(schema_version='2.0', decisions=[decision(old, old.claim, 'rejected')]), str(tmp_path))
    fresh = issue('unused', '1.1', make_anchor(text, 6, len(text)))
    combined, _, _ = review.merge_unit_findings(str(tmp_path), [old], [fresh], [unit('1.1', text)], {'1.1'})
    assert len(combined) == 2


@pytest.mark.parametrize('single_unit', [False, True])
def test_review_reads_resolved_text_and_retains_corrected_issue(tmp_path, monkeypatch, single_unit):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = _synthetic_lesson(root, {'1.1':'Il valore è errato.'})
    original = load_draft(lesson).units[0]
    old = issue('sci_000001', '1.1', make_anchor(original.content, 12, 18))
    review.save_science_issues([old], lesson)
    write_ledger_file(DecisionLedger(schema_version='2.0', decisions=[decision(old, 'corretto')]), lesson)
    seen = []
    def critic(client, current_unit, *args, **kwargs):
        seen.append((current_unit.unit_id, current_unit.content))
        return []
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    if single_unit:
        review.run_review_unit(lesson, '1.1', force_mock=True, force=True)
    else:
        review.run_review(lesson, force_mock=True, force=True)
    assert ('1.1', 'Il valore è corretto.') in seen
    assert {i.id for i in review.load_science_issues(lesson)} == {old.id}
    assert [d.issue_id for d in load_ledger(lesson).decisions] == [old.id]
    assert load_resolved_draft(lesson).units[0].content == 'Il valore è corretto.'


def test_new_finding_anchor_is_on_resolved_text(tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = _synthetic_lesson(root, {'1.1':'Il valore è errato.'})
    original = load_draft(lesson).units[0]
    old = issue('sci_000001', '1.1', make_anchor(original.content, 12, 18))
    review.save_science_issues([old], lesson)
    write_ledger_file(DecisionLedger(schema_version='2.0', decisions=[decision(old, 'corretto')]), lesson)
    def critic(client, current_unit, *args, **kwargs):
        return [ScienceIssue(id='from_model', unit_id='inventata', type='ERR_CONCETTUALE',
                 severity='low', claim='corretto', reason='Altro controllo', suggested_fix='preciso')]
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    review.run_review_unit(lesson, '1.1', force_mock=True, force=True)
    generated = next(i for i in review.load_science_issues(lesson) if i.id != old.id)
    assert generated.unit_id == '1.1' and generated.origin == 'verifica'
    assert generated.anchor.quote == 'corretto'
    assert generated.anchor.start == 12 and generated.anchor.end == 20
    assert [d.issue_id for d in load_ledger(lesson).decisions] == [old.id]


def test_decisions_do_not_trigger_a_new_review_but_a_forced_one_reads_resolved_text(tmp_path, monkeypatch):
    """Una decisione cambia il testo risolto, non la bozza: niente nuova chiamata da sola.
    Quando la verifica riparte (forzata) legge il testo già corretto."""
    from rt.pipeline.ledger import record_decision
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = _synthetic_lesson(root, {'1.1':'Il valore è errato.'})
    seen = []
    def critic(client, current_unit, *args, **kwargs):
        seen.append((current_unit.unit_id, current_unit.content))
        if 'errato' in current_unit.content:
            return [ScienceIssue(id='from_model', type='ERR_CONCETTUALE', severity='low',
                                 claim='errato', reason='Valore', suggested_fix='corretto')]
        return []
    monkeypatch.setattr(review, '_validated_review_issues', critic)
    monkeypatch.setattr(review, 'detect_statistical_asr_risks', lambda **kw: [])
    review.run_review(lesson, force_mock=True, force=True)
    old = review.load_science_issues(lesson)[0]
    record_decision(lesson, old.id, 'accepted', 'corretto')
    seen.clear()
    assert review.run_review(lesson, force_mock=True)['action'] == 'SKIP'
    assert seen == []
    review.run_review(lesson, force_mock=True, force=True)
    assert ('1.1', 'Il valore è corretto.') in seen
    assert [i.id for i in review.load_science_issues(lesson)] == [old.id]


def test_merge_can_preserve_open_findings_outside_a_selected_span(tmp_path):
    text = 'Prima.Seconda.'
    selected = issue('sci_000001', '1.1', make_anchor(text, 0, 6))
    outside = issue('sci_000002', '1.1', make_anchor(text, 6, len(text)))
    write_ledger_file(DecisionLedger(schema_version='2.0'), str(tmp_path))
    combined, _, _ = review.merge_unit_findings(str(tmp_path), [selected, outside], [],
                        [unit('1.1', text)], {'1.1'}, replace_open=lambda finding: finding.anchor.start < 6)
    assert combined == [outside]
