"""
rt.services.jev_mapping
Domande Jev configurabili per fase e mappatura della risposta sulle etichette di RT.

- effective_decision(): la configurazione in uso (salvata dal playground o predefinita,
  derivata dai campi storici di JevConfig così che nulla cambi finché l'utente non modifica).
- template(): la domanda predefinita di una fase per un tipo di richiesta (choice/noul/score).
- build_question() / state_for(): cosa si invia a Jev.
- evaluate(): regole valutate in ordine, vince la prima vera; nessuna regola vera, o risposta
  non valutabile, porta all'esito fail-open della fase (unità inclusa / review eseguita).
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from rt.core.jev_decision import (
    FALLBACK_OUTCOME, PROBABILITY_PREFIX, JevCondition, JevDecisionConfig, JevOption, JevRule,
)

# ---------------------------------------------------------------- rilevanza (gate delle unità)

RELEVANCE_CRITERIA = {
    "didactic": "Contiene anche una sola nozione, definizione, relazione, spiegazione o esempio disciplinare utile allo studio; include introduzioni con contenuto e unità miste o dubbie.",
    "organizational": "Contiene solo calendario, modalità d'esame, materiali, ricevimento, contatti, presentazione del corso o altre comunicazioni organizzative, senza nozioni disciplinari.",
    "no_content": "Contiene solo saluti, convenevoli, prove audio, pause, interruzioni o conversazione senza nozioni né informazioni organizzative utili.",
}
RELEVANCE_INSTRUCTIONS = (
    "Classifica una singola unità riscritta di una lezione universitaria per review e domande di ripasso. "
    "Valuta il contenuto effettivo, non il titolo o la posizione: un'introduzione può insegnare nozioni. "
    "Se è presente anche un contenuto didattico sostanziale, scegli didactic. In caso di dubbio "
    "scegli didactic per evitare omissioni. Restituisci solo la scelta tra i criteri."
    " Esempi: presentazione personale o composizione della classe senza nozioni → no_content; "
    "verifica audio e saluti → no_content; rose, date di esame, sede, indirizzo e ricevimento → organizational; "
    "una spiegazione dei principi di diritto o dell'articolo 32, anche dopo l'introduzione logistica → didactic."
)
_RELEVANCE_PROBABILITY = (
    "Valuta una singola unità riscritta di una lezione universitaria. Stima la probabilità che l'unità "
    "NON contenga alcuna nozione didattica (solo informazioni organizzative, saluti, prove audio o "
    "conversazione). Un'introduzione con contenuto disciplinare è didattica. In caso di dubbio la "
    "probabilità deve essere bassa, per evitare omissioni."
)

# ---------------------------------------------------------------- prefiltro errori (prima della review)

PREFILTER_INSTRUCTIONS = (
    "Sei un revisore scientifico che classifica un singolo paragrafo di prosa "
    "accademica (già rielaborato da una trascrizione di lezione universitaria) "
    "in base alla gravità di eventuali errori scientifici presenti, SENZA accesso "
    "alla trascrizione originale. Non correggere il testo: classifica solo la "
    "gravità di ciò che vi leggi. Ignora eventuali refusi isolati o termini "
    "graficamente sospetti che sembrano artefatti di trascrizione automatica (ASR) "
    "non ancora corretti: non è compito tuo, e non contano come errore scientifico "
    "se isolati e privi di altro significato rilevante."
)
PREFILTER_CRITERIA = {
    "corretta": (
        "Il testo è scientificamente corretto, oppure contiene al più imprecisioni "
        "terminologiche irrilevanti che non cambiano il significato concettuale."
    ),
    "imprecisione": (
        "Il testo contiene una semplificazione o approssimazione minore, di nessuna "
        "reale conseguenza per la preparazione dell'esame — ad esempio una "
        "generalizzazione innocua o un dettaglio tecnico secondario reso in modo "
        "impreciso (es. descrivere come lo stesso enzima due isoforme distinte che "
        "catalizzano reazioni analoghe). Non merita una segnalazione: correggerla "
        "sarebbe pignoleria controproducente."
    ),
    "errore_grave": (
        "Il testo contiene un errore concettuale che potrebbe genuinamente "
        "confondere uno studente durante il ripasso attivo, generare domande di "
        "richiamo fuorvianti, o riflette un vero fraintendimento concettuale del "
        "docente — ad esempio confondere due strutture anatomicamente distinte in "
        "un modo che genera vera confusione (es. dire 'carotide' intendendo "
        "'coronaria'), oppure affermare con sicurezza il contrario di un fatto "
        "consolidato e ben noto (es. sostenere che i bastoncelli sono meno numerosi "
        "dei coni, quando è vero il contrario)."
    ),
}

QUESTION_NAMES = {"relevance": "rilevanza", "prefilter": "correttezza"}
OUTCOME_LABELS = {
    "didactic": "Includi · didattica",
    "organizational": "Escludi · organizzativa",
    "no_content": "Escludi · senza contenuto",
    "skip_review": "Salta la review",
    "needs_review": "Esegui la review",
}
SAMPLE_UNITS = {
    "relevance": ("Esempio", "Buongiorno a tutti, prima di cominciare: l'esame sarà il 12 giugno in aula 3, "
                              "iscrivetevi entro il 5. Il ricevimento è il martedì alle 14."),
    "prefilter": ("Esempio", "I bastoncelli sono meno numerosi dei coni e sono responsabili della visione "
                              "dei colori in condizioni di luce intensa."),
}


def _cond(field_name: str, op: str, value) -> JevCondition:
    return JevCondition(field=field_name, op=op, value=value)


def _options(criteria: Dict[str, str]):
    return [JevOption(label=label, description=text) for label, text in criteria.items()]


def _with_extra(text: str, extra: str) -> str:
    return text + ("\n" + extra if extra else "")


def template(phase: str, question_type: str, jev_cfg) -> JevDecisionConfig:
    """Domanda e mappatura predefinite di una fase per un tipo di richiesta. Con il tipo storico
    (choice per la rilevanza, prefilter_type per il prefiltro) riproducono esattamente il
    comportamento precedente al playground, soglie e istruzioni aggiuntive comprese."""
    if phase == "relevance":
        threshold = jev_cfg.relevance_threshold
        extra = jev_cfg.relevance_prompt
        if question_type == "choice":
            return JevDecisionConfig(
                question=_with_extra(RELEVANCE_INSTRUCTIONS, extra), type="choice",
                options=_options(RELEVANCE_CRITERIA), fallback_label="Didattica",
                rules=[JevRule(label="Organizzativa", outcome="organizational",
                               conditions=[_cond("choice", "eq", "organizational"), _cond("confidence", "gte", threshold)]),
                       JevRule(label="Senza contenuto", outcome="no_content",
                               conditions=[_cond("choice", "eq", "no_content"), _cond("confidence", "gte", threshold)])])
        if question_type == "noul":
            return JevDecisionConfig(
                question=_with_extra(_RELEVANCE_PROBABILITY, extra), type="noul", fallback_label="Didattica",
                rules=[JevRule(label="Non didattica", outcome="no_content", conditions=[_cond("noul", "gte", threshold)])])
        return JevDecisionConfig(
            question=_with_extra(_RELEVANCE_PROBABILITY, extra), type="score", fallback_label="Didattica",
            levels=["Probabilità che l'unità sia priva di contenuto didattico (0 = sicuramente didattica, 1 = sicuramente non didattica)."],
            rules=[JevRule(label="Non didattica", outcome="no_content", conditions=[_cond("score", "gte", threshold)])])

    threshold = jev_cfg.task_a_skip_confidence_threshold
    extra = jev_cfg.prefilter_prompt
    # noul e score stimano la probabilità di un errore grave: si salta la review solo se
    # P(nessun errore grave) = 1 - p raggiunge la soglia di confidenza (0.85 → p ≤ 0.15).
    max_error = round(1 - threshold, 10)
    if question_type == "choice":
        return JevDecisionConfig(
            question=_with_extra(PREFILTER_INSTRUCTIONS, extra), type="choice",
            options=_options(PREFILTER_CRITERIA), fallback_label="Da revisionare",
            rules=[JevRule(label="Nessun errore grave", outcome="skip_review",
                           conditions=[_cond("choice", "ne", "errore_grave"), _cond("confidence", "gte", threshold)])])
    if question_type == "noul":
        return JevDecisionConfig(
            question=_with_extra(PREFILTER_INSTRUCTIONS + " Stima la probabilità che sia presente un errore concettuale grave, da 0 a 1.", extra),
            type="noul", fallback_label="Da revisionare",
            rules=[JevRule(label="Nessun errore grave", outcome="skip_review", conditions=[_cond("noul", "lte", max_error)])])
    return JevDecisionConfig(
        question=PREFILTER_INSTRUCTIONS + " Assegna un punteggio 0–1 alla probabilità di errore grave.",
        type="score", fallback_label="Da revisionare",
        levels=["Probabilità di un errore concettuale grave (0 = assente, 1 = certo)." +
                (" Istruzioni aggiuntive: " + extra if extra else "")],
        rules=[JevRule(label="Nessun errore grave", outcome="skip_review",
                       conditions=[_cond("score", "gte", 0.0), _cond("score", "lte", max_error)])])


def default_decision(phase: str, jev_cfg) -> JevDecisionConfig:
    """La decisione predefinita: quella in uso prima del playground."""
    return template(phase, "choice" if phase == "relevance" else jev_cfg.prefilter_type, jev_cfg)


def effective_decision(phase: str, jev_cfg) -> JevDecisionConfig:
    stored = jev_cfg.relevance_decision if phase == "relevance" else jev_cfg.prefilter_decision
    return stored if stored is not None else default_decision(phase, jev_cfg)


def is_default(phase: str, decision: JevDecisionConfig, jev_cfg) -> bool:
    return decision.model_dump() == default_decision(phase, jev_cfg).model_dump()


def build_question(decision: JevDecisionConfig):
    from rt.llm.jev_client import JevChoiceQuestion, JevNoulQuestion, JevScoreQuestion
    if decision.type == "choice":
        return JevChoiceQuestion(instructions=decision.question, criteria=decision.payload_criteria())
    if decision.type == "score":
        return JevScoreQuestion(instructions=decision.question, criteria=decision.payload_criteria())
    return JevNoulQuestion(instructions=decision.question)


def state_for(phase: str, title: str, content: str) -> str:
    """Lo stato inviato a Jev: il prefiltro vede SOLO il testo rielaborato dell'unità."""
    if phase == "relevance":
        return f"Titolo: {title}\nTesto: {content}"
    return content


# ---------------------------------------------------------------- valutazione

@dataclass
class DecisionResult:
    label: str
    outcome: str
    rule: Optional[int]  # indice (da 0) della regola scattata, None = nessuna (fail-open)
    answer: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "outcome": self.outcome, "rule": self.rule, "answer": self.answer}


def answer_dict(answer) -> Dict[str, Any]:
    return answer.model_dump() if hasattr(answer, "model_dump") else dict(answer or {})


def field_value(answer: Dict[str, Any], name: str):
    if name.startswith(PROBABILITY_PREFIX):
        probabilities = answer.get("probabilities") or {}
        return probabilities.get(name[len(PROBABILITY_PREFIX):]) if isinstance(probabilities, dict) else None
    return answer.get(name)


def compare(actual, op: str, expected) -> bool:
    """Confronto robusto: un campo mancante o non numerico non soddisfa mai la condizione."""
    if actual is None:
        return False
    if isinstance(expected, str):
        if op == "eq":
            return str(actual) == expected
        if op == "ne":
            return str(actual) != expected
        return False
    try:
        number, target = float(actual), float(expected)
    except (TypeError, ValueError):
        return False
    if isinstance(actual, bool) or not math.isfinite(number):
        return False
    equal = math.isclose(number, target, rel_tol=0.0, abs_tol=1e-9)
    return {"eq": equal, "ne": not equal, "gt": number > target and not equal,
            "gte": number >= target or equal, "lt": number < target and not equal,
            "lte": number <= target or equal}.get(op, False)


def rule_matches(rule: JevRule, answer: Dict[str, Any]) -> bool:
    results = (compare(field_value(answer, c.field), c.op, c.value) for c in rule.conditions)
    return all(results) if rule.match == "all" else any(results)


def evaluate(phase: str, decision: JevDecisionConfig, answer) -> DecisionResult:
    data = answer_dict(answer)
    if data.get("type") == decision.type:
        for index, rule in enumerate(decision.rules):
            if rule_matches(rule, data):
                return DecisionResult(label=rule.label, outcome=rule.outcome, rule=index, answer=data)
    return DecisionResult(label=decision.fallback_label, outcome=FALLBACK_OUTCOME[phase], rule=None, answer=data)


def describe(result: DecisionResult) -> str:
    """Riga leggibile per i log dei job: etichetta, esito e tutte le probabilità."""
    answer = result.answer
    parts = [f"{result.label} ({OUTCOME_LABELS.get(result.outcome, result.outcome)})"]
    if answer.get("type") == "choice":
        parts.append(f"scelta {answer.get('choice')}")
    elif answer.get("type") == "score":
        parts.append(f"punteggio {answer.get('score')}")
    elif answer.get("type") == "noul":
        parts.append(f"probabilità {_fmt(answer.get('noul'))}")
    if answer.get("confidence") is not None:
        parts.append(f"confidenza {_fmt(answer.get('confidence'))}")
    probabilities = answer.get("probabilities") or {}
    if probabilities:
        parts.append("probabilità: " + ", ".join(f"{k} {_fmt(v)}" for k, v in probabilities.items()))
    return " · ".join(parts)


def _fmt(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
