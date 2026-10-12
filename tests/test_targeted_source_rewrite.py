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
