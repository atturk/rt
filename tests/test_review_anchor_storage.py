"""Ancore e campi storici attraverso file, DB, annullamento e migrazione."""
import pytest
from alembic import command
from sqlalchemy import text
from rt.core.models import ScienceIssue, ReviewDecision
from rt.db.engine import alembic_config, create_db_engine, upgrade_database
from rt.db.repositories import DecisionRepository, LessonRepository
from rt.db.session import session_scope
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import record_decision, load_ledger, revert_last_decision
from rt.pipeline.review import load_science_issues, save_science_issues


def issue(anchor=None):
    return ScienceIssue(id='sci_000001', type='ERR_CONCETTUALE', severity='low',
                        unit_id='1.1', claim='7.4', reason='Valore', anchor=anchor)


def test_historical_models_are_readable():
    old = issue().model_dump(exclude={'anchor', 'origin'})
    loaded = ScienceIssue.model_validate(old)
    assert loaded.anchor is None and loaded.origin == 'verifica'
    assert ReviewDecision.model_validate({'issue_id': loaded.id, 'decision': 'rejected'}).anchor is None


@pytest.mark.parametrize('origin', ['verifica', 'parte', 'studio'])
def test_issue_origin_roundtrip(tmp_path, origin):
    original = issue(make_anchor('Il valore è 7.4.', 12, 15))
    original.origin = origin
    save_science_issues([original], str(tmp_path))
    assert load_science_issues(str(tmp_path)) == [original]


def _record_and_assert(lesson_dir):
    anchor = make_anchor('Il valore è 7.4.', 12, 15)
    save_science_issues([issue(anchor)], lesson_dir)
    decision = record_decision(lesson_dir, 'sci_000001', 'accepted', '7.35', notes='nota',
                               original_context='contesto', channel='api', actor='utente')
    assert decision.anchor == anchor
    assert load_ledger(lesson_dir).decisions[-1] == decision
    # Una successiva modifica dell'issue non cambia l'ancora già registrata.
    save_science_issues([issue(make_anchor('7.4', 0, 3))], lesson_dir)
    assert load_ledger(lesson_dir).decisions[-1].anchor == anchor
    return decision


def test_decision_file_copies_anchor(tmp_path):
    _record_and_assert(str(tmp_path))


def test_decision_db_export_import_and_undo(rt_db, tmp_path):
    lesson_dir = str(tmp_path / 'lezione')
    (tmp_path / 'lezione' / '_state').mkdir(parents=True)
    (tmp_path / 'lezione' / '_state' / 'info.yaml').write_text("data: '2026-10-09'\nmateria: Test\ntitolo: Test\n")
    decision = _record_and_assert(lesson_dir)
    with session_scope(rt_db) as session:
        lesson = LessonRepository(session).get_by_path(lesson_dir)
        row = DecisionRepository(session).active(lesson)[0]
        assert row.anchor == decision.anchor.model_dump()
        assert (row.notes, row.original_context, row.channel, row.actor) == ('nota', 'contesto', 'api', 'utente')
    assert revert_last_decision(lesson_dir, decision.issue_id)
    assert load_ledger(lesson_dir).decisions == []
    with session_scope(rt_db) as session:
        from rt.db.models import ReviewDecision as DbDecision
        row = session.query(DbDecision).one()
        assert row.reverted_at is not None and row.anchor == decision.anchor.model_dump()


def test_alembic_preserves_existing_decision(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'old.db')
    engine = create_db_engine(url)
    config = alembic_config(url, engine)
    command.upgrade(config, '0010')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO lessons (id, path, folder_name, data, materia, titolo, argomenti, workflow_state, created_at, updated_at) VALUES (1, 'old', 'old', '', '', '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO review_decisions (lesson_id, issue_id, decision, resolved_text, resolved_by, timestamp, created_at) VALUES (1, 'sci_000001', 'accepted', 'testo', 'user', '2026-10-09', CURRENT_TIMESTAMP)"))
    upgrade_database(url, engine)
    with engine.connect() as connection:
        row = connection.execute(text('SELECT issue_id, resolved_text, anchor FROM review_decisions')).one()
        assert tuple(row) == ('sci_000001', 'testo', None)
    engine.dispose()
