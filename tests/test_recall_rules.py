import json
from unittest.mock import Mock
import pytest
from rt.core.config import RTConfig
from rt.pipeline import recall
from rt.services import recall_rules as service


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    config = RTConfig()
    config.telegram.state_dir = str(tmp_path)
    monkeypatch.setattr(service, 'load_config', lambda: config)
    monkeypatch.setattr(recall, 'load_config', lambda: config)
    return config


def vote(subject='Medicina', text='Qual è il compenso respiratorio?', **kwargs):
    recall.record_fewshot_vote('mirata', text, 'up', subject=subject, **kwargs)


def test_history_compatibility_limit_and_pertinent_examples(cfg):
    target = recall.get_fewshot_path()
    for old in [[{'question_text': 'Vecchia?', 'vote': 'up'}], {'good': [{'question_text': 'Vecchia?', 'vote': 'up'}], 'avoid': []}]:
        with open(target, 'w') as stream: json.dump({'mirata': old}, stream)
        vote(lesson='lesson-1', unit_ids=['1.1'], reasons=['buona'], comment='Chiara')
        rows = recall.fewshot_history(recall._load_fewshot()['mirata'])
        assert len(rows) == 2 and rows[-1]['lesson'] == 'lesson-1' and rows[-1]['unit_ids'] == ['1.1']
    for n in range(305): vote(text=f'Qual è il ruolo di ADH {n}?')
    assert len(recall.fewshot_history(recall._load_fewshot()['mirata'])) == 300
    vote(subject='Biochimica', text='Descrivi il glucosio e la glicolisi.')
    vote(text='Qual è il compenso respiratorio nella acidosi metabolica?')
    examples = recall.load_fewshot_examples('mirata', subject='Medicina', unit_text='Acidosi e compenso respiratorio')
    assert examples[0]['subject'] == 'Medicina' and 'acidosi' in examples[0]['question_text']
    assert len(examples) == 5


def test_automatic_threshold_manual_protection_and_explicit_update(cfg, monkeypatch):
    call = Mock(return_value=service.DistilledRules(rules=['Evita domande su date.']))
    monkeypatch.setattr('rt.llm.client.LLMClient.call_structured', call)
    for n in range(4): vote(text=f'Domanda {n}')
    assert service.update('mirata', 'Medicina') == [] and not call.called
    vote(text='Quinta')
    assert service.update('mirata', 'Medicina') == ['Evita domande su date.']
    assert call.call_count == 1
    service.update('mirata', 'Medicina')
    assert call.call_count == 1
    service.edit('mirata', 'Medicina', ['Regola scritta a mano'])
    for n in range(5): vote(text=f'Altra domanda {n}')
    assert service.update('mirata', 'Medicina') == ['Regola scritta a mano']
    assert call.call_count == 1
    service.update('mirata', 'Medicina', manual=True)
    assert call.call_count == 2 and not service.load()['mirata']['Medicina']['manual']


def test_presave_checks_batch_and_switches(cfg, monkeypatch):
    from rt.core.models import GeneratedMirata
    questions = [GeneratedMirata(type='mirata', question_text='Qual è il ruolo di ADH?'), GeneratedMirata(type='mirata', question_text='Quando fu scoperto ADH?')]
    call = Mock(return_value=service.RuleCheck(rejected=[1, 100]))
    monkeypatch.setattr('rt.llm.client.LLMClient.call_structured', call)
    summary = {}
    assert service.filter_group(questions, ['Evita le date'], summary=summary) == questions[:1]
    assert summary['presave_discarded'] == 1 and call.call_count == 1
    cfg.recall.votes_enabled = False
    assert service.filter_group(questions, ['Evita le date']) == questions
    assert service.prepare('mirata', 'fake') == []
    cfg.recall.votes_enabled = True
    cfg.recall.presave_check = False
    assert service.filter_group(questions, ['Evita le date']) == questions
    assert call.call_count == 1


def test_rules_api_configuration_and_update_job(api_client, rt_db, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace
    from rt.services.jobs import DbJobQueue
    from rt.services.worker import Worker
    from rt.core.config import load_config
    isolated_workspace(tmp_path, monkeypatch)
    url = '/api/v1/settings/recall-rules'
    assert api_client.get(url).json() == {'votes_enabled': True, 'presave_check': True, 'groups': []}
    vote(lesson='lesson', unit_ids=['1.1'], reasons=['buona'], comment='Chiara')
    assert api_client.put(url, json={'type': 'mirata', 'subject': 'Medicina', 'rules': ['Regola manuale']}).status_code == 200
    response = api_client.put('/api/v1/settings/recall-votes', json={'votes_enabled': False, 'presave_check': False})
    assert response.status_code == 200
    assert not load_config().recall.votes_enabled and not load_config().recall.presave_check
    assert response.json()['groups'][0]['rules'] == ['Regola manuale']
    accepted = api_client.post(url + '/update', json={'type': 'mirata', 'subject': 'Medicina', 'mock': True})
    assert accepted.status_code == 202
    queue = DbJobQueue(rt_db)
    worker = Worker(queue, worker_id='rules-test')
    assert worker.run_once()
    job = queue.get(accepted.json()['job_id'])
    assert job.state == 'succeeded'
    group = api_client.get(url).json()['groups'][0]
    assert group['rules'] != ['Regola manuale'] and group['updated_at'] and group['votes'] == 1


def test_disabled_votes_omit_examples_and_rules_from_generation(cfg, tmp_path, monkeypatch):
    from tests.test_jev_prefilter import setup_mock_lesson
    from rt.core.models import RecallMirataGenerationResult
    path = setup_mock_lesson(tmp_path)
    cfg.recall.votes_enabled = False
    service.edit('mirata', '', ['NON DEVE APPARIRE'])
    prompts = []
    def generate(_client, **kwargs):
        prompts.append(kwargs['prompt'])
        return RecallMirataGenerationResult.model_validate({'questions': [{'type': 'mirata', 'question_text': 'Qual è il contenuto della unità?'}]})
    monkeypatch.setattr('rt.llm.client.LLMClient.call_structured', generate)
    questions = recall.generate_recall_batch(path, 'mirata', 1, [{'question_text': 'ESEMPIO SPENTO', 'vote': 'up'}])
    assert len(questions) == 1
    assert all('NON DEVE APPARIRE' not in prompt and 'ESEMPIO SPENTO' not in prompt for prompt in prompts)
