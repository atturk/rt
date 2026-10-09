"""Coordinamento delle domande del classificatore, con impronte indipendenti."""
from rt.core.config import load_config, classifier_jev, classifier_job
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
    rel_cfg = classifier_jev(cfg, "relevance")
    qt_cfg = classifier_jev(cfg, "question_types")
    rel_enabled = bool(rel_cfg.relevance_model.strip()) and rel_cfg.relevance_mode != "disabled"
    qt_enabled = question_types.enabled() and classifier_job(cfg, "question_types").mode == "pipeline"
    allowed = unit_relevance.included_ids(lesson_dir, units)
    rel_enabled = rel_enabled and classifier_job(cfg, "relevance").mode in ("observe", "pipeline")
    context = lesson_context(lesson_dir)
    for unit in units:
        questions = {}
        rel = relevance.get(unit.unit_id, {})
        qt = types.get(unit.unit_id, {})
        if rel_enabled and not (rel.get("text_hash") == unit_relevance._unit_hash(unit, lesson_dir)
                and rel.get("config_hash") == unit_relevance._config_hash(rel_cfg)
                and rel.get("prediction") in unit_relevance.CLASSES):
            questions[jev_mapping.QUESTION_NAMES["relevance"]] = jev_mapping.build_question(
                jev_mapping.effective_decision("relevance", rel_cfg))
        if qt_enabled and unit.unit_id in allowed and not (qt.get("text_hash") == question_types._text_hash(unit, lesson_dir)
                and qt.get("config_hash") == question_types._config_hash(qt_cfg)
                and qt.get("mock") == mock and qt.get("candidate") in question_types.CRITERIA):
            questions["tipo_consigliato"] = jev_client.JevChoiceQuestion(
                instructions=question_types.INSTRUCTIONS, criteria=question_types.CRITERIA)
        if questions and not mock:
            # Un modello proprio impedisce di fondere le due richieste.
            same_connection = (rel_cfg.relevance_model, rel_cfg.credential, rel_cfg.base_url) == (qt_cfg.relevance_model, qt_cfg.credential, qt_cfg.base_url)
            batches = [(rel_cfg if jev_mapping.QUESTION_NAMES["relevance"] in questions else qt_cfg, questions)] if same_connection or len(questions) == 1 else [
                (rel_cfg, {k: v for k, v in questions.items() if k != "tipo_consigliato"}),
                (qt_cfg, {"tipo_consigliato": questions["tipo_consigliato"]})]
            answers = {}
            for connection, batch in batches:
                try:
                    response = jev_client.call_jev(
                        state=jev_mapping.state_for("relevance", unit.title, unit.content, context),
                        questions=batch, job_name="classifier", unit_id=unit.unit_id, lesson_dir=lesson_dir,
                        model=connection.relevance_model, credential=connection.credential, base_url=connection.base_url,
                        timeout_seconds=connection.timeout_seconds)
                    answers.update(response.answers)
                except Exception:
                    pass  # I servizi registrano la risposta mancante senza ripetere la chiamata.
            responses[unit.unit_id] = jev_client.JevResponse(model=rel_cfg.relevance_model, answers=answers)
    relevance = unit_relevance.refresh(lesson_dir, force_mock=mock, ctx=ctx, responses=responses) if rel_enabled else relevance
    from rt.services import section_labels
    if classifier_job(cfg, "section_labels").mode == "pipeline":
        section_labels.refresh(lesson_dir, force_mock=mock)
    types = question_types.refresh(lesson_dir, force_mock=mock, ctx=ctx, responses=responses, refresh_sections=False) if qt_enabled else types
    return {"relevance": relevance, "question_types": types}
