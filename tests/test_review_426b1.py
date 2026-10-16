"""Correzioni di revisione della 4.2.6b1: immagini dei materiali, audio e fotografie."""
import json
import os

from rt.core.idempotency import compute_file_sha256
from rt.core.models import Outline, OutlineMacro, OutlineUnit
from rt.core.sources import Source, _save, load_sources
from rt.pipeline.image_placement import load_image_placement, save_image_placement
from rt.services.audio_compaction import compact_audio_lessons, referenced_audio_files
from rt.storage import fs


def _write(path, data, mode="w"):
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    with fs.open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as stream:
        stream.write(data)


def test_save_placement_without_units_keeps_subunit_images(tmp_path):
    lesson = str(tmp_path)
    save_image_placement(lesson, {"1": ["a"]}, False, units={"1.1": ["b"]})
    # Aggiungi immagini scrive solo le macro: le immagini delle sottounità restano.
    save_image_placement(lesson, {"1": ["a", "c"]}, False)
    assert load_image_placement(lesson)["units"] == {"1.1": ["b"]}


def test_assignment_replaces_only_its_own_images(tmp_path):
    from rt.pipeline.material_mapping import STATE_FILE, assign_material_pages
    lesson = str(tmp_path)
    _write(os.path.join(lesson, "info.yaml"), "titolo: Prova\nallega_materiali: 'false'\n")
    _write(os.path.join(lesson, STATE_FILE), json.dumps({"macros": {"1": ["old"]}, "units": {"1.1": ["oldu"]}}))
    save_image_placement(lesson, {"1": ["old", "manual"]}, False, units={"1.1": ["oldu", "web"]})
    outline = Outline(lesson_title="Prova", macro_sections=[OutlineMacro(id="1", title="Uno", units=[
        OutlineUnit(id="1.1", title="Uno uno", start_segment_id="seg_000001", end_segment_id="seg_000001")])])
    assign_material_pages(lesson, outline, mock=True)
    placement = load_image_placement(lesson)
    assert placement["macros"] == {"1": ["manual"]}
    assert placement["units"] == {"1.1": ["web"]}


def _lesson_with_wav_and_snapshot(lesson):
    wav = os.path.join(lesson, "sources", "src_000001", "lezione.wav")
    _write(wav, b"RIFF" + b"\x00" * 4000, "wb")
    source = Source(id="src_000001", tipo="audio", file="sources/src_000001/lezione.wav",
                    impronta=compute_file_sha256(wav), aggiunta_il="2026-10-01T10:00:00Z", ordine=1)
    _write(os.path.join(lesson, "info.yaml"), "titolo: Prova\nfile_audio: audio-new.m4a\n")
    _save(lesson, [source])
    snapshot = os.path.join(lesson, "history", "ver_000001")
    _write(os.path.join(snapshot, "sources.json"), json.dumps([source.model_dump()]))
    _write(os.path.join(snapshot, "info.yaml"), "titolo: Prova\nfile_audio: audio-old.m4a\n")
    _write(os.path.join(lesson, "audio-old.m4a"), b"old", "wb")
    _write(os.path.join(lesson, "audio-new.m4a"), b"new", "wb")
    _write(os.path.join(lesson, "audio-orphan.m4a"), b"orphan", "wb")
    return snapshot


def test_merged_audio_named_by_a_snapshot_is_not_orphan(tmp_path):
    lesson = str(tmp_path)
    _lesson_with_wav_and_snapshot(lesson)
    referenced = referenced_audio_files(lesson)
    assert "audio-old.m4a" in referenced and "audio-new.m4a" in referenced
    assert "audio-orphan.m4a" not in referenced


def test_compaction_updates_snapshots_and_keeps_their_audio(tmp_path, monkeypatch):
    lesson = str(tmp_path)
    snapshot = _lesson_with_wav_and_snapshot(lesson)

    def fake_transcode(src, dst):
        with open(dst, "wb") as stream:
            stream.write(b"m4a")
        return True
    monkeypatch.setattr("rt.services.audio_compaction.transcode_audio_for_storage", fake_transcode)
    result = compact_audio_lessons([lesson])
    assert result["file_convertiti"] == 1 and result["file_orfani_cancellati"] == 1
    current = load_sources(lesson)[0]
    assert current.file == "sources/src_000001/lezione.m4a"
    with fs.open(os.path.join(snapshot, "sources.json"), encoding="utf-8") as stream:
        old = json.load(stream)[0]
    # La versione salvata indica il file convertito con la sua impronta: ripristinarla non fallisce.
    assert old["file"] == current.file and old["impronta"] == current.impronta
    assert fs.isfile(os.path.join(lesson, "audio-old.m4a"))
    assert not fs.isfile(os.path.join(lesson, "audio-orphan.m4a"))
