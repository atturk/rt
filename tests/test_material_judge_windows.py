from types import SimpleNamespace

import pytest

from rt.core.config import ClassifierJob
from rt.llm.jev_client import JevNoulAnswer
from rt.pipeline.material_mapping import CandidateSubunit, PageSourceIdentity, classify_material_page, transcript_windows


def test_windows_find_relevant_late_passages_at_sentence_boundaries():
    unrelated = 'Una lunga introduzione descrive argomenti generali e informazioni amministrative. '
    relevant = 'La trombomodulina attiva la proteina C mediante un legame con la trombina. '
    transcript = unrelated * 40 + relevant * 5 + 'Conclusioni generali. '
    windows = transcript_windows('trombomodulina proteina trombina', transcript)
    assert len(windows) == 2
    assert any('trombomodulina' in window for window in windows)
    assert all(window.endswith('.') and len(window) <= 600 for window in windows)
    assert sum(len(window) for window in windows) < len(transcript)


@pytest.mark.parametrize('content_probability,placed', [(0.95, ['1.1']), (0.2, [])])
def test_content_question_shares_call_and_window_changes_invalidate_cache(tmp_path, monkeypatch, content_probability, placed):
    monkeypatch.setattr('rt.core.config.classifier_job', lambda *a: ClassifierJob(
        mode='manual', model='mock-judge', credential='mock', timeout_seconds=10))
    monkeypatch.setattr('rt.llm.client.LLMClient', lambda **k: SimpleNamespace(force_mock=False))
    calls = []
    def decision(state, questions, **kwargs):
        calls.append(state)
        assert len(questions) == 2
        question = questions['didactic_content'].instructions
        for word in ['copertina', 'titolo', 'indice', 'scaletta', 'ringraziamenti', 'vignette', 'decorative']:
            assert word in question
        return SimpleNamespace(answers={key: JevNoulAnswer(noul=content_probability if key == 'didactic_content' else .95)
                                        for key in questions})
    monkeypatch.setattr('rt.services.enrichment_service.decision', decision)
    page = {'numero': 1, 'testo': 'Trombomodulina e proteina C'}
    candidate = CandidateSubunit('1.1', '1', 'Coagulazione', 'La trombomodulina attiva la proteina C.', 1.)
    cache = {}
    source = PageSourceIdentity('source', 'hash')
    def classify():
        return classify_material_page(page, [candidate], source, str(tmp_path), cache)
    assert classify() == (placed, [])
    assert classify() == (placed, [])
    assert len(calls) == 1
    candidate.transcript += ' La proteina C degrada i fattori attivati.'
    assert classify() == (placed, [])
    assert len(calls) == 2


@pytest.mark.parametrize('probabilities,expected', [
    ([.71, .75, .4, .2], (['1.2'], [])),
    ([.85, .9, .82, .2], ([], ['1'])),
    ([.85, .86, .87, .95], (['2.1'], [])),
])
def test_one_destination_with_best_probability_and_macro_aggregation(tmp_path, monkeypatch, probabilities, expected):
    monkeypatch.setattr('rt.llm.client.LLMClient', lambda **k: SimpleNamespace(force_mock=False))
    candidates = [CandidateSubunit(uid, uid.split('.')[0], uid, 'Parlato.', 1.)
                  for uid in ['1.1', '1.2', '1.3', '2.1']]
    def decision(state, questions, **kwargs):
        answers = {'didactic_content': JevNoulAnswer(noul=.95)}
        answers.update({f"unit_{c.unit_id.replace('.', '_')}": JevNoulAnswer(noul=p)
                        for c, p in zip(candidates, probabilities)})
        return SimpleNamespace(answers=answers)
    monkeypatch.setattr('rt.services.enrichment_service.decision', decision)
    assert classify_material_page({'numero': 1, 'testo': 'Contenuto didattico'}, candidates,
                                  PageSourceIdentity('src', 'hash'), str(tmp_path), {}) == expected
