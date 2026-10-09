"""Testo storico congelato prima di cambiare apply_decisions_to_draft (V1c)."""
import json
import pytest
from rt.core.models import Draft, DraftUnit, DecisionLedger, ReviewDecision, ScienceIssue
from rt.core.lesson_paths import lesson_path
from rt.pipeline.ledger import apply_decisions_to_draft, load_resolved_draft, load_ledger, get_ledger_path
from rt.pipeline.review import load_science_issues, get_science_issues_path
from rt.pipeline.rewrite import save_draft
from rt.pipeline.document_edits import save_document_edits


def historical_lesson(tmp_path):
    (tmp_path / 'info.yaml').write_text("data: '2026-10-09'\nmateria: Test\ntitolo: Migrazione\n")
    contents = {
        '1.1': 'Il pH normale del sangue è 7.4 circa, mantenuto dai tamponi. Altro testo qui.',
        '1.2': 'I saturi hanno doppi legami. Altra frase.',
        '1.3': 'Questo testo è stato rifiutato.',
        '1.4': 'Testo già corretto a mano. Valore nuovo errato.',
        '1.5': 'Il valore richiede una precisazione.',
        '1.6': 'Il composto è sbagliato. Nota iniziale.',
    }
    draft = Draft(units=[DraftUnit(unit_id=uid, title='Unità', start_segment_id=f'seg_{n:06d}',
                     end_segment_id=f'seg_{n:06d}', source_segment_ids=[f'seg_{n:06d}'], content=content)
                     for n, (uid, content) in enumerate(contents.items(), 1)])
    claims = ['Il pH normale del sangue è 7.4 circa', 'hanno doppi legami',
              'Questo testo', 'Testo vecchio', 'errato', 'Il valore', 'sbagliato', 'Testo ASR']
    unit_ids = ['1.1', '1.2', '1.3', '1.4', '1.4', '1.5', '1.6', '1.6']
    issues = [ScienceIssue(id=f'sci_{n:06d}', type='ERR_CONCETTUALE' if n != 8 else 'ERR_ASR_LLM',
                          severity='low', unit_id=uid, claim=claim, reason='Verifica')
              for n, (uid, claim) in enumerate(zip(unit_ids, claims), 1)]
    texts = ['Sostituire con: "Il pH normale del sangue arterioso è 7,35-7,45, mantenuto dai tamponi."',
             'non hanno doppi legami', 'Questo testo', 'Testo già corretto', 'corretto',
             'Precisare che il valore varia', 'corretto', 'Il composto è sbagliato. Nota di paragrafo.']
    decisions = [ReviewDecision(issue_id=issue.id, decision=decision, resolved_text=text,
                  timestamp=f'2026-10-09T10:{n:02d}:00', notes='nota storica')
                 for n, (issue, text, decision) in enumerate(zip(issues, texts,
                  ['accepted', 'edited', 'rejected', 'accepted', 'edited', 'accepted', 'accepted', 'edited']), 1)]
    edits = {'1.4': '2026-10-09T10:04:30'}
    save_draft(draft, str(tmp_path))
    # File realmente storici: niente campi introdotti da V1b.
    path = lesson_path(str(tmp_path), 'science_issues.json')
    with open(path, 'w') as file:
        json.dump([i.model_dump(mode='json', exclude={'anchor', 'origin'}) for i in issues], file)
    ledger = DecisionLedger(decisions=decisions)
    path = lesson_path(str(tmp_path), 'review_decisions.json')
    with open(path, 'w') as file:
        json.dump({'schema_version':'1.0', 'decisions':[d.model_dump(mode='json', exclude={'anchor'}) for d in decisions]}, file)
    save_document_edits(str(tmp_path), {'units':{'1.4':{'edited':True, 'edited_at':edits['1.4']}}})
    return draft, ledger, issues, edits


EXPECTED = [
    'Il pH normale del sangue arterioso è 7,35-7,45, mantenuto dai tamponi. Altro testo qui.',
    'I saturi non hanno doppi legami. Altra frase.',
    'Questo testo è stato rifiutato.',
    'Testo già corretto a mano. Valore nuovo corretto.',
    'Il valore richiede una precisazione.',
    'Il composto è corretto. Nota di paragrafo.',
]


@pytest.mark.parametrize("database", [False, True])
def test_historical_resolved_text_before_and_after_first_read(tmp_path, request, monkeypatch, database):
    if database:
        request.getfixturevalue("rt_db")
    def forbidden(*args, **kwargs):
        raise AssertionError("La migrazione non deve chiamare il modello")
    monkeypatch.setattr("rt.llm.client.LLMClient.call_structured", forbidden)
    draft, ledger, issues, edits = historical_lesson(tmp_path)
    before = [u.content for u in apply_decisions_to_draft(draft, ledger, issues, edits).units]
    assert before == EXPECTED
    after = [u.content for u in load_resolved_draft(str(tmp_path)).units]
    assert after == before

    migrated = load_ledger(str(tmp_path))
    assert migrated.schema_version == '2.0'
    assert [(d.issue_id, d.timestamp, d.notes) for d in migrated.decisions] == [(d.issue_id, d.timestamp, d.notes) for d in ledger.decisions]
    assert migrated.decisions[5].resolved_text is None
    assert migrated.decisions[0].anchor.quote.endswith('mantenuto dai tamponi.')
    paths = [get_ledger_path(str(tmp_path)), get_science_issues_path(str(tmp_path))]
    snapshots = {path:open(path, 'rb').read() for path in paths}
    assert [u.content for u in load_resolved_draft(str(tmp_path)).units] == before
    assert {path:open(path, 'rb').read() for path in paths} == snapshots
    if database:
        from rt.db.repositories import DecisionRepository, LessonRepository
        from rt.db.session import session_scope
        from rt.db.engine import get_database
        with session_scope(get_database()) as session:
            lesson = LessonRepository(session).get_by_path(str(tmp_path))
            rows = DecisionRepository(session).active(lesson)
            assert [row.anchor for row in rows] == [d.anchor.model_dump() if d.anchor else None for d in migrated.decisions]


def test_shared_segment_effects_are_migrated_per_unit(tmp_path):
    from rt.pipeline.review_migration import migrate_objects
    from rt.pipeline.ledger import apply_decisions_to_draft
    draft = Draft(units=[DraftUnit(unit_id=uid, title='Test', start_segment_id='seg_000001',
                 end_segment_id='seg_000001', source_segment_ids=['seg_000001'],
                 content='I saturi hanno doppi legami.') for uid in ('1.1', '1.2')])
    issue = ScienceIssue(id='sci_000001', type='ERR_CONCETTUALE', severity='low',
                         unit_id='1.1', segment_id='seg_000001', claim='hanno doppi legami', reason='Errore')
    ledger = DecisionLedger(decisions=[ReviewDecision(issue_id=issue.id, decision='accepted',
                                                     resolved_text='non hanno doppi legami')])
    before = [u.content for u in apply_decisions_to_draft(draft, ledger, [issue]).units]
    migrated, anchored = migrate_objects(draft, ledger, [issue], {})
    assert [u.content for u in apply_decisions_to_draft(draft, migrated, anchored).units] == before
    assert [i.unit_id for i in anchored] == ['1.1', '1.2']
    assert [d.issue_id for d in migrated.decisions] == ['sci_000001', 'sci_000002']


def test_invalid_ledger_is_not_overwritten(tmp_path):
    historical_lesson(tmp_path)
    path = get_ledger_path(str(tmp_path))
    with open(path, 'w') as file:
        file.write('{invalid')
    original = open(get_science_issues_path(str(tmp_path)), 'rb').read()
    with pytest.raises(ValueError):
        load_resolved_draft(str(tmp_path))
    assert open(path).read() == '{invalid'
    assert open(get_science_issues_path(str(tmp_path)), 'rb').read() == original
