import json
import wave

from rt.core.lesson_paths import lesson_path
from rt.core.models import Segment
from rt.core.segments import load_segments_json, save_segments_json
from rt.core.sources import add_source, remove_source
from rt.pipeline.source_update import prepare_source_update, sources_pending


def write_audio(path, seconds=2):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * int(16000 * seconds))


def legacy(tmp_path):
    (tmp_path / "info.yaml").write_text("file_audio: original.wav\nmateria: Test\ndata: 2026-10-12\nfase_corrente: setup_completato\n")
    write_audio(tmp_path / "original.wav")
    original = Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=1,
                       start_formatted="00:00", end_formatted="00:01", text_raw="original")
    save_segments_json([original], str(tmp_path / "segments.json"))


def test_audio_insertion_transcribes_only_new_source_and_shifts_times(tmp_path, monkeypatch):
    legacy(tmp_path)
    lesson = str(tmp_path)
    write_audio(tmp_path / "new.wav", 3)
    original_bytes = (tmp_path / "original.wav").read_bytes()
    source = add_source(lesson, "audio", "part.wav", (tmp_path / "new.wav").read_bytes(), ordine=1)
    calls = []
    def transcribe(path, mock):
        calls.append(path)
        return [Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=2,
                        start_formatted="00:00", end_formatted="00:02", text_raw="new")]
    monkeypatch.setattr("rt.pipeline.source_update._transcribe", transcribe)
    assert sources_pending(lesson)
    result = prepare_source_update(lesson)
    assert calls == [str(tmp_path / source.file)]
    assert [s.id for s in result["segments"]] == ["seg_000002", "seg_000001"]
    assert result["segments"][1].start_seconds == 3
    assert result["segments"][1].source_file == "src_000001"
    assert (tmp_path / "original.wav").read_bytes() == original_bytes
    assert not sources_pending(lesson)
    prepare_source_update(lesson)
    assert len(calls) == 1
    remove_source(lesson, source.id)
    assert sources_pending(lesson)
    assert prepare_source_update(lesson)["segments"][0].start_seconds == 0


def test_notes_use_paragraphs_and_do_not_shift_audio(tmp_path):
    legacy(tmp_path)
    lesson = str(tmp_path)
    source = add_source(lesson, "appunti", "notes.txt", b"one paragraph\n\ntwo paragraph", ordine=1)
    result = prepare_source_update(lesson)["segments"]
    assert [s.id for s in result] == ["seg_000002", "seg_000003", "seg_000001"]
    assert all(s.flags == ["appunti"] and s.end_seconds == .001 and s.source_file == source.id for s in result[:2])
    assert result[-1].start_seconds == 0
    assert [s.index for s in load_segments_json(str(tmp_path / "segments.json")).segments] == [1, 2, 3]
