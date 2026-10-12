from rt.core.sources import add_source
from rt.core.source_selection import set_primary, selection
from rt.core.segments import load_segments_json
from rt.core.lesson_paths import lesson_path
from rt.pipeline.source_update import run_source_update, prepare_source_update
from rt.pipeline.prepare import run_prepare
from rt.pipeline.outline import run_outline
from rt.pipeline.rewrite import run_rewrite
from rt.pipeline.image_placement import images_for_document
from rt.pipeline.outline import load_outline
from tests.test_materials import pdf_bytes
from tests.test_source_update import write_audio


def test_material_only_pipeline_then_audio_remains_context_until_chosen(tmp_path, monkeypatch):
    monkeypatch.setattr('rt.services.classifier.classify_units', lambda *a, **k: None)
    (tmp_path / 'info.yaml').write_text('materia: Test\ndata: 2026-10-12\nfile_audio: ""\nfase_corrente: setup_completato\n')
    lesson = str(tmp_path)
    source = add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('PRIMARY MATERIAL'))
    secondary = add_source(lesson, 'materiale', 'extra.pdf', pdf_bytes('SECONDARY CONTEXT'))
    run_prepare(lesson)
    segments = load_segments_json(lesson_path(lesson, 'segments.json')).segments
    assert len(segments) == 1 and segments[0].source_file == source.id
    assert segments[0].flags == ['materiale']
    run_outline(lesson, force_mock=True)
    run_rewrite(lesson, force_mock=True)
    old_ids = [s.id for s in segments]
    write_audio(tmp_path / 'incoming.wav')
    audio = add_source(lesson, 'audio', 'part.wav', (tmp_path / 'incoming.wav').read_bytes())
    assert selection(lesson)['principale'] == source.id
    assert not selection(lesson)['solo_ricostruzione']
    run_source_update(lesson, mock=True)
    assert [s.id for s in load_segments_json(lesson_path(lesson, 'segments.json')).segments] == old_ids
    assert images_for_document(lesson, load_outline(lesson))[0]
    set_primary(lesson, audio.id)
    assert selection(lesson)['solo_ricostruzione']
    run_source_update(lesson, mode='rebuild', mock=True)
    segments = load_segments_json(lesson_path(lesson, 'segments.json')).segments
    assert all(s.source_file == audio.id for s in segments)
    assert not selection(lesson)['solo_ricostruzione']


def test_material_conversion_not_repeated_after_update_failure(tmp_path, monkeypatch):
    import pytest
    (tmp_path / 'info.yaml').write_text('materia: Test\ndata: 2026-10-12\n')
    lesson = str(tmp_path)
    source = add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('CACHED'))
    real = __import__('rt.pipeline.outline', fromlist=['run_outline']).run_outline
    def fail(*args, **kwargs):
        raise RuntimeError('failed outline')
    monkeypatch.setattr('rt.pipeline.outline.run_outline', fail)
    with pytest.raises(RuntimeError, match='failed outline'):
        run_source_update(lesson, mock=True)
    monkeypatch.setattr('rt.core.materials._extract', lambda _: (_ for _ in ()).throw(AssertionError('must reuse cache')))
    monkeypatch.setattr('rt.pipeline.outline.run_outline', real)
    monkeypatch.setattr('rt.services.classifier.classify_units', lambda *a, **k: None)
    assert run_source_update(lesson, mock=True)['status'] == 'draft_validated'
