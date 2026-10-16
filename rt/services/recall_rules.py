"""Regole dai voti per tipo e materia, aggiornate solo su richiesta o all'inizio del job."""
import json
import logging
import os
from datetime import datetime
from pydantic import BaseModel, Field
from rt.core.config import load_config
from rt.core.filelock import file_lock
from rt.storage import fs

_LOG = logging.getLogger(__name__)


class DistilledRules(BaseModel):
    rules: list[str] = Field(max_length=8)


class RuleCheck(BaseModel):
    rejected: list[int] = Field(default_factory=list)


def path():
    return os.path.join(load_config().telegram.state_dir, 'recall_rules.json')


def load():
    if not fs.isfile(path()):
        return {}
    with fs.open(path(), encoding='utf-8') as stream:
        return json.load(stream)


def _save(data):
    from rt.pipeline.recall import _atomic_write
    fs.makedirs(os.path.dirname(path()), exist_ok=True)
    _atomic_write(path(), data)


def votes(qtype, subject):
    from rt.pipeline.recall import _load_fewshot, fewshot_history
    return [r for r in fewshot_history(_load_fewshot().get(qtype, [])) if r.get('subject', '') == subject]


def update(qtype, subject, *, manual=False, mock=False):
    from rt.llm.client import LLMClient
    row = load().get(qtype, {}).get(subject, {})
    history = votes(qtype, subject)
    new = [v for v in history if v.get('voted_at', '') > row.get('processed_at', '')]
    if not manual and (row.get('manual') or len(new) < 5):
        return row.get('rules', [])
    if not history:
        return row.get('rules', [])
    watermark = max(v.get('voted_at', '') for v in history)
    client = LLMClient(force_mock=mock)
    if client.force_mock:
        rules = ['Formula una domanda chiara e pertinente alla propria unità.']
    else:
        result = client.call_structured(
            system_prompt='Riassumi i voti in massimo 8 regole brevi di forma e livello. Non importare contenuti o scenari degli esempi. Restituisci DistilledRules.',
            prompt=json.dumps({'tipo': qtype, 'materia': subject, 'voti': [
                {k: v[k] for k in ('question_text', 'vote', 'reasons', 'comment') if v.get(k)} for v in history]},
                ensure_ascii=False),
            response_model=DistilledRules, job_name='recall')
        rules = [r.strip() for r in result.rules if r.strip()][:8]
    with file_lock(fs.lock_path(path() + '.lock')):
        data = load()
        current = data.get(qtype, {}).get(subject, {})
        # Una modifica manuale arrivata durante la chiamata prevale sull'automatico.
        if not manual and current.get('manual'):
            return current.get('rules', [])
        data.setdefault(qtype, {})[subject] = {'rules': rules, 'updated_at': datetime.now().isoformat(),
            'processed_at': watermark, 'manual': False}
        _save(data)
    return rules


def edit(qtype, subject, rules):
    with file_lock(fs.lock_path(path() + '.lock')):
        data = load()
        row = data.setdefault(qtype, {}).setdefault(subject, {})
        row.update(rules=[r.strip() for r in rules if r.strip()][:8], manual=True)
        _save(data)


def prepare(qtype, lesson_dir, *, mock=False):
    from rt.services.recall_context import lesson_context
    if not load_config().recall.votes_enabled:
        return []
    subject = lesson_context(lesson_dir).get('materia', '')
    try:
        return update(qtype, subject, mock=mock)
    except Exception as exc:  # un modello che sbaglia il JSON non ferma la generazione
        from rt.llm.cancel import RunCancelled
        if isinstance(exc, RunCancelled):
            raise
        _LOG.warning("Regole dai voti non aggiornate (%s, %s): %s", qtype, subject, exc)
        return load().get(qtype, {}).get(subject, {}).get('rules', [])


def block(rules):
    return ('REGOLE DAI VOTI (forma e livello):\n' + '\n'.join('- ' + r for r in rules) + '\n\n') if rules else ''


def filter_group(questions, rules, *, mock=False, summary=None, lesson_dir=None):
    cfg = load_config().recall
    if not questions or not rules or not cfg.votes_enabled or not cfg.presave_check or mock:
        return questions
    from rt.llm.client import LLMClient
    from rt.llm.cancel import RunCancelled
    try:
        result = LLMClient(force_mock=False).call_structured(
            system_prompt='Confronta le domande con le regole. Scarta solo violazioni chiare; restituisci RuleCheck con gli indici da scartare, a partire da zero.',
            prompt=json.dumps({'regole': rules, 'domande': [q.model_dump(mode='json') for q in questions]}, ensure_ascii=False),
            response_model=RuleCheck, job_name='recall', lesson_dir=lesson_dir)
    except RunCancelled:
        raise
    except Exception as exc:  # controllo non riuscito: le domande generate si tengono
        _LOG.warning("Controllo prima di salvare non riuscito: %s", exc)
        return questions
    rejected = set(i for i in result.rejected if 0 <= i < len(questions))
    if summary is not None:
        summary['presave_discarded'] = summary.get('presave_discarded', 0) + len(rejected)
    return [q for i, q in enumerate(questions) if i not in rejected]


def view():
    from rt.pipeline.recall import _load_fewshot, fewshot_history
    cfg = load_config().recall
    data = load()
    rows = []
    for qtype, saved in _load_fewshot().items():
        history = fewshot_history(saved)
        for subject in dict.fromkeys(v.get('subject', '') for v in history):
            rows.append({'type': qtype, 'subject': subject, 'votes': sum(v.get('subject', '') == subject for v in history),
                         'rules': [], 'updated_at': None, **data.get(qtype, {}).get(subject, {})})
    return {'votes_enabled': cfg.votes_enabled, 'presave_check': cfg.presave_check, 'groups': rows}


def settings(votes_enabled, presave_check):
    from rt.services.config_service import general_config_path, read_yaml, write_yaml_atomic
    target = general_config_path()
    with file_lock(str(target) + '.lock'):
        data = read_yaml(target)
        data.setdefault('recall', {}).update(votes_enabled=votes_enabled, presave_check=presave_check)
        write_yaml_atomic(target, data)
    return view()
