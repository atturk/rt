"""Classificatore a etichette del registro: soglia, cache, materie e correzioni."""
from unittest.mock import patch

import pytest
from rt.core.config import RTConfig, RecallConfig, JevConfig, CustomQuestionType
from rt.llm.jev_client import JevResponse, JevChoiceAnswer
from rt.services import section_labels as labels, custom_question_types as registry, classifier_view
from tests.api_support import isolated_workspace
from tests.test_jev_prefilter import setup_mock_lesson
from tests.test_custom_question_types import definition


@pytest.fixture
def configured(tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = setup_mock_lesson(__import__('pathlib').Path(root), num_units=2)
    (__import__('pathlib').Path(path) / 'info.yaml').write_text('materia: Informatica\n')
    from rt.services.recall_context import lesson_context
    subject = lesson_context(path)['materia']
    types = [CustomQuestionType(**definition(materie=[subject])),
             CustomQuestionType(**definition(nome='Codice', materie=[subject], cerca='Programmi'))]
    cfg = RTConfig(jev=JevConfig(relevance_mode='shadow', relevance_model='typesafe/jev-1.13'),
                   recall=RecallConfig(custom_types=types))
    for module in (labels, registry, classifier_view):
        monkeypatch.setattr(module, 'load_config', lambda: cfg)
    return path, cfg


def response(probabilities):
    return JevResponse(model='mock', answers={'tipo': JevChoiceAnswer(
        choice=max(probabilities, key=probabilities.get), probabilities=probabilities, confidence=.9)})


def test_single_choice_multiple_types_and_none_margin(configured):
    path, cfg = configured
    with patch('rt.llm.jev_client.call_jev', return_value=response({'query-sql': .35, 'codice': .3, 'nessuno': .35})) as call:
        labels.refresh(path)
        assert all(row == {'query-sql': 'presente', 'codice': 'presente'} for row in labels.labels(path).values())
        assert all(len(c.kwargs['questions']) == 1 for c in call.call_args_list)
        assert set(call.call_args.kwargs['questions']['tipo'].criteria) == {'query-sql', 'codice', 'nessuno'}
        labels.refresh(path)
        assert call.call_count == len(labels.sections(path))
    with patch('rt.llm.jev_client.call_jev', return_value=response({'query-sql': .26, 'codice': .1, 'nessuno': .64})):
        labels.refresh(path, force=True)
        assert all(row == {'query-sql': 'nessuno', 'codice': 'nessuno'} for row in labels.labels(path).values())


def test_subject_without_types_does_not_call_classifier_or_add_rows(configured):
    path, cfg = configured
    for t in cfg.recall.custom_types:
        t.materie = ['Un’altra materia']
    with patch('rt.llm.jev_client.call_jev') as call:
        assert labels.refresh(path) == {}
        call.assert_not_called()
    assert not any(name.startswith('custom:') for name in classifier_view.overview(path)['jobs'])


def test_fingerprint_reclassifies_only_affected_subject_and_overrides_survive(configured):
    path, cfg = configured
    labels.refresh(path, force_mock=True)
    sid = labels.sections(path)[0]['id']
    labels.set_override(path, sid, 'query-sql', 'presente')
    initial = labels.configuration(path)
    cfg.recall.custom_types.append(CustomQuestionType(**definition(nome='Altro', materie=['Altrove'])))
    assert labels.configuration(path) == initial
    cfg.recall.custom_types[0].cerca = 'Nuovo criterio'
    assert labels.configuration(path) != initial
    labels.refresh(path, force_mock=True)
    assert labels.labels(path)[sid]['query-sql'] == 'presente'
    row = classifier_view.overview(path)['jobs']['custom:query-sql']
    assert row['nome'] == 'Query SQL' and row['icona'] == 'MessageSquare'
    assert row['cells'][0]['source'] == 'manual'
    with pytest.raises(ValueError):
        labels.set_override(path, sid, 'query-sql', 'svolto')


def test_mock_uses_words_of_name_and_text_change_invalidates_override(configured):
    from rt.pipeline.rewrite import load_draft, save_draft
    path, cfg = configured
    draft = load_draft(path)
    draft.units[0].content = 'Query SQL e codice della lezione.'
    save_draft(draft, path)
    labels.refresh(path, force_mock=True)
    sid = labels.sections(path)[0]['id']
    assert labels.labels(path)[sid] == {'query-sql': 'presente', 'codice': 'presente'}
    labels.set_override(path, sid, 'query-sql', 'nessuno')
    draft.units[0].content += ' Testo cambiato.'
    save_draft(draft, path)
    assert sid not in labels.labels(path)
    labels.refresh(path, force_mock=True)
    assert labels.labels(path)[sid]['query-sql'] == 'presente'
