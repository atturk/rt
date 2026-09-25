"""
rt.llm.jev_client
Client dedicato per Jev (typesafe.ai), un modello "System One" di decisione strutturata.

API fondamentalmente diversa dalle chat-completions: prende uno stato testuale libero
("state") e un dizionario di domande tipizzate (choice/score/noul), e restituisce SOLO
decisioni strutturate con confidenza — mai testo libero generato. Per questo non passa
da BaseLLMProvider/LLMClient.call_structured (pensati per messages/streaming/JSON-schema
di una chat-completions), ma riusa comunque l'infrastruttura di credenziali, costo e
telemetria già esistente nel progetto.

Endpoint verificato empiricamente con una chiamata reale (script in scratch/jev_spike.py,
usa-e-getta, non fa parte del codice di produzione): POST
https://openrouter.ai/api/alpha/decisions con la stessa credenziale "openrouter" già
configurata in RT — nessuna chiave TypeSafe nativa separata è necessaria. L'endpoint
esatto è emerso dal messaggio d'errore restituito da OpenRouter tentando di chiamare
Jev come un modello di chat-completions normale ("...cannot be used with the
chat/completions endpoint. Use the /api/alpha/decisions endpoint instead.").
"""

import datetime
import time
from typing import Dict, List, Literal, Optional, Union

import requests
from pydantic import BaseModel, Field

from rt.llm.credentials import GLOBAL_CREDENTIALS
from rt.llm.pricing import calculate_cost
from rt.llm.telemetry import LLMTelemetryRecord, current_telemetry

DEFAULT_JEV_BASE_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"
DEFAULT_JEV_CREDENTIAL = "openrouter"


class JevChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: Dict[str, str]


class JevScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: List[str]


class JevNoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str


JevQuestion = Union[JevChoiceQuestion, JevScoreQuestion, JevNoulQuestion]


class JevChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: Dict[str, float] = Field(default_factory=dict)
    confidence: float = 0.0


class JevScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    score: float
    legend: Dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0


class JevNoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    noul: float


JevAnswer = Union[JevChoiceAnswer, JevScoreAnswer, JevNoulAnswer]


class JevResponse(BaseModel):
    model: str
    answers: Dict[str, JevAnswer]
    usage: Dict[str, float] = Field(default_factory=dict)


class JevError(Exception):
    """Sollevata per qualunque fallimento della chiamata Jev (rete, auth, formato risposta)."""

    def __init__(self, message: str, http_status: Optional[int] = None):
        super().__init__(message)
        self.http_status = http_status


def _parse_answer(name: str, raw: Dict) -> JevAnswer:
    a_type = raw.get("type")
    if a_type == "choice":
        return JevChoiceAnswer.model_validate(raw)
    if a_type == "score":
        return JevScoreAnswer.model_validate(raw)
    if a_type == "noul":
        return JevNoulAnswer.model_validate(raw)
    raise JevError(f"Tipo di risposta Jev sconosciuto per la domanda '{name}': {a_type!r}")


def call_jev(
    state: str,
    questions: Dict[str, JevQuestion],
    *,
    job_name: str,
    unit_id: Optional[str] = None,
    lesson_dir: Optional[str] = None,
    model: str = DEFAULT_JEV_MODEL,
    credential: str = DEFAULT_JEV_CREDENTIAL,
    base_url: str = DEFAULT_JEV_BASE_URL,
    timeout_seconds: float = 15.0,
) -> JevResponse:
    """
    Esegue una chiamata a Jev (System One di typesafe.ai) via l'endpoint decisions di
    OpenRouter. Registra costo e telemetria come ogni altra chiamata LLM del progetto
    (compare in 'rt cost' e in llm_debug.log), ma non passa da LLMClient.call_structured.
    Solleva JevError in caso di fallimento di rete, autenticazione o formato risposta.
    """
    from rt.llm.client import _append_debug_log  # import locale: evita un ciclo di import con rt.llm.client

    api_key = GLOBAL_CREDENTIALS.get_api_key(credential)
    if not api_key:
        raise JevError(f"Credenziale '{credential}' non configurata o chiave API mancante per Jev.")

    payload = {
        "state": state,
        "model": model,
        "questions": {name: q.model_dump(exclude_none=True) for name, q in questions.items()},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    t_start = time.time()
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    resp_json: Optional[Dict] = None
    try:
        resp = requests.post(base_url, headers=headers, json=payload, timeout=timeout_seconds)
        http_status = resp.status_code
        resp_json = resp.json()
        if resp.status_code != 200:
            error_message = GLOBAL_CREDENTIALS.sanitize_secrets(str(resp_json))
            raise JevError(f"Jev ha risposto con status {resp.status_code}: {error_message}", http_status=resp.status_code)
    except (requests.RequestException, ValueError) as e:
        error_message = GLOBAL_CREDENTIALS.sanitize_secrets(str(e))
        raise JevError(f"Errore chiamando Jev: {error_message}") from e
    finally:
        elapsed = time.time() - t_start
        usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
        reported_cost = usage.get("cost")
        cost_est = reported_cost if reported_cost is not None else calculate_cost(
            provider="openrouter", model=model, input_tokens=in_tok, output_tokens=out_tok
        )

        record = LLMTelemetryRecord(
            request_id=f"jev_{int(t_start * 1000)}",
            job=job_name,
            unit_id=unit_id,
            provider="typesafe",
            model=model,
            elapsed_seconds=round(elapsed, 4),
            latency_ms=round(elapsed * 1000.0, 2),
            input_tokens=in_tok,
            output_tokens=out_tok,
            status="success" if http_status == 200 else "error",
            http_status=http_status,
            error_message=error_message,
            estimated_cost=cost_est,
            streaming=False,
        )
        current_telemetry().add(record)

        if lesson_dir:
            _append_debug_log(lesson_dir, {
                "timestamp": datetime.datetime.now().isoformat(),
                "job": job_name,
                "unit_id": unit_id,
                "provider": "typesafe",
                "model": model,
                "status": record.status,
                "elapsed_seconds": record.elapsed_seconds,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "estimated_cost": cost_est,
                "error_message": error_message,
                "jev_answers": resp_json.get("answers") if isinstance(resp_json, dict) else None,
            })

    answers = {name: _parse_answer(name, raw) for name, raw in resp_json.get("answers", {}).items()}
    return JevResponse(model=resp_json.get("model", model), answers=answers, usage=resp_json.get("usage", {}))
