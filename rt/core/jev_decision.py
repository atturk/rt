"""
rt.core.jev_decision
Configurazione di una decisione Jev per fase (gate di rilevanza, prefiltro errori): la
domanda inviata a Jev (testo, tipo, opzioni o livelli) e la mappatura dalla risposta di
Jev alle etichette di RT, con le regole convalidate qui una volta per tutte.

Solo modelli e validazione: nessuna chiamata di rete, nessun import pesante (lo importa
rt.core.config). La valutazione delle regole e i default sono in rt.services.jev_mapping.
"""

import math
import re
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

JevPhase = Literal["relevance", "prefilter"]
QuestionType = Literal["choice", "noul", "score"]
Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte"]

# Esiti di RT per fase: le etichette scelte dall'utente devono ricadere su uno di questi.
# Rilevanza: le stesse classi di unit_relevance.json (correzioni umane e pagina di verifica).
PHASE_OUTCOMES: Dict[str, Tuple[str, ...]] = {
    "relevance": ("didactic", "organizational", "no_content"),
    "prefilter": ("skip_review", "needs_review"),
}
# Esito quando nessuna regola scatta (o la risposta non è valutabile): sempre fail-open.
FALLBACK_OUTCOME: Dict[str, str] = {"relevance": "didactic", "prefilter": "needs_review"}

NUMERIC_OPERATORS = ("eq", "ne", "gt", "gte", "lt", "lte")
TEXT_OPERATORS = ("eq", "ne")
PROBABILITY_PREFIX = "p:"
_LABEL_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def answer_fields(question_type: str, options: List[str]) -> Dict[str, str]:
    """Campi della risposta Jev confrontabili nelle regole, con il loro tipo ("text"/"number").
    noul restituisce solo la probabilità; choice e score anche la confidenza."""
    if question_type == "choice":
        fields = {"choice": "text", "confidence": "number"}
        fields.update({PROBABILITY_PREFIX + label: "number" for label in options})
        return fields
    if question_type == "score":
        return {"score": "number", "confidence": "number"}
    return {"noul": "number"}


class JevOption(BaseModel):
    """Un'opzione di una domanda choice: l'etichetta restituita dal classificatore e quando sceglierla."""
    label: str = Field(description="Etichetta restituita dal classificatore (lettere, cifre, _ e -)")
    description: str = Field(min_length=1, max_length=4000, description="Quando scegliere questa opzione")

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        value = value.strip()
        if not _LABEL_RE.match(value):
            raise ValueError("L'etichetta di un'opzione può contenere solo lettere, cifre, _ e - (max 40).")
        return value


class JevCondition(BaseModel):
    """Una condizione: [campo della risposta] [operatore] [valore]."""
    field: str = Field(description="choice, confidence, noul, score o p:<opzione>")
    op: Operator = "eq"
    value: Union[float, str]

    @field_validator("value")
    @classmethod
    def _finite(cls, value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Valore numerico non valido.")
        return value


class JevRule(BaseModel):
    """Una riga della mappatura: l'etichetta RT assegnata quando le condizioni sono vere."""
    label: str = Field(min_length=1, max_length=80, description="Etichetta mostrata in anteprima")
    outcome: str = Field(description="Esito di RT a cui corrisponde l'etichetta")
    match: Literal["all", "any"] = Field("all", description="Tutte le condizioni o almeno una")
    conditions: List[JevCondition] = Field(min_length=1, max_length=20)


class JevDecisionConfig(BaseModel):
    """Domanda del classificatore e mappatura verso le etichette RT di una fase."""
    question: str = Field(min_length=1, max_length=20000, description="Testo della domanda (istruzioni)")
    type: QuestionType = "choice"
    options: List[JevOption] = Field(default_factory=list, max_length=12, description="Opzioni (solo choice)")
    levels: List[str] = Field(default_factory=list, max_length=12, description="Livelli ordinati (solo score)")
    recall_richness: bool = Field(False, description="Associa esplicitamente i tre livelli score 0/1/2 alla ricchezza del recall")
    rules: List[JevRule] = Field(default_factory=list, max_length=20, description="Regole valutate in ordine: vince la prima vera")
    fallback_label: str = Field("Nessuna regola", min_length=1, max_length=80,
                                description="Etichetta quando nessuna regola scatta (esito fail-open)")

    @field_validator("levels")
    @classmethod
    def _levels(cls, values: List[str]) -> List[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 4000 for value in cleaned):
            raise ValueError("Ogni livello deve avere una descrizione (max 4000 caratteri).")
        return cleaned

    @model_validator(mode="after")
    def _consistent(self) -> "JevDecisionConfig":
        labels = [option.label for option in self.options]
        if self.type == "choice":
            if len(labels) < 2:
                raise ValueError("Una domanda choice richiede almeno due opzioni.")
            if len(set(labels)) != len(labels):
                raise ValueError("Le etichette delle opzioni devono essere distinte.")
        if self.type == "score" and not self.levels:
            raise ValueError("Una domanda score richiede almeno un livello.")
        if self.recall_richness and (self.type != "score" or len(self.levels) != 3):
            raise ValueError("La ricchezza del recall richiede tre livelli score.")
        fields = answer_fields(self.type, labels)
        for index, rule in enumerate(self.rules, start=1):
            for condition in rule.conditions:
                kind = fields.get(condition.field)
                if kind is None:
                    raise ValueError(f"Regola {index}: il campo '{condition.field}' non esiste in una risposta {self.type}.")
                if kind == "text":
                    if condition.op not in TEXT_OPERATORS:
                        raise ValueError(f"Regola {index}: '{condition.field}' si confronta solo con uguale/diverso.")
                    condition.value = str(condition.value).strip()
                    if condition.value not in labels:
                        raise ValueError(f"Regola {index}: '{condition.value}' non è un'opzione della domanda.")
                else:
                    try:
                        number = float(condition.value)
                    except (TypeError, ValueError):
                        raise ValueError(f"Regola {index}: '{condition.field}' richiede un valore numerico.") from None
                    if not math.isfinite(number):
                        raise ValueError(f"Regola {index}: valore numerico non valido.")
                    condition.value = number
        return self

    def payload_criteria(self) -> Union[Dict[str, str], List[str], None]:
        if self.type == "choice":
            return {option.label: option.description for option in self.options}
        if self.type == "score":
            return list(self.levels)
        return None


def validate_for_phase(phase: str, decision: Optional[JevDecisionConfig]) -> Optional[JevDecisionConfig]:
    """Controlla che le etichette puntino a esiti ammessi dalla fase. Solleva ValueError."""
    if decision is None:
        return None
    allowed = PHASE_OUTCOMES[phase]
    if decision.recall_richness and phase != "relevance":
        raise ValueError("La ricchezza del recall è disponibile soltanto per la rilevanza.")
    for index, rule in enumerate(decision.rules, start=1):
        if rule.outcome not in allowed:
            raise ValueError(f"Regola {index}: esito '{rule.outcome}' non valido per questa fase "
                             f"(ammessi: {', '.join(allowed)}).")
    return decision
