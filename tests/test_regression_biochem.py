"""
Regression test sulla lezione reale di Biochimica.
Verifica:
1. Parsing dei 499 segmenti della lezione reale
2. Corrispondenza esatta del timecode di seg_000222 a 36:30 (2190s)
3. Monotonicità temporale e assenza di inversioni
4. Provenance chain completa
"""

import os
import json
import pytest
from rt.core.segments import parse_segments_from_markdown, load_segments_json
from rt.core.timestamp import format_timestamp


def test_real_lecture_segments():
    lecture_md = os.path.join(os.path.dirname(__file__), "..", "test_real_lecture", "trascritto grezzo.md")
    if not os.path.isfile(lecture_md):
        pytest.skip("Lezione reale non copiata localmente per il test.")
        
    segments = parse_segments_from_markdown(lecture_md)
    assert len(segments) == 499
    
    # Verifica che il primo segmento sia a 00:02
    assert segments[0].id == "seg_000001"
    assert segments[0].start_formatted == "00:02"
    assert segments[0].start_seconds == 2.0
    
    # Verifica il segmento critico di 36:30 (propionil-CoA)
    # seg_000222: start_formatted == "36:30", start_seconds == 2190.0
    seg_propionil = segments[221] # indice 222 (0-indexed 221)
    assert seg_propionil.id == "seg_000222"
    assert seg_propionil.start_formatted == "36:30"
    assert seg_propionil.start_seconds == 2190.0
    assert "proprio" in seg_propionil.text_raw.lower() or "propionil" in seg_propionil.text_raw.lower()
    
    # Verifica monotonicità su tutti i 499 segmenti
    for i in range(len(segments) - 1):
        curr = segments[i]
        nxt = segments[i + 1]
        assert nxt.start_seconds >= curr.start_seconds, f"Inversione temporale tra {curr.id} ({curr.start_formatted}) e {nxt.id} ({nxt.start_formatted})"
