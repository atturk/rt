from rt.core.lesson_paths import lesson_path
from rt.core.update_history import record_version, list_versions, restore_version, undo_update
from rt.storage import fs


def write(lesson, name, content):
    with fs.open(lesson_path(lesson, name), 'w') as stream:
        stream.write(content)


def read(lesson, name):
    with fs.open(lesson_path(lesson, name)) as stream:
        return stream.read()


def test_versions_are_post_event_bounded_and_restore_can_be_undone(tmp_path):
    lesson = str(tmp_path)
    write(lesson, 'draft.json', 'original')
    first = record_version(lesson, 'import')
    for i in range(7):
        write(lesson, 'draft.json', str(i))
        record_version(lesson, 'extend', added=['notes'], new=1)
    versions = list_versions(lesson)
    assert len(versions) == 6 and sum(v['attuale'] for v in versions) == 1
    assert first not in [v['id'] for v in versions]
    restore_version(lesson, versions[-1]['id'])
    assert read(lesson, 'draft.json') == '1'
    assert list_versions(lesson)[0]['modo'] == 'restore'
    undo_update(lesson)
    assert read(lesson, 'draft.json') == '6'


def test_restore_preserves_database_study_data_and_matches_original_text(rt_db, tmp_path):
    from rt.db.repositories import LessonRepository
    from rt.db.session import session_scope
    from rt.services.highlights_service import add_highlight, list_highlights
    from rt.services.study_progress_service import list_units
    from rt.db.models import StudyUnit
    lesson = fs.create_db_lesson(str(tmp_path / 'virtual'))
    with session_scope(rt_db) as session:
        lid = LessonRepository(session).get_by_path(lesson).id
        session.add(StudyUnit(lesson_id=lid, unit_id='1.1', status='studiata'))
    write(lesson, 'draft.json', 'Il testo originale evidenziato')
    first = record_version(lesson, 'import')
    highlight = add_highlight(lid, '1.1', 1, {'text': 'originale evidenziato'})
    write(lesson, 'draft.json', 'Ricostruzione con testo diverso')
    record_version(lesson, 'rebuild')
    restore_version(lesson, first)
    assert list_highlights(lid, None) == [highlight]
    assert highlight['source']['text'] in read(lesson, 'draft.json')
    assert list_units(lid)[0]['status'] == 'studiata'
