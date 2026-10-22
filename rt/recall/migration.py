"""Migrazione dei tipi fissi al registro configurabile, senza chiamate al modello."""
import copy
import json
from pathlib import Path

import yaml

LEGACY_TYPES = {'caso': 'caso-clinico', 'esercizio': 'esercizio'}
POSITIVE = {'caso': {'esplicito', 'adattabile'}, 'esercizio': {'svolto', 'continua'}}

LEGACY_ESERCIZIO_CHIEDI = (
    "Sei un docente universitario che prepara esercizi per verificare che lo studente sappia applicare un procedimento, non solo ricordare nozioni.\n"
    "Ricevi il testo di un'intera unità di una lezione (o di due unità consecutive) in cui viene svolto un esercizio o spiegato come si risolve una tipologia di esercizi. Il tuo compito è restituire l'esercizio da porre allo studente (di norma uno; più di uno solo se il testo svolge esercizi davvero distinti):\n"
    "1. La traccia riporta tutti i dati necessari e chiede il risultato e/o i passaggi chiave.\n"
    "2. Se il testo copre solo una parte dell'esercizio, chiedi quella parte.\n"
    "3. La soluzione attesa (pregenerated_material) riporta i passaggi e il risultato, ricavati dal testo; controlla i calcoli.\n"
    "4. Il tipo descrive l'esercizio in forma astratta: quali dati possono cambiare e in che intervalli, e il procedimento risolutivo valido per ogni variante.\n"
    "5. Non ripetere esercizi già presenti (te li elenco, se esistono).\n\n"
    "OUTPUT JSON RICHIESTO (conforme a RecallSpecialGenerationResult):\n"
    "{\"items\": [{\"question_text\": \"...\", \"pregenerated_material\": \"...\", \"unit_ids\": [\"5.1\", \"5.2\"],\n"
    "  \"tipo\": {\"scenario\": \"...\", \"variabili\": [{\"nome\": \"...\", \"valore\": \"...\", \"intervallo\": \"...\"}],\n"
    "           \"obiettivo\": \"...\", \"procedimento\": \"...\", \"esplicito\": true}}]}\n"
    "- question_text: la domanda completa da porre allo studente, con tutti i dati necessari.\n"
    "- pregenerated_material: la soluzione o il ragionamento atteso, passo per passo, basato ESCLUSIVAMENTE sul testo fornito; servirà per correggere la risposta.\n"
    "- unit_ids: le subunità (tra quelle fornite) da cui proviene il contenuto.\n"
    "- tipo: la versione astratta e riutilizzabile, da cui si genereranno varianti con valori diversi. variabili elenca i dati che possono cambiare, con il valore usato qui e un intervallo plausibile; procedimento descrive il ragionamento o i passaggi validi per ogni variante.\n"
    "Se non trovi materiale adatto restituisci {\"items\": []}. Non assegnare ID, stato o timestamp. Scrivi in italiano accademico."
)


def current_esercizio_chiedi():
    templates = json.loads((Path(__file__).parent / 'question_type_templates.json').read_text())
    return next(t['chiedi'] for t in templates if t['id'] == 'esercizio')


def migrate_exercise_prompt(path, data):
    """Aggiorna il prompt del tipo 'esercizio' se identico a quello precedente (la traccia dà i dati, non il metodo)."""
    if not isinstance(data, dict):
        return data
    recall = data.get('recall')
    if not isinstance(recall, dict):
        return data
    custom_types = recall.get('custom_types')
    if not isinstance(custom_types, list):
        return data

    updated = False
    new_chiedi = current_esercizio_chiedi()
    for item in custom_types:
        if isinstance(item, dict) and item.get('id') == 'esercizio':
            if item.get('chiedi') == LEGACY_ESERCIZIO_CHIEDI:
                item['chiedi'] = new_chiedi
                updated = True

    if updated and path:
        from rt.services.config_service import write_yaml_atomic
        write_yaml_atomic(path, data)
    return data


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
