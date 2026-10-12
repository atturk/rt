"""Migrazione dei tipi fissi al registro configurabile, senza chiamate al modello."""
import copy
import json
from pathlib import Path

import yaml

LEGACY_TYPES = {'caso': 'caso-clinico', 'esercizio': 'esercizio'}
POSITIVE = {'caso': {'esplicito', 'adattabile'}, 'esercizio': {'svolto', 'continua'}}


def migrate_bank(data):
    """Come l'eliminazione dal pool: toglie domande, risposte e strutture obsolete."""
    result = copy.deepcopy(data)
    questions = result.get('questions') or []
    # Solo le banche con domande o strutture dei vecchi tipi fissi: il tipo Esercizio del registro
    # usa le stesse chiavi dei tentativi e non va ripulito a ogni lettura.
    if not any(q.get('type') in LEGACY_TYPES for q in questions) and \
            not any(t.get('kind') in LEGACY_TYPES for t in result.get('templates') or []):
        return result
    deleted = {q.get('id') for q in questions if q.get('type') in LEGACY_TYPES}
    result['questions'] = [q for q in questions if q.get('id') not in deleted]
    result['answers'] = [a for a in result.get('answers', []) if a.get('question_id') not in deleted]
    result['templates'] = [t for t in result.get('templates', []) if t.get('kind') not in LEGACY_TYPES]
    result['generation_attempts'] = {k: v for k, v in result.get('generation_attempts', {}).items()
                                     if k.split(':')[0] not in LEGACY_TYPES}
    numbers = [int(q['id'][7:]) for q in questions if str(q.get('id', '')).startswith('recall_')
               and str(q['id'][7:]).isdigit()]
    result['last_question_number'] = max([result.get('last_question_number', 0), *numbers])
    return result


def legacy_labels(data):
    return isinstance(data, dict) and any(isinstance(row, dict) and
        any(k in row or 'override_' + k in row for k in LEGACY_TYPES) for row in data.values())


def migrate_registry(path, data):
    """Prima lettura della configurazione: registro e file delle lezioni locali."""
    if not isinstance(data.get('telegram') or {}, dict) or not isinstance(data.get('recall') or {}, dict):
        return data
    if 'custom_types' in (data.get('recall') or {}):
        return data
    from rt.services.config_service import write_yaml_atomic
    original = copy.deepcopy(data)
    found = {k: set() for k in LEGACY_TYPES}
    root = (data.get('telegram') or {}).get('lessons_root')
    if root and Path(root).is_dir():
        for lesson in sorted(Path(root).iterdir()):
            if not lesson.is_dir():
                continue
            try:
                _migrate_lesson(lesson, found)
            except (OSError, ValueError, yaml.YAMLError):
                continue  # una lezione illeggibile non blocca le altre
    if original.get('recall') is None:
        original['recall'] = {}
    original['recall']['custom_types'] = seeded_types(found)
    write_yaml_atomic(path, original)
    return original


def _migrate_lesson(lesson, found):
    """Una lezione: materie con i vecchi tipi trovati, etichette e banca ripulite."""
    from rt.services.config_service import write_text_atomic
    info_path = lesson / 'info.yaml'
    info = yaml.safe_load(info_path.read_text()) if info_path.is_file() else {}
    subject = str((info or {}).get('materia') or '').strip()
    for state in (lesson, lesson / '_state'):
        labels_path = state / 'section_labels.json'
        if labels_path.is_file():
            labels = json.loads(labels_path.read_text())
            if legacy_labels(labels):
                for kind, positive in POSITIVE.items():
                    if subject and any((r.get('override_' + kind) or r.get(kind)) in positive
                                       for r in labels.values() if isinstance(r, dict)):
                        found[kind].add(subject)
                write_text_atomic(labels_path, '{}\n')
        bank_path = state / 'recall_questions.json'
        if bank_path.is_file():
            bank = json.loads(bank_path.read_text())
            migrated = migrate_bank(bank)
            if migrated != bank:
                write_text_atomic(bank_path, json.dumps(migrated, ensure_ascii=False, indent=2) + '\n')


def seeded_types(found):
    templates = json.loads((Path(__file__).parent / 'question_type_templates.json').read_text())
    registry = []
    for kind, identifier in LEGACY_TYPES.items():
        if not found[kind]:
            continue
        item = copy.deepcopy(next(t for t in templates if t['id'] == identifier))
        item.pop('originali', None)
        item['materie'] = sorted(found[kind])
        registry.append(item)
    return registry
