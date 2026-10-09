"""Migrazione dei modelli storici e modalità indipendenti."""
import pytest
from rt.core.config import RTConfig, ClassifierConfig, classifier_job
from tests.api_support import isolated_workspace


@pytest.mark.parametrize('relevance,model,expected', [('disabled','m','off'),('shadow','','off'),('shadow','m','observe'),('active','m','pipeline')])
@pytest.mark.parametrize('enabled,shadow,prefilter', [(False,False,'off'),(True,True,'observe'),(True,False,'pipeline')])
@pytest.mark.parametrize('enrichment,expected_enrichment', [('disabled','off'),('manual','manual'),('automatic','pipeline')])
def test_migration(relevance, model, expected, enabled, shadow, prefilter, enrichment, expected_enrichment):
    cfg = RTConfig.model_validate({'jev': {'relevance_mode': relevance, 'relevance_model': model, 'enabled': enabled, 'shadow': shadow}, 'enrichment': {'mode': enrichment, 'decision_model': 'altro'}})
    assert classifier_job(cfg, 'relevance').mode == expected
    assert classifier_job(cfg, 'question_types').mode == ('off' if expected == 'off' else 'pipeline')
    assert classifier_job(cfg, 'prefilter').mode == prefilter
    assert classifier_job(cfg, 'drift').mode == prefilter
    assert classifier_job(cfg, 'enrichment').mode == expected_enrichment
    assert classifier_job(cfg, 'enrichment').model == 'altro'


def test_new_configuration_and_independent_jobs(monkeypatch):
    from rt.services import question_types, section_labels, unit_relevance
    cfg = RTConfig(classifier=ClassifierConfig(model='shared', jobs={'relevance': {'mode':'off'}, 'question_types': {'mode':'pipeline', 'model':'own'}, 'section_labels': {'mode':'pipeline'}}))
    for service in (question_types, section_labels, unit_relevance):
        monkeypatch.setattr(service, 'load_config', lambda: cfg)
    assert unit_relevance.mode() == 'disabled'
    assert question_types.enabled()
    assert section_labels.mode() == 'active'
    assert classifier_job(cfg,'question_types').model == 'own'
    assert classifier_job(cfg,'section_labels').model == 'shared'
    with pytest.raises(ValueError):
        ClassifierConfig(jobs={'images': {'mode':'pipeline'}})


def test_settings_classifier_requires_probe_and_cleans_legacy(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    path = '/api/v1/settings/classifier'
    body = api_client.get(path).json()
    body.update(model='new-model', jobs={'relevance': {'mode':'observe'}})
    assert api_client.put(path, json=body).status_code == 422
    from rt.services.jev_playground import record_probe
    record_probe(body['credential'], body['model'], 'score')
    assert api_client.put(path, json=body).status_code == 200
    assert api_client.get(path).json()['model'] == 'new-model'
    from tests.test_decision_model_settings import _general
    saved = _general()
    assert 'classifier' in saved and 'model' not in saved['jev']
    assert 'mode' not in saved['enrichment']
