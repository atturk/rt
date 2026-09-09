"""
tests/test_audio_clip.py
rt.core.audio_clip.resolve_unit_time_range: mappa una DraftUnit sull'intervallo temporale
nell'audio originale tramite i Segment corrispondenti (stessa logica già usata più volte
inline in rt/pipeline/issue_review.py, qui centralizzata e riusata dal recall per il
bottone 🔊).
"""
import pytest

from rt.core.models import Segment, DraftUnit
from rt.core.audio_clip import resolve_unit_time_range


def _fmt(seconds):
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def _seg(index, start, end):
    return Segment(
        id=f"seg_{index:06d}", index=index, start_seconds=start, end_seconds=end,
        start_formatted=_fmt(start), end_formatted=_fmt(end), text_raw="testo",
    )


def _unit(unit_id, start_seg_id, end_seg_id):
    return DraftUnit(
        unit_id=unit_id, title="Titolo", content="Contenuto.",
        start_segment_id=start_seg_id, end_segment_id=end_seg_id,
        source_segment_ids=[start_seg_id, end_seg_id],
    )


def test_resolves_start_and_end_seconds_from_segments():
    segments = [_seg(1, 10.0, 18.0), _seg(2, 20.0, 30.0), _seg(3, 35.0, 42.0)]
    unit = _unit("1.1", "seg_000001", "seg_000003")
    start_s, end_s = resolve_unit_time_range(unit, segments)
    assert start_s == 10.0
    assert end_s == 42.0


def test_single_segment_unit():
    segments = [_seg(1, 10.0, 18.0)]
    unit = _unit("1.1", "seg_000001", "seg_000001")
    start_s, end_s = resolve_unit_time_range(unit, segments)
    assert (start_s, end_s) == (10.0, 18.0)


def test_raises_when_start_segment_missing():
    segments = [_seg(2, 20.0, 30.0)]
    unit = _unit("1.1", "seg_000001", "seg_000002")
    with pytest.raises(ValueError):
        resolve_unit_time_range(unit, segments)


def test_raises_when_end_segment_missing():
    segments = [_seg(1, 10.0, 18.0)]
    unit = _unit("1.1", "seg_000001", "seg_000002")
    with pytest.raises(ValueError):
        resolve_unit_time_range(unit, segments)
