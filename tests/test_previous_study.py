from datetime import datetime, timedelta, timezone

from rt.pipeline.source_update import _write_state
from rt.services.previous_study import is_previous
from rt.services.sources_view import record_update_summary


def test_previous_is_temporal_and_restore_reverts_change_history(tmp_path, rt_db):
    from rt.storage import fs
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope
    from rt.core.update_history import record_version, restore_version
    from rt.services.highlights_service import add_highlight, list_highlights
    from rt.services.study_notes_service import add_study_note, list_study_notes
    lesson = fs.create_db_lesson(str(tmp_path / 'virtual'))
    with session_scope(rt_db) as session:
        lid = LessonRepository(session).get_by_path(lesson).id
    highlight = add_highlight(lid, '1.1', 0, {'text': 'original'})
    note = add_study_note(lid, '1.1', 'chiedi', {}, response={'answer': 'original'})
    first = record_version(lesson, 'import')
    change = datetime.now(timezone.utc)
    _write_state(lesson, {'next_segment': 1, 'sources': {}, 'unit_changed_at': {'1.1': change.isoformat()}})
    assert list_highlights(lid, None)[0]['precedente']
    assert list_study_notes(lid)[0]['precedente']
    assert is_previous(lesson, ['1.2', '1.1'], (change - timedelta(seconds=1)).isoformat())
    assert not is_previous(lesson, ['1.2'], (change - timedelta(seconds=1)).isoformat())
    assert not is_previous(lesson, ['1.1'], (change + timedelta(seconds=1)).isoformat())
    restore_version(lesson, first)
    assert not list_highlights(lid, None)[0]['precedente']
    assert not list_study_notes(lid)[0]['precedente']


def test_recall_previous_across_every_question_view(tmp_path):
    from rt.core.models import RecallBank, RecallQuestion
    from rt.pipeline.recall import save_recall_bank
    from rt.services.recall_service import question_view, question_resume_view, recall_history, question_list
    lesson = str(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    question = RecallQuestion(id='q1', type='mirata', unit_ids=['1.1'], question_text='Explain', created_at=old)
    _write_state(lesson, {'next_segment': 1, 'sources': {},
                          'unit_changed_at': {'1.1': datetime.now(timezone.utc).isoformat()}})
    save_recall_bank(RecallBank(questions=[question]), lesson)
    assert question_view(question, lesson_dir=lesson)['precedente']
    assert question_resume_view(lesson, question)['precedente']
    assert recall_history(lesson)['questions'][0]['precedente']
    assert question_list(lesson)['questions'][0]['precedente']


def test_legacy_question_local_time_is_compared_to_utc_change(tmp_path, monkeypatch):
    import time
    if not hasattr(time, 'tzset'):
        return
    _write_state(str(tmp_path), {'next_segment': 1, 'sources': {},
        'unit_changed_at': {'1.1': '2026-10-12T09:00:00+00:00'}})
    try:
        with monkeypatch.context() as patch:
            patch.setenv('TZ', 'Europe/Rome')
            time.tzset()
            assert is_previous(str(tmp_path), ['1.1'], '2026-10-12T10:30:00')
            assert not is_previous(str(tmp_path), ['1.1'], '2026-10-12T11:30:00')
    finally:
        time.tzset()
