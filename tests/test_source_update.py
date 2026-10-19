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
    assert not sources_pending(lesson)
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


def test_force_prepare_after_undo_preserves_legacy_duration_and_pending_sources(tmp_path, monkeypatch):
    from rt.pipeline.prepare import run_prepare
    from rt.core.update_history import undo_update
    from rt.pipeline.source_update import run_source_update, _read_state
    legacy(tmp_path)
    lesson = str(tmp_path)
    with open(lesson_path(lesson, "trascritto grezzo.json"), "w") as stream:
        json.dump({"segments": [{"start": 0, "end": 1000, "text": "original"}]}, stream)
    run_prepare(lesson, force=True)
    add_source(lesson, "appunti", "pending.txt", b"pending notes")
    monkeypatch.setattr("rt.services.classifier.classify_units", lambda *a, **k: None)
    run_source_update(lesson, mock=True)
    undo_update(lesson)
    assert _read_state(lesson)["sources"] == {}
    result = run_prepare(lesson, force=True)
    assert result["duration_seconds"] == 1
    assert [s.id for s in load_segments_json(str(tmp_path / "segments.json")).segments] == ["seg_000001"]
    assert sources_pending(lesson)
    assert _read_state(lesson)["next_segment"] >= 3


def test_legacy_lesson_with_missing_audio_can_add_notes(tmp_path, monkeypatch):
    from rt.pipeline.source_update import run_source_update, _read_state
    legacy(tmp_path)
    lesson = str(tmp_path)
    from rt.core.sources import load_sources
    load_sources(lesson)
    (tmp_path / "original.wav").unlink()
    add_source(lesson, "appunti", "notes.txt", b"notes")
    monkeypatch.setattr("rt.services.classifier.classify_units", lambda *a, **k: None)
    result = run_source_update(lesson, mode="rebuild", mock=True)
    assert result["status"] == "draft_validated"
    assert _read_state(lesson)["sources"]["src_000001"]["duration"] == 1
    assert [s.text_raw for s in load_segments_json(str(tmp_path / "segments.json")).segments] == ["original", "notes"]


def test_prepare_source_update_cleans_up_old_merged_audio(tmp_path, monkeypatch):
    legacy(tmp_path)
    lesson = str(tmp_path)
    from rt.core.sources import load_sources
    load_sources(lesson)
    monkeypatch.setattr("rt.pipeline.source_update._duration", lambda p: 2.0)
    old_merged = tmp_path / "audio-old123.m4a"
    old_merged.write_bytes(b"old merged audio")
    from rt.core.state import update_info_yaml
    update_info_yaml(str(tmp_path / "info.yaml"), {"file_audio": "audio-old123.m4a"})
    prepare_source_update(lesson)
    assert not old_merged.exists()


def test_prepare_source_update_multiple_audios_cleans_previous_merged(tmp_path, monkeypatch):
    legacy(tmp_path)
    lesson = str(tmp_path)
    from rt.core.sources import load_sources
    load_sources(lesson)
    monkeypatch.setattr("rt.pipeline.source_update._duration", lambda p: 2.0)
    old_merged = tmp_path / "audio-previous.m4a"
    old_merged.write_bytes(b"previous merged audio")
    from rt.core.state import update_info_yaml
    update_info_yaml(str(tmp_path / "info.yaml"), {"file_audio": "audio-previous.m4a"})
    write_audio(tmp_path / "second.wav", 2)
    monkeypatch.setattr("rt.pipeline.setup.transcode_audio_for_storage", lambda inp, out: False)
    add_source(lesson, "audio", "second.wav", (tmp_path / "second.wav").read_bytes())
    monkeypatch.setattr("rt.pipeline.source_update._transcribe", lambda p, m: [
        Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=1,
                start_formatted="00:00", end_formatted="00:01", text_raw="new")
    ])
    def mock_merge(paths, target):
        with open(target, "wb") as f:
            f.write(b"new merged")
    monkeypatch.setattr("rt.pipeline.setup.merge_audio_for_transcription", mock_merge)
    prepare_source_update(lesson)
    assert not old_merged.exists()
    from rt.core.state import read_info_yaml
    new_audio = read_info_yaml(str(tmp_path / "info.yaml")).get("file_audio")
    assert new_audio.startswith("audio-") and new_audio != "audio-previous.m4a"
    assert (tmp_path / new_audio).exists()



def test_reingest_runs_automatic_enrichment_only_when_enabled(tmp_path, monkeypatch):
    from rt.pipeline.source_update import run_source_update
    from rt.core.config import load_config
    from rt.services import enrichment_service
    from tests.test_source_reingest import prepared
    lesson, _ = prepared(tmp_path, monkeypatch)
    cfg = load_config()
    calls = []
    monkeypatch.setattr('rt.services.enrichment_service.analyze', lambda *a, **k: calls.append(k['ctx']) or {'ok': True})
    monkeypatch.setattr('rt.core.config.load_config', lambda: cfg)
    cfg.classifier.jobs['enrichment'].mode = 'pipeline'
    assert run_source_update(lesson, mode='rebuild', mock=True, reingest=True)['enrichment'] == {'ok': True}
    assert len(calls) == 1 and calls[0] is not None
    cfg.classifier.jobs['enrichment'].mode = 'manual'
    assert run_source_update(lesson, mode='rebuild', mock=True, reingest=True)['enrichment']['skipped'] == 'manual'
    assert len(calls) == 1
    assert 'enrichment' not in run_source_update(lesson, mode='extend', mock=True)
    assert len(calls) == 1


import pytest


@pytest.mark.parametrize('mode', ['extend', 'rebuild'])
@pytest.mark.parametrize('fails', [False, True])
def test_source_update_approves_outline_before_rewrite_and_restores_on_failure(tmp_path, monkeypatch, mode, fails):
    from rt.pipeline.source_update import run_source_update
    from rt.pipeline.rewrite import run_rewrite
    from rt.services.outline_service import is_outline_approved, get_outline_approval
    from rt.services import jobs
    legacy(tmp_path)
    lesson = str(tmp_path)
    monkeypatch.setattr('rt.services.classifier.classify_units', lambda *a, **k: None)
    run_source_update(lesson, mode='rebuild', mock=True)
    with open(lesson_path(lesson, 'outline.json'), 'rb') as stream:
        old_outline = stream.read()
    old_approval = get_outline_approval(lesson)
    add_source(lesson, 'appunti', 'new.txt', b'new notes')
    resumed = []
    monkeypatch.setattr(jobs, 'resume_waiting_jobs', lambda *a: resumed.append(a))

    def rewrite(*a, **kw):
        assert is_outline_approved(lesson)
        assert get_outline_approval(lesson)['actor'] == 'source_update'
        if fails:
            raise RuntimeError('rewrite failed')
        return run_rewrite(*a, **kw)

    monkeypatch.setattr('rt.pipeline.rewrite.run_rewrite', rewrite)
    if fails:
        with pytest.raises(RuntimeError, match='rewrite failed'):
            run_source_update(lesson, mode=mode, mock=True)
        with open(lesson_path(lesson, 'outline.json'), 'rb') as stream:
            assert stream.read() == old_outline
        assert get_outline_approval(lesson) == old_approval
    else:
        run_source_update(lesson, mode=mode, mock=True)
    assert is_outline_approved(lesson)
    assert resumed == []
