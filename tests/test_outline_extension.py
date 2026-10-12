import pytest

from rt.core.models import Outline, OutlineMacro, OutlineUnit, SegmentsData
from rt.pipeline.outline_extension import _mock_extension, validate_extension
from rt.pipeline.validator import ValidationError
from tests.test_stable_segments import segment


def outline():
    return Outline(lesson_title="Lesson", macro_sections=[OutlineMacro(id="1", title="Original", units=[
        OutlineUnit(id="1.1", title="Fixed one", start_segment_id="seg_000001", end_segment_id="seg_000002"),
        OutlineUnit(id="1.2", title="Fixed two", start_segment_id="seg_000003", end_segment_id="seg_000003")])])


def scenario():
    old = [segment(i, "old") for i in range(1, 4)]
    current = SegmentsData(segments=[s.model_copy(update={"index": i}) for i, s in enumerate(
        [segment(4, "new before"), old[0], segment(5, "new inside"), old[1], old[2], segment(6, "new after")], 1)])
    return old, current


def test_extend_covers_every_segment_and_keeps_existing_units():
    old, current = scenario()
    candidate = _mock_extension(outline(), old, current)
    report = validate_extension(candidate, outline(), old, current)
    assert report["coverage_percentage"] == 100 and report["duplicate_count"] == 0
    units = {u.id: u for m in candidate.macro_sections for u in m.units}
    assert units["1.1"] == outline().macro_sections[0].units[0]
    assert units["1.2"] == outline().macro_sections[0].units[1]


@pytest.mark.parametrize("change", ["title", "remove", "move_segments", "gap"])
def test_extend_rejects_changes_to_fixed_structure(change):
    old, current = scenario()
    candidate = _mock_extension(outline(), old, current)
    units = candidate.macro_sections[0].units
    if change == "title":
        next(u for u in units if u.id == "1.1").title = "Changed"
    elif change == "remove":
        candidate.macro_sections[0].units = [u for u in units if u.id != "1.2"]
    elif change == "move_segments":
        next(u for u in units if u.id == "1.1").end_segment_id = "seg_000001"
        next(u for u in units if u.id == "1.2").start_segment_id = "seg_000005"
    else:
        candidate.macro_sections[0].units = units[:-1]
    with pytest.raises(ValidationError):
        validate_extension(candidate, outline(), old, current)
