import pytest
from rt.pipeline.recall_checks import question_issue, variant_issue, evaluation_issue, percentage_outcome

MEDICINE = 'Acidosi metabolica, pH, PaCO2, HCO3 e compenso respiratorio. ADH e osmolarità plasmatica.'

@pytest.mark.parametrize('text', [
    "Cos'è ADH?", "Qual è il ruolo dell'ADH nell'osmolarità plasmatica?",
    'Un paziente con pH 7,20, PaCO2 25 mmHg e HCO3 10 mmol/L presenta quale disturbo acido-base?',
    'Descrivi il compenso respiratorio nella chetoacidosi diabetica con HCO3 12 mmol/L.',
    'Confronta acidosi metabolica e acidosi respiratoria rispetto alla variazione di PaCO2.',
])
def test_real_medical_italian_passes(text):
    assert question_issue({'question_text': text}, MEDICINE) is None

@pytest.mark.parametrize('text,reason', [
    ('ADH?', 'lunghezza'), ('Domanda 1: Qual è il ruolo di ADH?', 'segnaposto'),
    ('Qual è il ruolo di [...]?', 'segnaposto'), ('XXX determina il pH?', 'segnaposto'),
    ('What causes metabolic acidosis in patients?', 'lingua'),
    (('Il pH cambia nella acidosi. ' * 5), 'ripetizione'),
    ('Qual è la capitale della Francia?', 'pertinenza'),
])
def test_broken_questions_are_rejected(text, reason):
    assert question_issue({'question_text': text}, MEDICINE) == reason


def test_quiz_and_vasta_checks():
    q = dict(type='quiz', question_text="Qual è il ruolo dell'ADH?", options=['Riduce la diuresi', 'Aumenta la diuresi', 'Blocca il glucosio', 'Riduce il calcio'], correct_index=0)
    assert question_issue(q, MEDICINE) is None
    assert question_issue({**q, 'options': ['A', 'a ', 'C', 'D']}) == 'opzioni'
    assert question_issue({**q, 'correct_index': 4}) == 'indice'
    assert question_issue({**q, 'options': ['Risposta corretta molto lunga e riconoscibile che spiega tutta la fisiologia renale', 'B', 'C', 'D']}) == 'corretta troppo lunga'
    assert question_issue({'type': 'vasta', 'question_text': 'Descrivi il ruolo di ADH', 'pregenerated_material': ''}) == 'scaletta vuota'


def test_near_duplicates_are_unit_local_and_preserve_changed_clinical_values():
    old = 'Qual è il compenso respiratorio atteso nel paziente con acidosi metabolica e pH 7,20?'
    new = 'Nel paziente con acidosi metabolica e pH 7,20 qual è il compenso respiratorio atteso?'
    assert question_issue({'question_text': new}, previous=[old]) == 'quasi doppione'
    assert question_issue({'question_text': new.replace('7,20', '7,30')}, previous=[old]) is None


def test_variants_numbers_readable_ranges_and_results():
    tipo = {'variabili': [{'nome': 'pH', 'intervallo': '7,10–7,50'}]}
    q = {'question_text': 'Un paziente ha pH 7,30 e PaCO2 25 mmHg. Qual è il disturbo?', 'pregenerated_material': 'Il risultato è acidosi metabolica.'}
    assert variant_issue(q, tipo) is None
    assert variant_issue(q, tipo, [q['question_text'].replace('paziente', 'uomo')]) == 'numeri già usati'
    assert variant_issue({**q, 'question_text': q['question_text'].replace('7,30', '8,30')}, tipo) == 'fuori intervallo'
    assert variant_issue({**q, 'pregenerated_material': 'Applicare la formula.'}, tipo) == 'soluzione senza risultato'
    assert variant_issue({**q, 'pregenerated_material': None}, tipo) is None
    assert variant_issue(q, {'variabili': [{'nome': 'pH', 'intervallo': 'valori fisiologici'}]}) is None

@pytest.mark.parametrize('c,f,outcome', [(100,100,'corretta'), (85,85,'corretta'), (75,70,'parziale'), (0,0,'sbagliata'), (30,100,'sbagliata')])
def test_evaluation_coherence(c, f, outcome):
    assert percentage_outcome(c, f) == outcome
    assert evaluation_issue(dict(correttezza=c, completezza=f, commento='Manca il compenso respiratorio.', outcome=outcome)) is None
    assert evaluation_issue(dict(correttezza=c, completezza=f, commento=' ', outcome=outcome)) == 'commento vuoto'


def test_invalid_scores_and_outcome():
    assert evaluation_issue(dict(correttezza=101, completezza=50, commento='Ok', outcome='parziale')) == 'percentuali'
    assert evaluation_issue(dict(correttezza=0, completezza=0, commento='Errato', outcome='corretta')) == 'esito incoerente'


def test_evaluation_retries_once_and_derives_outcome():
    from unittest.mock import Mock
    from rt.pipeline.recall_checks import checked_evaluation
    from rt.llm.prompts import RecallEvalMirataResult
    broken = RecallEvalMirataResult(correttezza=20, completezza=10, commento='Errata', outcome='corretta')
    client = Mock()
    client.call_structured.side_effect = [broken, broken.model_copy()]
    result = checked_evaluation(client, response_model=RecallEvalMirataResult)
    assert result.outcome == 'sbagliata' and client.call_structured.call_count == 2
    client.call_structured.reset_mock()
    valid = broken.model_copy(update={'outcome': 'sbagliata'})
    client.call_structured.side_effect = [broken, valid]
    assert checked_evaluation(client, response_model=RecallEvalMirataResult) == valid
    assert client.call_structured.call_count == 2


def test_generation_notice_omits_zero_parts_and_reports_stop_and_discards():
    from rt.services.api_jobs import recall_generation_notice
    assert recall_generation_notice({}, 10, 10) == 'Generate 10 su 10.'
    text = recall_generation_notice({'local_discarded': 1, 'presave_discarded': 1, 'verification_discarded': 1}, 10, 6)
    assert text == 'Generate 6 su 10: il modello non ha trovato altri contenuti utili. 2 scartate dai controlli. 1 variante non ha superato la verifica.'
    assert 'tre passaggi' in recall_generation_notice({'stop_reason': 'max_rounds'}, 10, 3)
