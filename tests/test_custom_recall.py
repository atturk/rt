"""Un tipo aggiunto ai dati attraversa classificatore, consiglio, API e recaller."""
import re
from pathlib import Path

import yaml

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from tests.test_custom_question_types import definition


def test_no_fixed_custom_type_names_in_application_code():
    root = Path(__file__).resolve().parents[1]
    allowed = {'rt/recall/question_type_templates.json', 'rt/recall/migration.py',
               'rt/db/migrations/versions/0013_custom_question_types.py'}
    forbidden = re.compile(r'(?<![a-zA-Z])(?:caso|esercizio)(?![a-zA-Z])', re.IGNORECASE)
    violations = []
    for directory in ('rt', 'frontend/src'):
        for path in (root / directory).rglob('*'):
            relative = path.relative_to(root).as_posix()
            if not path.is_file() or path.suffix not in {'.py', '.ts', '.tsx', '.json', '.css'}:
                continue
            if relative in allowed or '.test.' in path.name or '/tests/' in relative:
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if forbidden.search(line):
                    violations.append(f'{relative}:{number}')
    assert not violations, '\n'.join(violations)


def test_query_sql_works_from_configuration_without_code_changes(api_client, rt_db, tmp_path, monkeypatch):
    from rt.pipeline.rewrite import load_draft, save_draft
    from rt.pipeline.recall import load_recall_bank
    from rt.services import section_labels, question_types
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import Worker
    root = isolated_workspace(tmp_path, monkeypatch)
    config = Path('config/general.yaml')
    data = yaml.safe_load(config.read_text())
    data.update(mock_llm=True, jev={'relevance_model': 'typesafe/jev-1.13', 'relevance_mode': 'shadow'},
                recall={'custom_types': [definition(materie=['BIOCHIMICA'], icona='Database', correzione='soluzione')]})
    config.write_text(yaml.safe_dump(data))
    path = make_lesson(root)
    run_mock_pipeline(path, with_review=False)
    draft = load_draft(path)
    draft.units[0].content += ' Query SQL: seleziona i dati pertinenti.'
    save_draft(draft, path)
    assert question_types.enabled()
    unit_id = draft.units[0].unit_id
    section_labels.refresh(path, force_mock=True)
    question_types.refresh(path, force_mock=True)
    assert 'query-sql' in question_types.suggestions(path).values()
    lesson_id = api_client.get('/api/v1/lessons').json()[0]['id']
    base = f'/api/v1/lessons/{lesson_id}'
    classifier = api_client.get(base + '/classifier').json()['jobs']['custom:query-sql']
    assert classifier['nome'] == 'Query SQL' and classifier['icona'] == 'Database'
    assert any(cell['value'] == 'presente' for cell in classifier['cells'])
    types = api_client.get('/api/v1/recall/types', params={'lesson_id': lesson_id}).json()
    assert next(t for t in types if t['id'] == 'query-sql')['available']
    study = api_client.get(base + '/study').json()
    assert next(u for u in study['units'] if u['id'] == unit_id)['suggested_qtype'] == 'query-sql'
    accepted = api_client.post(base + '/recall/generate', json={'qtype': 'query-sql', 'count': 1, 'mock': True})
    assert accepted.status_code == 202, accepted.text
    worker = Worker(DbJobQueue(rt_db), worker_id='query-sql', mock=True)
    for _ in range(20):
        if worker.run_once() is None:
            break
    result = api_client.get('/api/v1/jobs/' + accepted.json()['job_id']).json()
    assert result['state'] == 'succeeded', result
    question = api_client.post(base + '/recall/next', params={'qtype': 'query-sql'}).json()
    assert question['type'] == 'personalizzata' and question['custom_type'] == 'query-sql'
    assert 'Query SQL' in question['question_text']
    assert load_recall_bank(path).questions[0].pregenerated_material
    subject = api_client.get('/api/v1/recall/types', params={'materia': 'BIOCHIMICA'}).json()
    assert any(t['id'] == 'query-sql' for t in subject)
    data['recall']['custom_types'] = []
    config.write_text(yaml.safe_dump(data))
    assert api_client.post(base + '/recall/generate', json={'qtype': 'query-sql'}).status_code == 422
    assert any(q['custom_type'] == 'query-sql' for q in api_client.get(base + '/recall/history').json()['questions'])
    assert 'query-sql' not in [t['id'] for t in api_client.get('/api/v1/recall/types', params={'lesson_id': lesson_id}).json()]
