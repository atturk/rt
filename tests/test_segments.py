"""
Unit tests per rt.core.segments
"""

import os
import json
import pytest
from rt.core.segments import (
    make_segment_id,
    parse_segments_from_json,
    parse_segments_from_markdown,
    save_segments_json,
    load_segments_json,
    export_normalized_transcript_md
)


def test_make_segment_id():
    assert make_segment_id(1) == "seg_000001"
    assert make_segment_id(184) == "seg_000184"
    assert make_segment_id(999999) == "seg_999999"


def test_parse_segments_from_macwhisper_json(tmp_path):
    mw_data = {
        "segments": [
            {
                "id": "uuid-1",
                "start": 2720,
                "end": 6560,
                "text": "Allora ieri abbiamo visto."
            },
            {
                "id": "uuid-2",
                "start": 9760,
                "end": 13280,
                "text": "Tutti collezioni, abbiamo visto."
            }
        ]
    }
    json_file = str(tmp_path / "mw_export.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(mw_data, f)
        
    segments = parse_segments_from_json(json_file)
    assert len(segments) == 2
    assert segments[0].id == "seg_000001"
    assert segments[0].start_seconds == 2.72
    assert segments[0].end_seconds == 6.56
    assert segments[0].start_formatted == "00:02"
    assert segments[0].text_raw == "Allora ieri abbiamo visto."

    assert segments[1].id == "seg_000002"
    assert segments[1].start_seconds == 9.76
    assert segments[1].end_seconds == 13.28
    assert segments[1].start_formatted == "00:09"


def test_parse_segments_from_timestamp_list_json(tmp_path):
    list_data = [
        {"text": "Frase 1", "timestamp": "00:02-00:12"},
        {"text": "Frase 2", "timestamp": "00:14-00:20"}
    ]
    json_file = str(tmp_path / "list_export.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(list_data, f)
        
    segments = parse_segments_from_json(json_file)
    assert len(segments) == 2
    assert segments[0].start_seconds == 2.0
    assert segments[0].end_seconds == 12.0
    assert segments[1].start_seconds == 14.0
    assert segments[1].end_seconds == 20.0


def test_parse_segments_from_markdown(tmp_path):
    md_content = """---
materia: BIOCHIMICA
data: 2026-09-05
---

*00:02*
Allora ieri abbiamo visto tutti questione, abbiamo visto

*00:14*
I figured sono depositati nel tessuto a disturbare.

*00:22-00:26*
Quando c'è necessità di degradarli.
"""
    md_file = str(tmp_path / "trascritto grezzo.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    segments = parse_segments_from_markdown(md_file)
    assert len(segments) == 3
    assert segments[0].id == "seg_000001"
    assert segments[0].start_seconds == 2.0
    # end_seconds del segmento 1 deve coincidere con lo start del segmento 2 (14.0)
    assert segments[0].end_seconds == 14.0
    assert segments[0].text_raw == "Allora ieri abbiamo visto tutti questione, abbiamo visto"

    assert segments[1].id == "seg_000002"
    assert segments[1].start_seconds == 14.0
    # end_seconds del segmento 2 deve coincidere con lo start del segmento 3 (22.0)
    assert segments[1].end_seconds == 22.0

    assert segments[2].id == "seg_000003"
    assert segments[2].start_seconds == 22.0
    assert segments[2].end_seconds == 26.0


def test_save_and_load_segments_roundtrip(tmp_path):
    segments = parse_segments_from_markdown(str(tmp_path / "non_existent.md")) if False else []
    from rt.core.models import Segment
    seg1 = Segment(
        id="seg_000001",
        index=1,
        start_seconds=0.0,
        end_seconds=10.0,
        start_formatted="00:00",
        end_formatted="00:10",
        text_raw="Inizio lezione"
    )
    seg_file = str(tmp_path / "segments.json")
    save_segments_json([seg1], seg_file, lesson_id="lesson_test")
    
    loaded = load_segments_json(seg_file)
    assert loaded.lesson_id == "lesson_test"
    assert len(loaded.segments) == 1
    assert loaded.segments[0].id == "seg_000001"
    assert loaded.segments[0].start_seconds == 0.0


def test_export_normalized_transcript_md(tmp_path):
    from rt.core.models import Segment
    seg1 = Segment(
        id="seg_000001",
        index=1,
        start_seconds=2.0,
        end_seconds=12.0,
        start_formatted="00:02",
        end_formatted="00:12",
        text_raw="Testo di prova"
    )
    out_md = str(tmp_path / "normalized.md")
    export_normalized_transcript_md([seg1], out_md)
    assert os.path.isfile(out_md)
    with open(out_md, "r", encoding="utf-8") as f:
        content = f.read()
    assert "[seg_000001]" in content
    assert "00:02 - 00:12" in content
    assert "Testo di prova" in content
