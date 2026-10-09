"""Applicazione per unità, ordine del registro e decisioni da riconfermare."""
import pytest
from rt.core.models import Draft, DraftUnit, DecisionLedger, ReviewDecision, ScienceIssue
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import apply_decisions_to_draft, load_ledger, load_resolved_draft, write_ledger_file
from rt.pipeline.review import save_science_issues
from rt.pipeline.rewrite import load_draft, save_draft
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def unit(uid, content):
    return DraftUnit(unit_id=uid, title='Valori', start_segment_id='seg_000001',
                     end_segment_id='seg_000001', source_segment_ids=['seg_000001'], content=content)


def issue(id, uid, anchor, kind='ERR_CONCETTUALE'):
    return ScienceIssue(id=id, unit_id=uid, segment_id='seg_000001', type=kind,
                        severity='low', claim=anchor.quote, reason='Errore', anchor=anchor)


def decision(iss, fix, kind='accepted', timestamp='2026-10-09T10:00:00'):
    return ReviewDecision(issue_id=iss.id, decision=kind, resolved_text=fix, anchor=iss.anchor,
                          timestamp=timestamp)


def test_exact_span_second_occurrence_and_only_issue_unit():
    text = 'Primo: 7.4. Secondo: 7.4 circa.'
    start = text.rindex('7.4')
    iss = issue('sci_000001', '1.1', make_anchor(text, start, start+3))
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(iss, '7.35.')])
    draft = Draft(units=[unit('1.1', text), unit('1.2', text)])
    result = apply_decisions_to_draft(draft, ledger, [iss])
    assert result.units[0].content == 'Primo: 7.4. Secondo: 7.35. circa.'
    assert result.units[1].content == text
    assert draft.units[0].content == text


def test_decisions_follow_registry_order():
    text = 'Il valore è errato.'
    first = issue('sci_000001', '1.1', make_anchor(text, 12, 18))
    after = 'Il valore è intermedio.'
    second = issue('sci_000002', '1.1', make_anchor(after, 12, 22))
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(first, 'intermedio'), decision(second, 'corretto')])
    result = apply_decisions_to_draft(Draft(units=[unit('1.1', text)]), ledger, [first, second])
    assert result.units[0].content == 'Il valore è corretto.'


def test_paragraph_edit_follows_earlier_decision():
    text = 'Il valore è errato.'
    first = issue('sci_000001', '1.1', make_anchor(text, 12, 18))
    paragraph = issue('sci_000002', '1.1', make_anchor(text, 0, len(text)), 'ERR_ASR_LLM')
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(first, 'corretto'), decision(paragraph, 'Nuovo paragrafo.', 'edited')])
    result = apply_decisions_to_draft(Draft(units=[unit('1.1', text)]), ledger, [first, paragraph])
    assert result.units[0].content == 'Nuovo paragrafo.'


def test_manual_edit_skips_only_older_decisions():
    text = 'Il valore è errato.'
    iss = issue('sci_000001', '1.1', make_anchor(text, 12, 18))
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(iss, 'corretto')])
    draft = Draft(units=[unit('1.1', text)])
    assert apply_decisions_to_draft(draft, ledger, [iss], {'1.1':'2026-10-09T10:01:00'}).units[0].content == text
    assert apply_decisions_to_draft(draft, ledger, [iss], {'1.1':'2026-10-09T09:59:00'}).units[0].content == 'Il valore è corretto.'


def test_moved_partially_rewritten_and_disappeared():
    text = 'Prima. Il pH normale del sangue è 7.4 e resta stabile. Dopo.'
    start, end = 7, text.index('. Dopo.')
    iss = issue('sci_000001', '1.1', make_anchor(text, start, end))
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(iss, 'Testo corretto')])
    updated = 'Introduzione. '+text.replace('normale', 'medio')
    result = apply_decisions_to_draft(Draft(units=[unit('1.1', updated)]), ledger, [iss])
    assert result.units[0].content == 'Introduzione. Prima. Testo corretto. Dopo.'
    gone = 'Prima. Un testo completamente diverso. Dopo.'
    assert apply_decisions_to_draft(Draft(units=[unit('1.1', gone)]), ledger, [iss]).units[0].content == gone
    assert ledger.decisions[0].resolved_text == 'Testo corretto'


def test_new_literal_fix_is_not_sanitized():
    text = 'Il valore è errato.'
    iss = issue('sci_000001', '1.1', make_anchor(text, 12, 18))
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(iss, 'Verificare il dato')])
    assert apply_decisions_to_draft(Draft(units=[unit('1.1', text)]), ledger, [iss]).units[0].content == 'Il valore è Verificare il dato.'


@pytest.mark.parametrize('gone_unit', [False, True])
def test_api_exposes_reconfirmation_without_deleting_decisions(tmp_path, monkeypatch, api_client, gone_unit):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = _synthetic_lesson(root)
    draft = load_draft(lesson)
    original = draft.units[0]
    iss = issue('sci_000001', original.unit_id, make_anchor(original.content, 0, len(original.content)))
    save_science_issues([iss], lesson)
    write_ledger_file(DecisionLedger(schema_version='2.0', decisions=[decision(iss, 'Correzione')]), lesson)
    if gone_unit:
        draft.units = draft.units[1:]
    else:
        original.content = 'Una riscrittura completamente diversa.'
    save_draft(draft, lesson)
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    payload = api_client.get(f'/api/v1/lessons/{lesson_id}/issues').json()
    assert payload['pending'] == 1 and payload['review_complete'] is False
    assert payload['items'][0]['needs_reconfirmation'] is True
    assert payload['items'][0]['decision']['decision'] == 'accepted'
    assert [d.issue_id for d in load_ledger(lesson).decisions] == [iss.id]
    # Lo stato è calcolato: se il tratto torna, la stessa decisione torna applicabile.
    if gone_unit:
        draft.units.insert(0, unit(iss.unit_id, iss.anchor.quote))
    else:
        original.content = iss.anchor.quote
    save_draft(draft, lesson)
    payload = api_client.get(f'/api/v1/lessons/{lesson_id}/issues?status=all').json()
    assert payload['pending'] == 0 and payload['review_complete'] is True
    assert payload['items'][0]['needs_reconfirmation'] is False
    assert load_resolved_draft(lesson).units[0].content == 'Correzione'


def test_unanchored_finding_can_be_rejected():
    from rt.pipeline.ledger import apply_decisions_to_draft
    iss = ScienceIssue(id='sci_000001', unit_id='1.1', type='ERR_CONCETTUALE',
                        severity='low', claim='Citazione non ritrovata', reason='Errore')
    ledger = DecisionLedger(schema_version='2.0', decisions=[ReviewDecision(issue_id=iss.id, decision='rejected')])
    missing = set()
    result = apply_decisions_to_draft(Draft(units=[unit('1.1', 'Testo della lezione.')]),
                                     ledger, [iss], missing_decisions=missing)
    assert result.units[0].content == 'Testo della lezione.'
    assert missing == set()


def test_rejecting_a_disappeared_quote_closes_it_in_an_existing_unit():
    iss = issue('sci_000001', '1.1', make_anchor('Testo precedente.', 0, 17))
    ledger = DecisionLedger(schema_version='2.0', decisions=[decision(iss, None, 'rejected')])
    missing = set()
    apply_decisions_to_draft(Draft(units=[unit('1.1', 'Testo completamente diverso.')]),
                             ledger, [iss], missing_decisions=missing)
    assert missing == set()
