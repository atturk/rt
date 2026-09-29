"""
rt.services.jev_playground
Servizi della sezione "Decisioni JEV" delle impostazioni: lettura e salvataggio della
configurazione per fase e prova di una configurazione non salvata su un'unità di lezione.
"""

from typing import Any, Dict, Optional

from rt.core.jev_decision import JevDecisionConfig, validate_for_phase
from rt.services import jev_mapping

PHASES = ("relevance", "prefilter")
TYPES = ("choice", "noul", "score")


class PlaygroundError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def templates(jev_cfg) -> Dict[str, Dict[str, JevDecisionConfig]]:
    return {phase: {kind: jev_mapping.template(phase, kind, jev_cfg) for kind in TYPES} for phase in PHASES}


def probe_key(credential: str, model: str, request_type: str) -> str:
    return f"decision_probe:{credential}:{model}:{request_type}"


def record_probe(credential: str, model: str, request_type: str) -> None:
    """Ricorda che il modello ha risposto correttamente a una domanda di quel tipo."""
    from rt.db.engine import get_database
    from rt.db.models import Setting, utcnow
    from rt.db.session import session_scope
    with session_scope(get_database()) as session:
        key = probe_key(credential, model, request_type)
        row = session.get(Setting, key)
        if row:
            row.value = {"validated": utcnow().isoformat()}
        else:
            session.add(Setting(key=key, value={"validated": utcnow().isoformat()}))


def probe_missing(checks) -> Optional[str]:
    """Il primo (modello, tipo) non ancora provato, se c'è."""
    from rt.db.engine import get_database
    from rt.db.models import Setting
    from rt.db.session import session_scope
    with session_scope(get_database()) as session:
        for credential, model, request_type in checks:
            if session.get(Setting, probe_key(credential, model, request_type)) is None:
                return f"Prova prima il protocollo Jev {request_type} del modello {model}."
    return None


def check_phase(phase: str, decision: JevDecisionConfig) -> JevDecisionConfig:
    try:
        return validate_for_phase(phase, decision)
    except ValueError as exc:
        raise PlaygroundError(422, "invalid_decision", str(exc)) from exc


def _unit(lesson_id: Optional[int], unit_id: Optional[str], phase: str):
    """(id, titolo, testo, id lezione) dell'unità di prova; senza lezione, l'esempio della fase."""
    if lesson_id is None:
        title, content = jev_mapping.SAMPLE_UNITS[phase]
        return None, title, content, None
    from rt.pipeline.rewrite import load_draft
    from rt.services.lesson_service import LessonNotFound, resolve_lesson_dir
    try:
        lesson_dir = resolve_lesson_dir(lesson_id)
    except LessonNotFound as exc:
        raise PlaygroundError(404, "lesson_not_found", str(exc)) from exc
    try:
        units = load_draft(lesson_dir).units
    except (FileNotFoundError, ValueError) as exc:
        raise PlaygroundError(422, "draft_missing", "La lezione non ha ancora una bozza riscritta.") from exc
    unit = next((u for u in units if u.unit_id == unit_id), None) if unit_id else (units[0] if units else None)
    if unit is None:
        raise PlaygroundError(404, "unit_not_found", "Unità non trovata nella bozza.")
    return unit.unit_id, unit.title, unit.content, lesson_dir


def run_test(phase: str, decision: JevDecisionConfig, model: str, credential: str,
             lesson_id: Optional[int] = None, unit_id: Optional[str] = None) -> Dict[str, Any]:
    """Esegue la domanda configurata (anche non salvata) su un'unità e la mappa. Non salva nulla
    della configurazione; registra solo che il modello supporta quel tipo di domanda."""
    from rt.core.config import load_config
    from rt.llm import jev_client
    if not model.strip():
        raise PlaygroundError(422, "decision_model_required", "Indica un modello decisionale.")
    decision = check_phase(phase, decision)
    jev_cfg = load_config().jev
    selected_unit, title, content, _lesson_dir = _unit(lesson_id, unit_id, phase)
    state = jev_mapping.state_for(phase, title, content)
    name = jev_mapping.QUESTION_NAMES[phase]
    question = jev_mapping.build_question(decision)
    try:
        response = jev_client.call_jev(state, {name: question}, job_name=f"decision_test_{phase}",
                                       model=model.strip(), credential=credential,
                                       base_url=jev_cfg.base_url, timeout_seconds=jev_cfg.timeout_seconds)
    except jev_client.JevError as exc:
        raise PlaygroundError(422, "decision_protocol_failed", str(exc)) from exc
    answer = response.answers.get(name)
    if answer is None or answer.type != decision.type:
        raise PlaygroundError(422, "decision_protocol_failed",
                              f"Il modello non ha restituito una risposta Jev {decision.type}.")
    result = jev_mapping.evaluate(phase, decision, answer)
    record_probe(credential, model.strip(), decision.type)
    raw = response.raw if response.raw is not None else response.model_dump()
    return {"phase": phase, "unit_id": selected_unit, "unit_title": title, "state": state,
            "request": {"state": state, "model": model.strip(),
                        "questions": {name: question.model_dump(exclude_none=True)}},
            "response": raw, **result.as_dict()}
