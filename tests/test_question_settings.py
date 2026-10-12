"""Impostazioni Domande: registro, galleria, import/export e prove senza scritture."""
from pathlib import Path
from unittest.mock import patch
import json

import pytest
import yaml

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from tests.test_custom_question_types import definition

BASE = '/api/v1/settings/questions'


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    return isolated_workspace(tmp_path, monkeypatch)


def test_editor_gallery_stable_id_and_import_export(api_client, workspace):
    path = Path('config/general.yaml')
    data = yaml.safe_load(path.read_text())
    data['recall'] = {'custom_types': [], 'custom_type_threshold': .4, 'refill_thresholds': {'quiz': 9}}
    path.write_text(yaml.safe_dump(data))
    listed = api_client.get(BASE).json()
    assert len(listed['templates']) == 7 and not listed['types']
    assert {t['nome'] for t in listed['templates']} >= {'Caso clinico', 'Esercizio', 'Query SQL'}
    assert all('originali' not in t for t in listed['templates'])
    created = api_client.post(BASE, json=definition()).json()
    assert created['id'] == 'query-sql'
    changed = {**created, 'nome': 'Interrogazione', 'chiedi': 'Nuove istruzioni'}
    result = api_client.put(BASE + '/query-sql', json=changed)
    assert result.status_code == 200 and result.json()['id'] == 'query-sql'
    exported = api_client.get(BASE + '/query-sql/export')
    assert exported.json() == changed
    assert 'query-sql.json' in exported.headers['content-disposition']
    imported = api_client.post(BASE + '/import', json=exported.json())
    assert imported.status_code == 201 and imported.json()['id'] == 'query-sql-2'
    assert api_client.post(BASE + '/import', json=exported.json()).json()['id'] == 'query-sql-3'
    persisted = yaml.safe_load(path.read_text())
    assert persisted['telegram'] == data['telegram']
    assert persisted['recall']['custom_type_threshold'] == .4
    assert persisted['recall']['refill_thresholds'] == {'quiz': 9}
    assert api_client.put(BASE + '/query-sql', json={**changed, 'id': 'cambiato'}).status_code == 422
    assert api_client.delete(BASE + '/query-sql').status_code == 200
    assert api_client.get(BASE + '/query-sql/export').status_code == 404
    assert api_client.delete(BASE + '/query-sql').status_code == 404


@pytest.mark.parametrize('changes', [{'materie': []}, {'materie': 'Informatica'}, {'materie': [1]},
                                   {'materie': [{}]}, {'nome': 3}, {'id': 'quiz'}, {'extra': True}, {'chiedi': ' '}])
def test_invalid_import_is_rejected_without_saving(api_client, workspace, changes):
    path = Path('config/general.yaml')
    api_client.get(BASE)
    before = path.read_bytes()
    response = api_client.post(BASE + '/import', json=definition(**changes))
    assert response.status_code == 422, response.text
    assert path.read_bytes() == before


def test_id_collision_respects_maximum_length(api_client, workspace):
    item = definition(id='a' * 64)
    assert api_client.post(BASE, json=item).status_code == 201
    imported = api_client.post(BASE + '/import', json=item).json()
    assert len(imported['id']) == 64 and imported['id'].endswith('-2')


def _snapshot(path):
    from rt.storage import fs
    result = {}
    for root, _, names in fs.walk(path):
        for name in names:
            with fs.open(str(Path(root, name)), 'rb') as stream:
                result[str(Path(root, name).relative_to(path))] = stream.read()
    return result


def test_trial_and_lazy_reclassification_do_not_save_trial_data(api_client, workspace, rt_db):
    from rt.pipeline.rewrite import load_draft, save_draft
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.services import section_labels
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import Worker
    config = Path('config/general.yaml')
    data = yaml.safe_load(config.read_text())
    data['classifier'] = {'jobs': {'section_labels': {'mode': 'pipeline'}}}
    config.write_text(yaml.safe_dump(data))
    path = make_lesson(workspace)
    run_mock_pipeline(path, with_review=True)
    draft = load_draft(path)
    draft.units[0].content += ' Query SQL.'
    save_draft(draft, path)
    lesson_id = lesson_id_for_dir(path)
    proposed = definition(materie=['BIOCHIMICA'], correzione='soluzione')
    before = _snapshot(path)
    cfg_before = Path('config/general.yaml').read_bytes()
    trial = api_client.post(BASE + '/trial', json={'definition': proposed, 'lesson_id': lesson_id,
                                                  'unit_id': draft.units[0].unit_id, 'mock': True})
    assert trial.status_code == 200, trial.text
    assert trial.json()['label'] == 'presente' and 'Query SQL' in trial.json()['example']['question_text']
    assert trial.json()['example']['pregenerated_material']
    assert _snapshot(path) == before
    assert Path('config/general.yaml').read_bytes() == cfg_before
    assert api_client.get(BASE).json()['types'] == []
    assert api_client.post(BASE + '/trial', json={'definition': definition(), 'lesson_id': lesson_id,
                        'unit_id': draft.units[0].unit_id, 'mock': True}).status_code == 422
    api_client.post(BASE, json=proposed)
    automatic = DbJobQueue(rt_db).list(state='queued', lesson_id=path)
    assert len(automatic) == 1 and automatic[0].payload == {'job': 'custom:query-sql', 'force': False}
    worker = Worker(DbJobQueue(rt_db), worker_id='custom-labels', mock=True)
    for _ in range(10):
        if worker.run_once() is None:
            break
    assert api_client.get('/api/v1/jobs/' + automatic[0].id).json()['state'] == 'succeeded'
    assert any(row.get('query-sql') == 'presente' for row in section_labels.labels(path).values())
    cells = api_client.get(f'/api/v1/lessons/{lesson_id}/classifier').json()['jobs']['custom:query-sql']['cells']
    assert any(cell['state'] == 'fresh' and cell['value'] == 'presente' for cell in cells)
    digest = section_labels.configuration(path, force_mock=True)
    before_edit = _snapshot(path)
    saved = api_client.get(BASE).json()['types'][0]
    api_client.put(BASE + '/query-sql', json={**saved, 'nome': 'Tabelle nuove', 'cerca': 'Nuovo criterio'})
    assert section_labels.configuration(path, force_mock=True) != digest
    assert _snapshot(path) == before_edit  # il salvataggio invalida, senza scrivere le lezioni
    section_labels.refresh(path, force_mock=True)
    assert section_labels.configuration(path, force_mock=True) == next(iter(section_labels._load(path).values()))['config_hash']


def test_real_trial_uses_generic_prompts_without_lesson_cost_files(api_client, workspace, rt_db):
    from rt.pipeline.rewrite import load_draft
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.llm.jev_client import JevResponse, JevChoiceAnswer
    from rt.core.models import RecallTextGenerationResult
    path = make_lesson(workspace)
    run_mock_pipeline(path, with_review=True)
    unit = load_draft(path).units[0]
    before = _snapshot(path)
    response = JevResponse(model='test', answers={'tipo': JevChoiceAnswer(choice='query-sql', confidence=.9,
                             probabilities={'query-sql': .9, 'nessuno': .1})})
    result = RecallTextGenerationResult.model_validate({'items': [{'question_text': 'Proponi una query',
        'unit_ids': [unit.unit_id], 'tipo': {'scenario': 'Dati', 'obiettivo': 'Selezione', 'procedimento': 'Leggi i dati'}}]})
    with patch('rt.llm.jev_client.call_jev', return_value=response) as classify, \
            patch('rt.llm.client.LLMClient.call_structured', return_value=result) as generate:
        trial = api_client.post(BASE + '/trial', json={'definition': definition(materie=['BIOCHIMICA']),
                        'lesson_id': lesson_id_for_dir(path), 'unit_id': unit.unit_id})
    assert trial.status_code == 200, trial.text
    assert classify.call_args.kwargs['lesson_dir'] is None
    assert 'lesson_dir' not in generate.call_args.kwargs
    assert 'Scrivi una query.' in generate.call_args.kwargs['system_prompt']
    assert 'testuale' in generate.call_args.kwargs['system_prompt']
    assert trial.json()['example'].get('pregenerated_material') is None
    assert _snapshot(path) == before
