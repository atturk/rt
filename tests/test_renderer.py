"""
Unit test per il vincolo obbligatorio sui timestamp del renderer (Spec sezione 50).
Verifica che il timestamp nel Markdown derivi sempre da:
segments[chapter.start_segment_id].start_seconds -> format_timestamp()
e che non possa essere manipolato da input esterni o dall'LLM.
"""

import re
import pytest
from rt.core.models import (
    Segment, SegmentsData,
    Outline, OutlineMacro, OutlineUnit,
    Draft, DraftUnit
)
from rt.core.timestamp import format_timestamp
from rt.pipeline.build import render_pre_elaborato_md, render_rielaborato_md


@pytest.fixture
def mock_lecture_data():
    segments = [
        Segment(
            id="seg_000184",
            index=184,
            start_seconds=2190.0, # 36:30
            end_seconds=2228.0,
            start_formatted="36:30",
            end_formatted="37:08",
            text_raw="Iniziamo la via del propionil-CoA."
        ),
        Segment(
            id="seg_000185",
            index=185,
            start_seconds=2228.0,
            end_seconds=2260.0,
            start_formatted="37:08",
            end_formatted="37:40",
            text_raw="Il propionil-CoA viene carbossilato."
        )
    ]
    seg_data = SegmentsData(schema_version="1.0", segments=segments)
    
    outline = Outline(
        schema_version="1.0",
        lesson_title="Metabolismo Lipidico",
        macro_sections=[
            OutlineMacro(
                id="5",
                title="Acidi grassi dispari",
                units=[
                    OutlineUnit(
                        id="5.2",
                        title="La via di conversione del propionil-CoA in succinil-CoA",
                        start_segment_id="seg_000184",
                        end_segment_id="seg_000185"
                    )
                ]
            )
        ]
    )
    
    draft = Draft(
        schema_version="1.0",
        units=[
            DraftUnit(
                unit_id="5.2",
                title="La via di conversione del propionil-CoA in succinil-CoA",
                start_segment_id="seg_000184",
                end_segment_id="seg_000185",
                source_segment_ids=["seg_000184", "seg_000185"],
                content="La conversione del propionil-CoA avviene in tre reazioni enzimatiche consecutive."
            )
        ]
    )
    return seg_data, outline, draft


def test_timestamp_strictly_derived_from_segment(mock_lecture_data):
    seg_data, outline, draft = mock_lecture_data
    
    # 1. Rendering pre-elaborato
    rendered_pre = render_pre_elaborato_md(
        outline=outline,
        draft=draft,
        segments_data=seg_data,
        date="2026-09-05",
        subject="BIOCHIMICA",
        topics="lipidi"
    )
    
    # Verifica che nel testo generato, sotto '### 5.2', ci sia esattamente '36:30'
    expected_timestamp = format_timestamp(seg_data.segments[0].start_seconds) # 36:30
    assert expected_timestamp == "36:30"
    
    match_pre = re.search(r"### 5.2[^\n]+\n([0-9:]+)", rendered_pre)
    assert match_pre is not None, "Timestamp non trovato sotto l'intestazione dell'unità nel pre-elaborato"
    found_timestamp = match_pre.group(1).strip()
    assert found_timestamp == expected_timestamp
    
    # 2. Rendering rielaborato definitivo
    rendered_rielab = render_rielaborato_md(
        outline=outline,
        draft=draft,
        segments_data=seg_data,
        date="2026-09-05",
        subject="BIOCHIMICA",
        topics="lipidi"
    )
    match_rielab = re.search(r"### 5.2[^\n]+\n([0-9:]+)", rendered_rielab)
    assert match_rielab is not None, "Timestamp non trovato sotto l'intestazione nel rielaborato"
    assert match_rielab.group(1).strip() == expected_timestamp


def test_renderer_fails_if_segment_does_not_exist(mock_lecture_data):
    seg_data, outline, draft = mock_lecture_data
    
    # Manomettiamo l'ID del segmento di inizio con uno non esistente
    outline.macro_sections[0].units[0].start_segment_id = "seg_999999"
    
    from rt.pipeline.build import BuildError
    with pytest.raises(BuildError, match="inesistente per unità"):
        render_pre_elaborato_md(
            outline=outline,
            draft=draft,
            segments_data=seg_data,
            date="2026-09-05",
            subject="BIOCHIMICA",
            topics="lipidi"
        )
