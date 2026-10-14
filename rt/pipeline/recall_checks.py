"""Controlli prudenti del recall: solo anomalie chiare, nessuna chiamata ai modelli."""
import re
from collections import Counter

# Otto caratteri ammettono domande brevi con sigle (es. «Cos'è ADH?»).
MIN_QUESTION_CHARS = 8
# Tracce cliniche e problemi possono essere lunghi: scartiamo solo output enormi.
MAX_QUESTION_CHARS = 12000
# Una parola italiana ogni 100 basta: sigle e lessico medico non sono un dizionario.
MIN_ITALIAN_RATIO = .01
# Quattro ripetizioni consecutive di un blocco di 5 parole indicano un loop evidente.
REPEATED_NGRAM_SIZE = 5
MAX_NGRAM_REPEATS = 4
# Somiglianza molto alta e almeno 8 parole: non confondere domande brevi sullo stesso tema.
DUPLICATE_JACCARD = .94
MIN_DUPLICATE_WORDS = 8
# Una sola parola significativa in comune: controllo grezzo, volutamente permissivo.
MIN_RELEVANT_WORDS = 1
# 1,8 segnala una risposta insolitamente prolissa; ignoriamo opzioni sotto 40 caratteri.
MAX_CORRECT_OPTION_RATIO = 1.8
MIN_LONG_OPTION_CHARS = 40
# Esito coerente coi due punteggi: entrambi >=85 corretta, correttezza <40 sbagliata.
CORRECT_PERCENT = 85
WRONG_PERCENT = 40

COMMON = set("il lo la i gli le un uno una di del della dei delle da dal dalla in nel nella con su per tra fra e o ma che a al alla è sono si non come quale quali cosa cos perché quando quanto dove ha hanno essere viene vengono può possono questo questa questi queste descrivi spiega indica confronta descrivere spiegare caratterizza determina calcola ruolo rapporto secondo rispetto durante dopo prima senza ad ogni più meno se ed oppure sia anche nel negli nelle dell all d l".split())
ITALIAN_MARKERS = COMMON - {"a", "in", "i", "come", "si", "non", "per", "e", "o", "ha", "su", "l", "d"}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?")
PLACEHOLDER = re.compile(r"\[\s*\.\.\.\s*\]|\bXXX\b|\blorem\b|^\s*Domanda\s+\d+\s*:", re.I)


def words(text):
    return WORD.findall(text.casefold())


def keywords(text):
    return {w for w in words(text) if len(w) >= 3 and w not in COMMON}


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
    if not tokens or sum(t in ITALIAN_MARKERS for t in tokens) / len(tokens) < MIN_ITALIAN_RATIO:
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
    if data.get('outcome') != percentage_outcome(*scores):
        return 'esito incoerente'
    return None
