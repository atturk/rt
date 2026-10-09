"""Chiamate condivise, impronte indipendenti e letture del contesto."""
from unittest.mock import patch
from rt.core.config import RTConfig, JevConfig
from rt.llm.jev_client import JevResponse, JevChoiceAnswer
from rt.services import classifier, question_types, section_labels, unit_relevance
from tests.test_jev_prefilter import setup_mock_lesson


def test_combined_calls_and_independent_freshness(tmp_path, monkeypatch):
    path = setup_mock_lesson(tmp_path, num_units=2)
    cfg = RTConfig(jev=JevConfig(relevance_mode="shadow", relevance_model="typesafe/jev-1.13"))
    for service in (classifier, question_types, section_labels, unit_relevance):
        monkeypatch.setattr(service, "load_config", lambda: cfg)
    monkeypatch.setattr(section_labels, "refresh", lambda *a, **kw: {})
    response = JevResponse(model="m", answers={
        "rilevanza": JevChoiceAnswer(choice="didactic", confidence=.95),
        "tipo_consigliato": JevChoiceAnswer(choice="mirata", confidence=.95)})
    # Usa una domanda choice per la rilevanza come i test del gate.
    from rt.services.jev_mapping import template
    cfg.jev.relevance_decision = template("relevance", "choice", cfg.jev)
    with patch("rt.llm.jev_client.call_jev", return_value=response) as called:
        classifier.classify_units(path)
        assert called.call_count == 2
        assert set(called.call_args.kwargs["questions"]) == {"rilevanza", "tipo_consigliato"}
        classifier.classify_units(path)
        assert called.call_count == 2
        with patch.object(question_types, "QT_VERSION", 3):
            classifier.classify_units(path)
        assert called.call_count == 4
        assert set(called.call_args.kwargs["questions"]) == {"tipo_consigliato"}


def test_context_files_opened_once_for_ten_units(tmp_path, monkeypatch):
    from rt.services.recall_context import _lesson_context
    from rt.storage import fs
    path = setup_mock_lesson(tmp_path, num_units=10)
    cfg = RTConfig(jev=JevConfig(relevance_mode="active", relevance_model="m"))
    monkeypatch.setattr(unit_relevance, "load_config", lambda: cfg)
    _lesson_context.cache_clear()
    counts = {}
    original = fs.open
    def counted(path, *args, **kwargs):
        name = str(path).split("/")[-1]
        if name in ("info.yaml", "outline.json"):
            counts[name] = counts.get(name, 0) + 1
        return original(path, *args, **kwargs)
    monkeypatch.setattr(fs, "open", counted)
    unit_relevance.list_units(path)
    assert counts == {"info.yaml": 1}  # La fixture non contiene outline.json.


def test_prefilter_cache_and_changed_text(tmp_path):
    from rt.pipeline.review import run_jev_task_a, run_jev_task_b
    from rt.pipeline.rewrite import load_draft
    path = setup_mock_lesson(tmp_path, num_units=1)
    unit = load_draft(path).units[0]
    cfg = JevConfig(enabled=True)
    from rt.llm.jev_client import JevNoulAnswer
    response = JevResponse(model="m", answers={"correttezza": JevChoiceAnswer(choice="corretta", confidence=.95),
                                               "unsupported_content": JevNoulAnswer(noul=.1)})
    with patch("rt.pipeline.review.call_jev", return_value=response) as called:
        for _ in range(2):
            run_jev_task_a(unit, cfg, path)
            run_jev_task_b(unit, "Fonte", cfg, path)
        assert called.call_count == 2
        unit.content += " Testo nuovo"
        run_jev_task_a(unit, cfg, path)
        run_jev_task_b(unit, "Fonte", cfg, path)
        assert called.call_count == 4
