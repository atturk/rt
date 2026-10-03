"""Ripristino della pipeline: copia unica, conteggio e decisioni conservate."""
import json
import os
import pytest
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson, _preview
from rt.services.document_edit_service import save_document_edit, DocumentEditError
from rt.services.document_restore_service import pipeline_version, restore_pipeline_version, SNAPSHOT_FILE
from rt.services.lesson_service import ensure_indexed
from rt.core.lesson_paths import lesson_path
from rt.pipeline.rewrite import load_draft, save_draft
from rt.storage import fs

@pytest.fixture(params=['folder', 'db'])
def lesson(tmp_path, monkeypatch, rt_db, request):
    path = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch))
    ensure_indexed([path])
    if request.param == 'db':
        from rt.storage.migrate import migrate_storage
        assert not migrate_storage(os.path.dirname(path)).errors
    return path


def test_snapshot_only_on_first_real_save_and_restore(api_client, lesson):
    from rt.services.lesson_service import lesson_id_for_dir
    original = _preview(lesson)
    draft = load_draft(lesson).model_dump()
    assert pipeline_version(lesson) == {'available': False, 'modified_units': 0}
    save_document_edit(lesson, original)
    with pytest.raises(DocumentEditError): save_document_edit(lesson, 'testo non valido')
    assert not fs.isfile(lesson_path(lesson, SNAPSHOT_FILE))
    save_document_edit(lesson, original.replace("Testo dell'unità 1.1.", 'Testo manuale.').replace('Acidi grassi', 'Titolo manuale').replace('00:20', '00:10'))
    with fs.open(lesson_path(lesson, SNAPSHOT_FILE)) as f: snapshot = f.read()
    assert pipeline_version(lesson) == {'available': True, 'modified_units': 2}
    save_document_edit(lesson, _preview(lesson).replace('Testo manuale.', 'Seconda modifica.'))
    with fs.open(lesson_path(lesson, SNAPSHOT_FILE)) as f: assert f.read() == snapshot
    # Anche un ledger cambiato nel frattempo deve restare identico al ripristino.
    ledger = lesson_path(lesson, 'review_decisions.json')
    with fs.open(ledger, 'w') as f: f.write('{"decisions": [], "schema_version": "1.0"}')
    lesson_id = lesson_id_for_dir(lesson)
    url = f'/api/v1/lessons/{lesson_id}/document'
    assert api_client.get(url + '/pipeline-version').json()['modified_units'] == 2
    result = api_client.post(url + '/restore-pipeline')
    assert result.status_code == 200, result.text
    assert result.json()['units_changed'] == ['1.1', '1.2']
    assert load_draft(lesson).model_dump() == draft and _preview(lesson) == original
    with fs.open(ledger) as f: assert json.load(f)['decisions'] == []
    assert pipeline_version(lesson)['modified_units'] == 0
    assert api_client.post(url + '/restore-pipeline').json()['modified_units'] == 0


def test_images_and_macro_titles_restore(lesson):
    from rt.pipeline.add_images import get_descriptions_path
    from rt.pipeline.image_placement import save_image_placement, load_image_placement
    image_path = lesson_path(lesson, 'assets/images/x.png')
    fs.makedirs(os.path.dirname(image_path), exist_ok=True)
    with fs.open(image_path, 'wb') as f: f.write(b'immagine')
    with fs.open(get_descriptions_path(lesson), 'w') as f: json.dump({'x': {'filename': 'assets/images/x.png', 'description': 'Immagine'}}, f)
    save_image_placement(lesson, {'1': ['x']}, False)
    original = _preview(lesson)
    save_document_edit(lesson, original.replace('![Immagine](assets/images/x.png)', '').replace('## 1. Struttura', '## 1. Nuova sezione'))
    assert pipeline_version(lesson)['modified_units'] == 2
    restore_pipeline_version(None, lesson)
    assert _preview(lesson) == original
    assert load_image_placement(lesson)['macros'] == {'1': ['x']}
    assert fs.isfile(image_path)


def test_new_pipeline_generation_starts_new_snapshot(lesson):
    original = _preview(lesson)
    save_document_edit(lesson, original.replace("Testo dell'unità 1.1.", 'Manuale.'))
    save_draft(load_draft(lesson), lesson)
    assert pipeline_version(lesson)['available'] is False


def test_restore_is_blocked_by_job_and_lease(api_client, lesson, rt_db):
    from rt.services.jobs import DbJobQueue
    from rt.services.lesson_service import lesson_id_for_dir
    lesson_id = lesson_id_for_dir(lesson)
    save_document_edit(lesson, _preview(lesson).replace("Testo dell'unità 1.1.", 'Manuale.'))
    url = f'/api/v1/lessons/{lesson_id}/document'
    token = api_client.post(url + '/lease').json()['token']
    assert api_client.post(url + '/restore-pipeline').status_code == 409
    assert api_client.post(url + '/restore-pipeline', json={'lease_token': token}).status_code == 200
    api_client.delete(url + '/lease', params={'token': token})
    DbJobQueue(rt_db).enqueue('run_phase', lesson, {})
    assert api_client.post(url + '/restore-pipeline').status_code == 409
