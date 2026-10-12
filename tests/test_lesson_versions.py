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
    from rt.services.study_notes_service import add_study_note, list_study_notes
    from rt.core.models import RecallBank, RecallQuestion
    from rt.pipeline.recall import save_recall_bank, load_recall_bank
    note = add_study_note(lid, '1.1', 'chiedi', {'quote': 'originale'}, response={'answer': 'studio'})
    question = RecallQuestion(id='q1', type='mirata', unit_ids=['1.1'], question_text='Domanda conservata')
    save_recall_bank(RecallBank(questions=[question]), lesson)
    write(lesson, 'draft.json', 'Ricostruzione con testo diverso')
    record_version(lesson, 'rebuild')
    restore_version(lesson, first)
    assert list_highlights(lid, None) == [highlight]
    assert highlight['source']['text'] in read(lesson, 'draft.json')
    assert list_units(lid)[0]['status'] == 'studiata'
    assert list_study_notes(lid) == [note]
    assert load_recall_bank(lesson).questions == [question]


def test_rebuild_then_restore_previous_version_preserves_highlights(api_client, rt_db, tmp_path, monkeypatch):
    from tests.test_api_sources import source_lesson, lesson_id
    from tests.api_support import isolated_workspace, make_lesson, add_audio, run_mock_pipeline
    from rt.services.highlights_service import add_highlight, list_highlights
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import Worker
    from rt.pipeline.rewrite import load_draft
    from rt.core.sources import add_source
    from rt.pipeline.source_update import run_source_update
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = make_lesson(root)
    add_audio(lesson)
    assert run_mock_pipeline(lesson, with_review=False).status.value == 'completed'
    lid = lesson_id(api_client)
    original = load_draft(lesson).units[0]
    first = record_version(lesson, 'import')
    highlight = add_highlight(lid, original.unit_id, 1, {'text': original.content[:20]})
    add_source(lesson, 'appunti', 'new.txt', b'Nuovo testo per ricostruire')
    run_source_update(lesson, mode='rebuild', mock=True)
    url = f'/api/v1/lessons/{lid}'
    versions = api_client.get(url + '/versions').json()
    assert versions[0]['modo'] == 'rebuild' and versions[0]['attuale']
    response = api_client.post(url + f'/versions/{first}/restore')
    assert response.status_code == 202
    assert api_client.post(url + f'/versions/{first}/restore').status_code == 409
    done = Worker(DbJobQueue(rt_db), job_types=['restore_version'], on_message=lambda *_: None).run_once()
    assert done.state == 'succeeded', done.error
    assert load_draft(lesson).units[0].content == original.content
    assert list_highlights(lid, None) == [highlight]
    assert highlight['source']['text'] in load_draft(lesson).units[0].content
    assert api_client.get(url + '/versions').json()[0]['modo'] == 'restore'
