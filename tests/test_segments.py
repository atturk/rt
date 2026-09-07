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


def test_parse_segments_from_macwhisper_json_sub_500ms(tmp_path):
    """Verifica che segmenti che iniziano/finiscono sotto i 500ms vengano convertiti correttamente da ms a secondi."""
    mw_data = {
        "segments": [
            {
                "id": "uuid-sub500",
                "start": 200,
                "end": 480,
                "text": "Avvio brevissimo."
            }
        ]
    }
    json_file = str(tmp_path / "mw_sub500.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(mw_data, f)

    segments = parse_segments_from_json(json_file)
    assert len(segments) == 1
    assert segments[0].id == "seg_000001"
    assert segments[0].start_seconds == 0.2
    assert segments[0].end_seconds == 0.48
    assert segments[0].start_formatted == "00:00"
    assert segments[0].text_raw == "Avvio brevissimo."


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


def test_extract_context_window_90s():
    """Verifica che extract_context_window accumuli correttamente ~90 secondi di contesto e rispetti il cap di 20 segmenti."""
    from rt.core.models import Segment
    from rt.core.timestamp import format_timestamp
    from rt.pipeline.rewrite import extract_context_window

    # 1. Creiamo 30 segmenti di 10s ciascuno (da 0s a 300s)
    segments_10s = [
        Segment(
            id=f"seg_{i:06d}",
            index=i,
            start_seconds=(i - 1) * 10.0,
            end_seconds=i * 10.0,
            start_formatted=format_timestamp((i - 1) * 10.0),
            end_formatted=format_timestamp(i * 10.0),
            text_raw=f"Segmento {i}"
        )
        for i in range(1, 31)
    ]

    # Target: unità dal segmento 15 al segmento 16 (140.0s - 160.0s)
    target_start = segments_10s[14]  # seg_000015, start=140.0s
    target_end = segments_10s[15]    # seg_000016, end=160.0s

    prev_segs, next_segs = extract_context_window(
        all_segments=segments_10s,
        start_seg=target_start,
        end_seg=target_end,
        window_seconds=90.0,
        max_segments=20
    )

    # 90s prima di 140s = fino a 50s -> segmenti 6, 7, 8, 9, 10, 11, 12, 13, 14 (9 segmenti da 10s)
    # seg_000006 ha start_seconds = 50.0 (140 - 50 = 90.0 <= 90.0)
    # seg_000005 ha start_seconds = 40.0 (140 - 40 = 100.0 > 90.0, escluso)
    assert len(prev_segs) == 9
    assert prev_segs[0].id == "seg_000006"
    assert prev_segs[-1].id == "seg_000014"

    # 90s dopo 160s = fino a 250s -> segmenti 17, 18, 19, 20, 21, 22, 23, 24, 25 (9 segmenti da 10s)
    assert len(next_segs) == 9
    assert next_segs[0].id == "seg_000017"
    assert next_segs[-1].id == "seg_000025"

    # 2. Test cap su segmenti brevissimi (1s ciascuno)
    segments_1s = [
        Segment(
            id=f"seg_{i:06d}",
            index=i,
            start_seconds=float(i - 1),
            end_seconds=float(i),
            start_formatted=format_timestamp(float(i - 1)),
            end_formatted=format_timestamp(float(i)),
            text_raw=f"Micro {i}"
        )
        for i in range(1, 101)
    ]
    prev_micro, next_micro = extract_context_window(
        all_segments=segments_1s,
        start_seg=segments_1s[50],  # index 51
        end_seg=segments_1s[50],
        window_seconds=90.0,
        max_segments=20
    )
    # Anche se 90s coprirebbero 90 segmenti, il cap massimo di 20 interviene
    assert len(prev_micro) == 20
    assert len(next_micro) == 20

    # 3. Test ai bordi estremi (inizio e fine)
    prev_edge, _ = extract_context_window(segments_10s, segments_10s[0], segments_10s[1], 90.0, 20)
    assert len(prev_edge) == 0  # nessun segmento prima di index 1


def test_segment_cross_field_consistency():
    """Verifica le invarianti cross-field del modello Segment."""
    from rt.core.models import Segment
    from rt.core.timestamp import format_timestamp

    # 1. Incoerenza id/index -> solleva ValueError
    with pytest.raises(ValueError, match="non corrisponde all'index"):
        Segment(
            id="seg_000001",
            index=5,
            start_seconds=0.0,
            end_seconds=5.0,
            start_formatted="00:00",
            end_formatted="00:05",
            text_raw="Test id incoerente"
        )

    # 2. Incoerenza start_formatted -> solleva ValueError
    with pytest.raises(ValueError, match="start_formatted.*non corrisponde a start_seconds"):
        Segment(
            id="seg_000001",
            index=1,
            start_seconds=120.0,  # atteso "02:00"
            end_seconds=130.0,
            start_formatted="00:00",
            end_formatted="02:10",
            text_raw="Test start_formatted incoerente"
        )

    # 3. Incoerenza end_formatted -> solleva ValueError
    with pytest.raises(ValueError, match="end_formatted.*non corrisponde a end_seconds"):
        Segment(
            id="seg_000001",
            index=1,
            start_seconds=0.0,
            end_seconds=120.0,  # atteso "02:00"
            start_formatted="00:00",
            end_formatted="00:10",
            text_raw="Test end_formatted incoerente"
        )

    # 4. Costruzione coerente -> successo
    idx = 42
    start_sec = 125.0
    end_sec = 145.0
    seg_valid = Segment(
        id=make_segment_id(idx),
        index=idx,
        start_seconds=start_sec,
        end_seconds=end_sec,
        start_formatted=format_timestamp(start_sec),
        end_formatted=format_timestamp(end_sec),
        text_raw="Test valido e coerente"
    )
    assert seg_valid.id == "seg_000042"
    assert seg_valid.index == 42
    assert seg_valid.start_formatted == "02:05"
    assert seg_valid.end_formatted == "02:25"


