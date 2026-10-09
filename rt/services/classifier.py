"""Coordinamento delle domande del classificatore, con impronte indipendenti."""
from rt.core.config import load_config
from rt.pipeline.rewrite import load_draft
from rt.services import jev_mapping, question_types, unit_relevance
from rt.services.recall_context import lesson_context


def classify_units(lesson_dir, ctx=None, *, force_mock=False):
    from rt.llm import jev_client
    cfg = load_config()
    mock = force_mock or cfg.mock_llm
    units = load_draft(lesson_dir).units
    relevance = unit_relevance._load(lesson_dir)
    types = question_types._load(lesson_dir)
    responses = {}
    rel_enabled = bool(cfg.jev.relevance_model.strip()) and cfg.jev.relevance_mode != "disabled"
    qt_enabled = question_types.enabled()
    allowed = unit_relevance.included_ids(lesson_dir, units)
    context = lesson_context(lesson_dir)
    for unit in units:
        questions = {}
        rel = relevance.get(unit.unit_id, {})
        qt = types.get(unit.unit_id, {})
        if rel_enabled and not (rel.get("text_hash") == unit_relevance._unit_hash(unit, lesson_dir)
                and rel.get("config_hash") == unit_relevance._config_hash(cfg.jev)
                and rel.get("prediction") in unit_relevance.CLASSES):
            questions[jev_mapping.QUESTION_NAMES["relevance"]] = jev_mapping.build_question(
                jev_mapping.effective_decision("relevance", cfg.jev))
        if qt_enabled and unit.unit_id in allowed and not (qt.get("text_hash") == question_types._text_hash(unit, lesson_dir)
                and qt.get("config_hash") == question_types._config_hash(cfg.jev)
                and qt.get("mock") == mock and qt.get("candidate") in question_types.CRITERIA):
            questions["tipo_consigliato"] = jev_client.JevChoiceQuestion(
                instructions=question_types.INSTRUCTIONS, criteria=question_types.CRITERIA)
        if questions and not mock:
            try:
                responses[unit.unit_id] = jev_client.call_jev(
                    state=jev_mapping.state_for("relevance", unit.title, unit.content, context),
                    questions=questions, job_name="classifier", unit_id=unit.unit_id, lesson_dir=lesson_dir,
                    model=cfg.jev.relevance_model, credential=cfg.jev.credential, base_url=cfg.jev.base_url,
                    timeout_seconds=cfg.jev.timeout_seconds)
            except Exception:
                # Risposta vuota: i due servizi registrano l'errore senza ripetere la chiamata.
                responses[unit.unit_id] = jev_client.JevResponse(model=cfg.jev.relevance_model, answers={})
    relevance = unit_relevance.refresh(lesson_dir, force_mock=mock, ctx=ctx, responses=responses)
    types = question_types.refresh(lesson_dir, force_mock=mock, ctx=ctx, responses=responses)
    return {"relevance": relevance, "question_types": types}
