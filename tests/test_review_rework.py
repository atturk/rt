"""Regressioni della verifica 4.2.3.2: decisioni sul testo mostrato all'utente."""
import pytest

from rt.core.models import ScienceIssue, ScienceSeverity, ScienceType
from rt.pipeline.ledger import load_ledger, load_resolved_draft
from rt.pipeline.review import save_science_issues
from rt.services import review_service as rs
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    return _synthetic_lesson(root, {'1.1': "La CO2 si lega all'emoglobina formando carbossiemoglobina nei globuli rossi."})


def issue(id, claim, fix, kind=ScienceType.ERR_CONCETTUALE):
    return ScienceIssue(id=id, unit_id='1.1', segment_id='seg_000001', type=kind,
                        severity=ScienceSeverity.MEDIUM, claim=claim, reason='Errore', suggested_fix=fix)


@pytest.mark.parametrize('decision', ['accepted', 'edited'])
def test_overlapping_claim_is_rejected_without_recording(lesson, decision):
    a = issue('sci_000001', 'formando carbossiemoglobina', 'formando carbaminoemoglobina')
    b = issue('sci_000002', "all'emoglobina formando carbossiemoglobina nei globuli rossi", 'alla globina')
    save_science_issues([a,b], lesson)
    rs.record_review_decision(lesson, a.id, 'accepted', channel='web', validate=True)
    with pytest.raises(rs.ReviewDecisionError) as exc:
        rs.record_review_decision(lesson, b.id, decision, 'alla globina', channel='web', validate=True)
    assert exc.value.reason == 'claim_changed'
    assert [d.issue_id for d in load_ledger(lesson).decisions] == [a.id]


def test_paragraph_edit_starts_from_resolved_text(lesson):
    a = issue('sci_000001', 'formando carbossiemoglobina', 'formando carbaminoemoglobina')
    b = issue('sci_000002', 'Testo ASR', None, ScienceType.ERR_ASR_LLM)
    save_science_issues([a,b], lesson)
    rs.record_review_decision(lesson, a.id, 'accepted', channel='web', validate=True)
    context = rs.issue_context(lesson, b)
    assert 'carbaminoemoglobina' in context['unit_content']
    rs.record_review_decision(lesson, b.id, 'edited', context['unit_content'] + ' Aggiunta corretta.', channel='web', validate=True)
    content = load_resolved_draft(lesson).units[0].content
    assert 'carbaminoemoglobina' in content and 'Aggiunta corretta.' in content
    assert b.id not in rs.orphan_issue_ids(lesson)


def test_paragraph_decisions_apply_before_punctual_ones(lesson):
    from rt.pipeline.ledger import record_decision
    a = issue('sci_000001', 'formando carbossiemoglobina', 'formando carbaminoemoglobina')
    b = issue('sci_000002', 'Testo ASR', None, ScienceType.ERR_ASR_LLM)
    save_science_issues([a,b], lesson)
    record_decision(lesson, a.id, 'accepted', a.suggested_fix)
    record_decision(lesson, b.id, 'edited', "La CO2 si lega all'emoglobina formando carbossiemoglobina. Aggiunta.")
    assert load_resolved_draft(lesson).units[0].content == "La CO2 si lega all'emoglobina formando carbaminoemoglobina. Aggiunta."


def test_api_returns_claim_changed(lesson, api_client):
    a = issue('sci_000001', 'formando carbossiemoglobina', 'formando carbaminoemoglobina')
    b = issue('sci_000002', "all'emoglobina formando carbossiemoglobina nei globuli rossi", 'alla globina')
    save_science_issues([a,b], lesson)
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    assert api_client.post(f'/api/v1/lessons/{lesson_id}/issues/{a.id}/decision', json={'decision':'accepted'}).status_code == 200
    response = api_client.post(f'/api/v1/lessons/{lesson_id}/issues/{b.id}/decision', json={'decision':'accepted'})
    assert response.status_code == 409 and response.json()['error']['code'] == 'claim_changed'


def test_advisory_acceptance_is_rejected(lesson):
    advisory = issue('sci_000001', 'formando carbossiemoglobina', 'Precisare che la CO2 si lega alla globina')
    save_science_issues([advisory], lesson)
    with pytest.raises(rs.ReviewDecisionError, match='È un suggerimento, non una correzione'):
        rs.record_review_decision(lesson, advisory.id, 'accepted', channel='web', validate=True)
    assert not load_ledger(lesson).decisions


def test_auto_accept_leaves_advisory_pending(lesson):
    advisory = issue('sci_000001', 'formando carbossiemoglobina', 'Verificare il nome del composto')
    save_science_issues([advisory], lesson)
    accepted, remaining = rs.auto_accept_pending(lesson, 'all')
    assert accepted == [] and [i.id for i in remaining] == [advisory.id]
    assert not load_ledger(lesson).decisions


def test_api_exposes_literal_fix_text(lesson, api_client):
    a = issue('sci_000001', 'formando carbossiemoglobina', 'Verificare il nome del composto')
    b = issue('sci_000002', 'CO2', 'Sostituire con: "anidride carbonica"')
    save_science_issues([a,b], lesson)
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    items = api_client.get(f'/api/v1/lessons/{lesson_id}/issues').json()['items']
    assert [i['fix_text'] for i in items] == [None, 'anidride carbonica']

def test_paragraph_preserves_correction_containing_original_claim(lesson):
    from rt.pipeline.rewrite import load_draft, save_draft
    draft = load_draft(lesson)
    draft.units[0].content = 'I saturi hanno doppi legami.'
    save_draft(draft, lesson)
    a = issue('sci_000001', 'hanno doppi legami', 'non hanno doppi legami')
    b = issue('sci_000002', 'Testo ASR', None, ScienceType.ERR_ASR_LLM)
    save_science_issues([a, b], lesson)
    rs.record_review_decision(lesson, a.id, 'accepted', channel='web', validate=True)
    context = rs.issue_context(lesson, b)
    rs.record_review_decision(lesson, b.id, 'edited', context['unit_content'] + ' Nota.', channel='web', validate=True)
    assert load_resolved_draft(lesson).units[0].content == 'I saturi non hanno doppi legami. Nota.'


def test_auto_accept_does_not_record_overlapping_corrections(lesson):
    a = issue('sci_000001', 'formando carbossiemoglobina', 'formando carbaminoemoglobina')
    b = issue('sci_000002', "all'emoglobina formando carbossiemoglobina nei globuli rossi", 'alla globina')
    save_science_issues([a,b], lesson)
    accepted, remaining = rs.auto_accept_pending(lesson, 'all')
    assert [i.id for i in accepted] == [a.id]
    assert [i.id for i in remaining] == [b.id]
    assert [d.issue_id for d in load_ledger(lesson).decisions] == [a.id]
