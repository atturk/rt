import json

from rt.core.models import Segment
from rt.core.segments import insert_source_segments, load_segments_json, save_segments_json
from rt.core.sources import add_source


def segment(number, text):
    return Segment(id=f"seg_{number:06d}", index=number, start_seconds=0,
                   end_seconds=1, start_formatted="00:00", end_formatted="00:01", text_raw=text)


def test_inserting_source_preserves_existing_ids_and_human_data(tmp_path):
    (tmp_path / "info.yaml").write_text("materia: Test\n")
    path = str(tmp_path / "segments.json")
    save_segments_json([segment(1, "original one"), segment(2, "original two")], path)
    human = {
        "review_decisions.json": {"decisions": [{"issue_id": "issue-1", "decision": "accepted", "notes": "seg_000002"}]},
        "study_notes.json": {"notes": [{"segment_id": "seg_000002", "text": "my note"}]},
        "highlights.json": [{"segment_id": "seg_000001", "quote": "original one"}],
        "study_units.json": [{"unit_id": "1.1", "state": "studied"}],
    }
    for name, data in human.items():
        (tmp_path / name).write_text(json.dumps(data))
    before = {name: (tmp_path / name).read_bytes() for name in human}
    source = add_source(str(tmp_path), "appunti", "notes.txt", b"inserted", ordine=1)
    result = insert_source_segments(load_segments_json(path).segments, [segment(1, "inserted")], source.id, 0)
    save_segments_json(result, path)
    saved = load_segments_json(path).segments
    assert [s.id for s in saved] == ["seg_000003", "seg_000001", "seg_000002"]
    assert [s.index for s in saved] == [1, 2, 3]
    assert saved[0].source_file == source.id
    assert {s.id: s.text_raw for s in saved}["seg_000002"] == "original two"
    assert all((tmp_path / name).read_bytes() == data for name, data in before.items())


def test_counter_does_not_reuse_removed_ids():
    result = insert_source_segments([segment(1, "old")], [segment(1, "new")], "src-new", 1, next_number=10)
    assert result[-1].id == "seg_000010"
