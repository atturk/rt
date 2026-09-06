"""
Unit tests per rt.pipeline.validator
"""

import pytest
from rt.core.models import (
    Segment, SegmentsData,
    Outline, OutlineMacro, OutlineUnit,
    Draft, DraftUnit
)
from rt.pipeline.validator import validate_outline, validate_draft, ValidationError


@pytest.fixture
def sample_segments():
    segs = [
        Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=30.0, start_formatted="00:00", end_formatted="00:30", text_raw="Intro"),
        Segment(id="seg_000002", index=2, start_seconds=30.0, end_seconds=60.0, start_formatted="00:30", end_formatted="01:00", text_raw="Argomento 1"),
        Segment(id="seg_000003", index=3, start_seconds=60.0, end_seconds=90.0, start_formatted="01:00", end_formatted="01:30", text_raw="Argomento 2"),
        Segment(id="seg_000004", index=4, start_seconds=90.0, end_seconds=120.0, start_formatted="01:30", end_formatted="02:00", text_raw="Conclusione"),
    ]
    return SegmentsData(schema_version="1.0", segments=segs)


def test_validate_outline_valid(sample_segments):
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione di Prova",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro 1",
                units=[
                    OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_000001", end_segment_id="seg_000002"),
                    OutlineUnit(id="1.2", title="Unità 2", start_segment_id="seg_000003", end_segment_id="seg_000004"),
                ]
            )
        ]
    )
    report = validate_outline(outline, sample_segments)
    assert report["valid"] is True
    assert report["coverage_percentage"] == 100.0
    assert report["omitted_count"] == 0


def test_validate_outline_missing_segment(sample_segments):
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione Errore",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro 1",
                units=[
                    OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_999999", end_segment_id="seg_000002"),
                ]
            )
        ]
    )
    with pytest.raises(ValidationError, match="non esiste nei segmenti"):
        validate_outline(outline, sample_segments)


def test_validate_outline_inverted_unit_order(sample_segments):
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione Errore",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro 1",
                units=[
                    OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_000002", end_segment_id="seg_000001"),
                ]
            )
        ]
    )
    with pytest.raises(ValidationError, match="successivo a end_segment"):
        validate_outline(outline, sample_segments)


def test_validate_outline_chronological_inversion(sample_segments):
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione Errore",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro 1",
                units=[
                    OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_000003", end_segment_id="seg_000004"),
                    OutlineUnit(id="1.2", title="Unità 2", start_segment_id="seg_000001", end_segment_id="seg_000002"),
                ]
            )
        ]
    )
    with pytest.raises(ValidationError, match="Inversione cronologica"):
        validate_outline(outline, sample_segments)


def test_validate_draft_valid(sample_segments):
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione di Prova",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro 1",
                units=[
                    OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_000001", end_segment_id="seg_000002"),
                ]
            )
        ]
    )
    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Unità 1",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
                content="Testo accademico rielaborato..."
            )
        ]
    )
    report = validate_draft(draft, outline, sample_segments)
    assert report["valid"] is True
    assert report["provenance_verified_units"] == 1


def test_validate_draft_missing_provenance(sample_segments):
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione di Prova",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro 1",
                units=[
                    OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_000001", end_segment_id="seg_000002"),
                ]
            )
        ]
    )
    with pytest.raises(Exception): # Pydantic or ValidationError on empty list
        Draft(
            schema_version="1.0",
            units=[
                DraftUnit(
                    unit_id="1.1",
                    title="Unità 1",
                    start_segment_id="seg_000001",
                    end_segment_id="seg_000002",
                    source_segment_ids=[],
                    content="Testo senza provenance"
                )
            ]
        )
