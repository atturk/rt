import json

from rt.core.models import Draft, DraftUnit
from rt.core.sources import add_source
from rt.pipeline.outline import save_outline
from rt.pipeline.rewrite import save_draft, load_draft
from rt.pipeline.source_update import run_source_update, changed_units
from tests.test_source_update import legacy
from tests.test_outline_extension import outline, scenario


def test_shifted_times_do_not_require_rewrite():
    old, _ = scenario()
    shifted = [s.model_copy(update={"start_seconds": 30, "end_seconds": 31}) for s in old]
    assert changed_units(outline(), old, outline(), shifted) == []
    shifted[0].text_raw = "changed"
    assert changed_units(outline(), old, outline(), shifted) == ["1.1"]


def test_update_only_rewrites_new_unit_and_preserves_human_decisions(tmp_path, monkeypatch):
    legacy(tmp_path)
    lesson = str(tmp_path)
    old_outline = outline()
    old_outline.macro_sections[0].units = old_outline.macro_sections[0].units[:1]
    old_outline.macro_sections[0].units[0].end_segment_id = "seg_000001"
    save_outline(old_outline, lesson)
    original = DraftUnit(unit_id="1.1", title="Fixed one", start_segment_id="seg_000001",
                         end_segment_id="seg_000001", source_segment_ids=["seg_000001"], content="Edited by user", generated_at="2026-01-01")
    save_draft(Draft(units=[original]), lesson)
    decisions = tmp_path / "review_decisions.json"
    decisions.write_text(json.dumps({"decisions": [{"issue_id": "science-1", "decision": "accepted"}]}))
    before = decisions.read_bytes()
    add_source(lesson, "appunti", "notes.txt", b"New notes", ordine=1)
    monkeypatch.setattr("rt.services.classifier.classify_units", lambda *args, **kwargs: None)
    result = run_source_update(lesson, mock=True)
    assert result["processed_units"] == 1
    assert result["changed_units"] == ["1.2"]
    assert next(u for u in load_draft(lesson).units if u.unit_id == "1.1") == original
    assert decisions.read_bytes() == before


def test_insertion_between_sources_rewrites_only_the_spanning_unit(tmp_path, monkeypatch):
    from rt.services.notes_lesson_service import create_notes_lesson
    from rt.pipeline.prepare import run_prepare
    from rt.pipeline.rewrite import run_rewrite
    from rt.pipeline.ledger import record_decision, load_ledger
    lesson = create_notes_lesson("First", date="2026-10-12", materia="Test", dest_dir=str(tmp_path))
    add_source(lesson, "appunti", "second.txt", b"Second")
    add_source(lesson, "appunti", "third.txt", b"Third")
    run_prepare(lesson)
    save_outline(outline(), lesson)
    from rt.core.state import transition_to, WorkflowState
    from rt.core.lesson_paths import lesson_path
    transition_to(lesson_path(lesson, "info.yaml"), WorkflowState.OUTLINE_VALIDATED, allow_force=True)
    monkeypatch.setattr("rt.services.classifier.classify_units", lambda *args, **kwargs: None)
    run_rewrite(lesson, force_mock=True)
    original = next(u for u in load_draft(lesson).units if u.unit_id == "1.2")
    original_title = next(u for u in load_draft(lesson).units if u.unit_id == "1.1").title
    from rt.llm.client import LLMClient
    call = LLMClient.call_structured
    def changed_title(self, **kwargs):
        result = call(self, **kwargs)
        if kwargs["job_name"] == "rewrite":
            result.title = "Titolo cambiato dal modello"
        return result
    monkeypatch.setattr(LLMClient, "call_structured", changed_title)
    record_decision(lesson, "existing-decision", "rejected")
    ledger = load_ledger(lesson)
    add_source(lesson, "appunti", "inserted.txt", b"Inserted inside the first unit", ordine=2)
    result = run_source_update(lesson, mock=True)
    assert result["changed_units"] == ["1.1"] and result["processed_units"] == 1
    assert next(u for u in load_draft(lesson).units if u.unit_id == "1.2") == original
    assert next(u for u in load_draft(lesson).units if u.unit_id == "1.1").title == original_title
    assert next(u for u in load_draft(lesson).units if u.unit_id == "1.1").source_segment_ids == ["seg_000001", "seg_000004", "seg_000002"]
    assert load_ledger(lesson) == ledger
