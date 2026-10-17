"""Controlli prudenti del recall: solo anomalie chiare, nessuna chiamata ai modelli."""
import re
from collections import Counter

# Otto caratteri ammettono domande brevi con sigle (es. «Cos'è ADH?»).
MIN_QUESTION_CHARS = 8
# Tracce cliniche e problemi possono essere lunghi: scartiamo solo output enormi.
MAX_QUESTION_CHARS = 12000
# Lingua: si scarta solo un testo abbastanza lungo da giudicare, senza parole italiane comuni
# e con almeno una parola inglese comune. Le domande telegrafiche («Valori normali HbA1c?»)
# e il lessico medico passano sempre.
MIN_LANGUAGE_WORDS = 5
MIN_ENGLISH_MARKERS = 1
# Quattro ripetizioni consecutive di un blocco di 5 parole indicano un loop evidente.
REPEATED_NGRAM_SIZE = 5
MAX_NGRAM_REPEATS = 4
# Somiglianza molto alta e almeno 8 parole: non confondere domande brevi sullo stesso tema.
DUPLICATE_JACCARD = .94
MIN_DUPLICATE_WORDS = 8
# Tre lettere per parole comuni; due per sigle come pH e Na, che sono informative.
MIN_KEYWORD_CHARS = 3
MIN_ACRONYM_CHARS = 2
# Una sola parola significativa in comune: controllo grezzo, volutamente permissivo.
MIN_RELEVANT_WORDS = 1
# 1,8 segnala una risposta insolitamente prolissa; ignoriamo opzioni sotto 40 caratteri.
MAX_CORRECT_OPTION_RATIO = 1.8
MIN_LONG_OPTION_CHARS = 40
# Solo contraddizioni nette fra esito e punteggi: «corretta» con correttezza sotto 40,
# «sbagliata» con entrambi i punteggi da 85 in su. Gli stessi valori ricavano l'esito mancante.
CORRECT_PERCENT = 85
WRONG_PERCENT = 40

COMMON = set("il lo la i gli le un uno una di del della dei delle da dal dalla in nel nella con su per tra fra e o ma che a al alla è sono si non come quale quali cosa cos perché quando quanto dove ha hanno essere viene vengono può possono questo questa questi queste descrivi spiega indica confronta descrivere spiegare caratterizza determina calcola ruolo rapporto secondo rispetto durante dopo prima senza ad ogni più meno se ed oppure sia anche nel negli nelle dell all d l".split())
ITALIAN_MARKERS = COMMON - {"a", "in", "i", "come", "si", "non", "per", "e", "o", "ha", "su", "l", "d"}
ENGLISH_MARKERS = set("the of which what is are and with for this that how why does from".split())
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?")
PLACEHOLDER = re.compile(r"\[\s*\.\.\.\s*\]|\bXXX\b|\blorem\b|^\s*Domanda\s+\d+\s*:", re.I)


def words(text):
    return WORD.findall(text.casefold())


def keywords(text):
    return {w.casefold() for w in WORD.findall(text)
            if w.casefold() not in COMMON and (len(w) >= MIN_KEYWORD_CHARS
                or (len(w) >= MIN_ACRONYM_CHARS and not w.islower()))}


def numbers(text):
    return tuple(float(n.replace(',', '.')) for n in NUMBER.findall(text))


def question_issue(question, unit_text='', previous=(), *, variant=False):
    """Restituisce il motivo del primo scarto, oppure None. Accetta modelli o dict."""
    data = question if isinstance(question, dict) else question.model_dump()
    text = data.get('question_text', '').strip()
    if not MIN_QUESTION_CHARS <= len(text) <= MAX_QUESTION_CHARS:
        return 'lunghezza'
    if PLACEHOLDER.search(text):
        return 'segnaposto'
    tokens = words(text)
    if not tokens:
        return 'lingua'
    if (len(tokens) >= MIN_LANGUAGE_WORDS and not any(t in ITALIAN_MARKERS for t in tokens)
            and sum(t in ENGLISH_MARKERS for t in tokens) >= MIN_ENGLISH_MARKERS):
        return 'lingua'
    grams = Counter(tuple(tokens[i:i + REPEATED_NGRAM_SIZE])
                    for i in range(len(tokens) - REPEATED_NGRAM_SIZE + 1))
    if grams and max(grams.values()) >= MAX_NGRAM_REPEATS:
        return 'ripetizione'
    material = data.get('pregenerated_material') or ''
    if data.get('type') == 'vasta' and not material.strip():
        return 'scaletta vuota'
    if data.get('type') == 'quiz':
        options = data.get('options') or []
        normalized = [s.strip().casefold() for s in options]
        index = data.get('correct_index')
        if len(options) != 4 or not all(normalized) or len(set(normalized)) != 4:
            return 'opzioni'
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < 4:
            return 'indice'
        correct = len(options[index].strip())
        others = [len(s.strip()) for i, s in enumerate(options) if i != index]
        if correct > MIN_LONG_OPTION_CHARS and correct > max(others) and correct > MAX_CORRECT_OPTION_RATIO * (sum(others) / 3):
            return 'corretta troppo lunga'
    relevant = keywords(unit_text)
    if not variant and relevant and len(relevant & keywords(text + ' ' + material)) < MIN_RELEVANT_WORDS:
        return 'pertinenza'
    current = set(tokens)
    for old in previous:
        old_text = old if isinstance(old, str) else old.question_text
        other = set(words(old_text))
        if text.casefold() == old_text.strip().casefold():
            return 'doppione'
        if variant:
            # Le varianti hanno per definizione parole simili: i valori le distinguono.
            continue
        if min(len(current), len(other)) >= MIN_DUPLICATE_WORDS and len(current & other) / len(current | other) > DUPLICATE_JACCARD:
            # Dati numerici diversi possono cambiare la risposta a una domanda clinica.
            if numbers(text) == numbers(old_text):
                return 'quasi doppione'
    return None


def variant_issue(question, template, previous=()):
    data = question if isinstance(question, dict) else question.model_dump()
    issue = question_issue(data, previous=previous, variant=True)
    if issue:
        return issue
    values = numbers(data['question_text'])
    for old in previous:
        old_text = old if isinstance(old, str) else old.question_text
        if values and values == numbers(old_text):
            return 'numeri già usati'
    tipo = template if isinstance(template, dict) else template.model_dump()
    for variable in tipo.get('variabili', []):
        interval = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*[–—-]\s*(\d+(?:[.,]\d+)?)\s*', variable.get('intervallo', ''))
        if not interval:
            continue
        low, high = (float(x.replace(',', '.')) for x in interval.groups())
        # Solo valori esplicitamente associati al nome: non confrontare età e pH.
        name = variable.get('nome', '')
        if not name:
            continue
        match = re.search(r'\b' + re.escape(name) + r'\s*(?:[:=]|di|è)?\s*([-+]?\d+(?:[.,]\d+)?)', data['question_text'], re.I)
        if match and not low <= float(match.group(1).replace(',', '.')) <= high:
            return 'fuori intervallo'
    solution = data.get('pregenerated_material')
    if solution is not None and (not solution.strip() or not re.search(r'\d|risultat|conclus|diagnos|quindi|pertanto|=|acidosi|alcalosi', solution, re.I)):
        return 'soluzione senza risultato'
    return None


def percentage_outcome(correctness, completeness):
    if correctness < WRONG_PERCENT:
        return 'sbagliata'
    if min(correctness, completeness) >= CORRECT_PERCENT:
        return 'corretta'
    return 'parziale'


def evaluation_issue(result):
    data = result if isinstance(result, dict) else result.model_dump()
    scores = [data.get(k) for k in ('correttezza', 'completezza')]
    if any(not isinstance(s, (int, float)) or isinstance(s, bool) or not 0 <= s <= 100 for s in scores):
        return 'percentuali'
    if not data.get('commento', '').strip():
        return 'commento vuoto'
    outcome = data.get('outcome')
    if ((outcome == 'corretta' and scores[0] < WRONG_PERCENT)
            or (outcome == 'sbagliata' and min(scores) >= CORRECT_PERCENT)):
        return 'esito incoerente'
    return None


def checked_evaluation(client, *, dont_know=False, **kwargs):
    """Riprova una volta; dopo deriva l'esito dai punteggi invece di fidarsi del modello."""
    from pydantic import ValidationError
    result = None
    for _ in range(2):
        try:
            result = client.call_structured(**kwargs)
        except ValidationError:
            continue
        if dont_know:
            result.correttezza = result.completezza = 0
            result.outcome = 'sbagliata'
        if not evaluation_issue(result):
            if result.outcome is None:  # esito mancante: si ricava dai punteggi, senza riprovare
                result.outcome = percentage_outcome(result.correttezza, result.completezza)
            return result
    if result is None:
        result = kwargs['response_model'].model_construct(correttezza=0, completezza=0,
            commento='Il modello non ha restituito una valutazione valida.', outcome='sbagliata')
    result.correttezza = min(100, max(0, result.correttezza))
    result.completezza = min(100, max(0, result.completezza))
    if result.outcome is None or evaluation_issue(result) == 'esito incoerente':
        result.outcome = percentage_outcome(result.correttezza, result.completezza)
    if not result.commento.strip():
        result.commento = 'Valutazione ricavata dalle percentuali restituite dal modello.'
    return result
