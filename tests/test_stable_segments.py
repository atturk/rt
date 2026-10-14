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


def test_removing_original_audio_never_assigns_its_asr_risks_to_another_source(tmp_path):
    from rt.core.sources import remove_source
    from rt.core.asr_risk import detect_statistical_asr_risks
    from rt.core.models import Draft, DraftUnit
    from rt.pipeline.rewrite import save_draft
    from rt.core.lesson_paths import lesson_path
    lesson = str(tmp_path)
    (tmp_path / "info.yaml").write_text("file_audio: original.wav\n")
    source = add_source(lesson, "audio", "new.wav", b"new audio")
    remove_source(lesson, "src_000001")
    old_raw = {"transcriptSegments": [{"text": "old audio", "wordRange": {"startIndex": 0, "endIndexExclusive": 1}}],
               "wordTimestamps": [{"confidence": 0.01}]}
    with open(lesson_path(lesson, "trascritto grezzo.json"), "w") as stream:
        json.dump(old_raw, stream)
    new = segment(2, "new audio").model_copy(update={"index": 1, "source_file": source.id})
    save_segments_json([new], lesson_path(lesson, "segments.json"))
    save_draft(Draft(units=[DraftUnit(unit_id="1.1", title="New", start_segment_id=new.id,
        end_segment_id=new.id, source_segment_ids=[new.id], content="new audio")]), lesson)
    assert detect_statistical_asr_risks(lesson) == []


def test_original_asr_segment_and_word_times_follow_composed_audio_clock(tmp_path):
    from rt.core.sources import load_sources
    from rt.core.asr_risk import detect_statistical_asr_risks
    from rt.core.models import Draft, DraftUnit
    from rt.pipeline.rewrite import save_draft
    from rt.core.lesson_paths import lesson_path
    lesson = str(tmp_path)
    (tmp_path / "info.yaml").write_text("file_audio: original.wav\n")
    load_sources(lesson)
    raw = {"transcriptSegments": [{"text": "original", "startMs": 0, "endMs": 1000,
               "wordRange": {"startIndex": 0, "endIndexExclusive": 1}}],
           "wordTimestamps": [{"word": "original", "confidence": 0.01, "startMs": 100, "endMs": 200}]}
    with open(lesson_path(lesson, "trascritto grezzo.json"), "w") as stream:
        json.dump(raw, stream)
    local = segment(1, "original").model_copy(update={"source_file": "src_000001"})
    with open(lesson_path(lesson, "source_update.json"), "w") as stream:
        json.dump({"sources": {"src_000001": {"segments": [local.model_dump()]}}}, stream)
    shifted = local.model_copy(update={"start_seconds": 10, "end_seconds": 11,
                                       "start_formatted": "00:10", "end_formatted": "00:11"})
    save_segments_json([shifted], lesson_path(lesson, "segments.json"))
    save_draft(Draft(units=[DraftUnit(unit_id="1.1", title="Original", start_segment_id=shifted.id,
        end_segment_id=shifted.id, source_segment_ids=[shifted.id], content="original")]), lesson)
    risk = detect_statistical_asr_risks(lesson)[0].asr_segments[0]
    assert risk.start_s == 10 and risk.end_s == 11
    assert risk.uncertain_words[0].start_s == 10.1 and risk.uncertain_words[0].end_s == 10.2
    # Togliere dal registro è ancora pendente: la lezione corrente non cambia.
    from rt.core.sources import remove_source
    remove_source(lesson, "src_000001")
    assert detect_statistical_asr_risks(lesson)[0].asr_segments[0] == risk
