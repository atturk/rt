"""Registro, modelli pronti e migrazione: ogni lezione vive sotto tmp_path."""
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rt.core.config import CustomQuestionType, RecallConfig, RTConfig, load_config
from rt.recall.migration import migrate_bank, migrate_registry
from rt.services.custom_question_types import active_types, templates


def definition(**changes):
    return {'nome': 'Query SQL', 'materie': ['Informatica'], 'cerca': 'Query e tabelle',
            'chiedi': 'Scrivi una query.', **changes}


def test_registry_validation_and_stable_identifiers():
    item = CustomQuestionType(**definition())
    assert item.id == 'query-sql'
    assert item.model_copy(update={'nome': 'Altro nome'}).id == 'query-sql'
    for changes in [{'materie': []}, {'materie': [' ']}, {'nome': ' '}, {'id': 'quiz'},
                    {'id': 'Non valido'}, {'correzione': 'numero'}]:
        with pytest.raises(ValidationError):
            CustomQuestionType(**definition(**changes))
    with pytest.raises(ValidationError):
        RecallConfig(custom_types=[item, item])
    with pytest.raises(ValidationError):
        RecallConfig(refill_thresholds={'query-sql': -1})
    cfg = RTConfig(recall=RecallConfig(custom_types=[item]))
    assert active_types(materia=' informatica ', cfg=cfg) == [item]
    assert active_types(materia='Storia', cfg=cfg) == []


def test_gallery_has_data_not_registered_types():
    gallery = templates()
    assert len(gallery) == 7
    assert {t['nome'] for t in gallery} >= {'Caso clinico', 'Esercizio', 'Query SQL'}
    assert all(t['materie'] == [] for t in gallery)
    assert 'originali' not in gallery[0]


def test_initial_registry_and_file_migration_are_idempotent(tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace
    root = Path(isolated_workspace(tmp_path, monkeypatch))
    lesson = root / 'lezione'
    state = lesson / '_state'
    state.mkdir(parents=True)
    (lesson / 'info.yaml').write_text('materia: Medicina\n')
    (state / 'section_labels.json').write_text(json.dumps({'1': {'caso': 'esplicito', 'esercizio': 'svolto'}}))
    old = {'questions': [{'id': 'recall_000010', 'type': 'caso'},
                         {'id': 'recall_000011', 'type': 'esercizio'},
                         {'id': 'recall_000002', 'type': 'quiz', 'unit_ids': ['1.1'], 'question_text': 'Q'}],
           'answers': [{'question_id': 'recall_000010'}, {'question_id': 'recall_000002'}],
           'templates': [{'kind': 'caso'}], 'generation_attempts': {'caso:sezioni:1': {}, 'quiz:1.1': {}}}
    (state / 'recall_questions.json').write_text(json.dumps(old))
    cfg = load_config()
    assert [t.nome for t in cfg.recall.custom_types] == ['Caso clinico', 'Esercizio']
    assert all(t.materie == ['Medicina'] for t in cfg.recall.custom_types)
    migrated = json.loads((state / 'recall_questions.json').read_text())
    assert [q['id'] for q in migrated['questions']] == ['recall_000002']
    assert migrated['answers'] == [{'question_id': 'recall_000002'}]
    assert migrated['last_question_number'] == 11 and migrated['templates'] == []
    assert migrated['generation_attempts'] == {'quiz:1.1': {}}
    assert json.loads((state / 'section_labels.json').read_text()) == {}
    assert migrate_bank(migrated) == migrated
    path = Path('config/general.yaml')
    content = path.read_text()
    migrate_registry(path, yaml.safe_load(content))
    assert path.read_text() == content


def test_custom_type_is_preserved_in_question_and_template():
    from rt.core.models import RecallQuestion, RecallQuestionType
    question = RecallQuestion(id='q', type='personalizzata', custom_type='query-sql', unit_ids=['1.1'], question_text='Query?')
    assert question.type == RecallQuestionType.PERSONALIZZATA
    assert question.model_dump(mode='json')['custom_type'] == 'query-sql'


def test_alembic_0013_migrates_database_documents(tmp_path, monkeypatch):
    from alembic import command
    from rt.db.engine import create_db_engine, upgrade_database, alembic_config, current_revision
    from rt.db.models import Lesson, LessonFile, StateDocument
    from sqlalchemy.orm import Session
    from tests.api_support import isolated_workspace
    isolated_workspace(tmp_path, monkeypatch)
    url = f'sqlite:///{tmp_path / "migration.db"}'
    engine = create_db_engine(url)
    config = alembic_config(url, engine)
    command.upgrade(config, '0012')
    bank = {'questions': [{'id': 'recall_000099', 'type': 'caso'},
                          {'id': 'recall_000001', 'type': 'quiz'}],
            'answers': [{'question_id': 'recall_000099'}]}
    with Session(engine) as session:
        lesson = Lesson(path=str(tmp_path / 'db-lesson'), folder_name='db-lesson', materia='Medicina', storage='db')
        session.add(lesson)
        session.flush()
        session.add(LessonFile(lesson_id=lesson.id, name='section_labels.json', content=json.dumps(
            {'1': {'caso': 'esplicito', 'esercizio': 'svolto'}}).encode()))
        session.add(LessonFile(lesson_id=lesson.id, name='recall_questions.json', content=json.dumps(bank).encode()))
        session.add(StateDocument(key=str(tmp_path / 'recall_questions.json'), payload=bank))
        session.commit()
    upgrade_database(url, engine)
    assert current_revision(engine) >= '0013'  # le migrazioni successive non cambiano i documenti
    with Session(engine) as session:
        document = session.get(StateDocument, str(tmp_path / 'recall_questions.json'))
        assert document.payload['last_question_number'] == 99
        assert document.payload['answers'] == []
        rows = session.query(LessonFile).all()
        assert next(json.loads(r.content) for r in rows if r.name == 'section_labels.json') == {}
        assert [q['type'] for r in rows if r.name == 'recall_questions.json' for q in json.loads(r.content)['questions']] == ['quiz']
    data = yaml.safe_load(Path('config/general.yaml').read_text())
    assert len(data['recall']['custom_types']) == 2
    engine.dispose()


def test_types_endpoint_reads_registry_without_fixed_custom_names(api_client, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace
    isolated_workspace(tmp_path, monkeypatch)
    data = yaml.safe_load(Path('config/general.yaml').read_text())
    data['recall'] = {'custom_types': [CustomQuestionType(**definition()).model_dump()]}
    Path('config/general.yaml').write_text(yaml.safe_dump(data))
    rows = api_client.get('/api/v1/recall/types', params={'materia': 'Informatica'}).json()
    assert [r['id'] for r in rows] == ['quiz', 'mirata', 'vasta', 'query-sql']
    assert rows[-1]['nome'] == 'Query SQL' and rows[-1]['custom']
    other = api_client.get('/api/v1/recall/types', params={'materia': 'Storia'}).json()
    assert len(other) == 3


def test_new_bank_keeps_attempts_of_registry_type_named_like_old_one():
    """Il tipo Esercizio del registro usa le chiavi «esercizio:…»: senza vecchie domande non si toccano."""
    bank = {'questions': [{'id': 'recall_000001', 'type': 'personalizzata', 'custom_type': 'esercizio'}],
            'templates': [{'kind': 'personalizzata', 'custom_type': 'esercizio'}],
            'generation_attempts': {'esercizio:sezioni:1': {'exhausted': True}}}
    assert migrate_bank(bank) == bank
