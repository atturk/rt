"""Rilettura esplicita delle fonti: cache, ID, revisione e ripristino dopo errori."""
from pathlib import Path

import pytest

from rt.core.lesson_paths import lesson_path
from rt.core.sources import add_source, load_sources
from rt.core.segments import load_segments_json
from rt.core.update_history import undo_update
from rt.pipeline import source_update as update
from tests.test_source_update import legacy, write_audio
from tests.test_materials import png_bytes


def prepared(tmp_path, monkeypatch):
    legacy(tmp_path)
    lesson = str(tmp_path)
    monkeypatch.setattr('rt.services.classifier.classify_units', lambda *a, **k: None)
    monkeypatch.setattr(update, '_duration', lambda _: 2.0)
    calls = []
    def transcribe(path, mock):
        calls.append(path)
        from rt.core.models import Segment
        return [Segment(id='seg_000001', index=1, start_seconds=0, end_seconds=1,
                        start_formatted='00:00', end_formatted='00:01', text_raw='Nuova trascrizione')]
    monkeypatch.setattr(update, '_transcribe', transcribe)
    update.prepare_source_update(lesson, mock=True)
    return lesson, calls


def test_reingest_transcribes_every_audio_and_does_not_reuse_segment_ids(tmp_path, monkeypatch):
    lesson, calls = prepared(tmp_path, monkeypatch)
    write_audio(tmp_path / 'second.wav')
    monkeypatch.setattr('rt.pipeline.setup.transcode_audio_for_storage', lambda *a: False)
    add_source(lesson, 'audio', 'second.wav', (tmp_path / 'second.wav').read_bytes())
    def merge(paths, target):
        Path(target).write_bytes(b'audio unito')
    monkeypatch.setattr('rt.pipeline.setup.merge_audio_for_transcription', merge)
    update.prepare_source_update(lesson, mock=True)
    calls.clear()
    old_ids = {int(s.id[4:]) for s in load_segments_json(str(tmp_path / 'segments.json')).segments}
    update.run_source_update(lesson, mode='rebuild', mock=True)
    assert calls == []
    result = update.run_source_update(lesson, mode='rebuild', mock=True, reingest=True)
    assert set(calls) == {str(tmp_path / s.file) for s in load_sources(lesson) if s.tipo == 'audio'}
    assert len(calls) == 2
    assert min(int(s.id[4:]) for s in load_segments_json(str(tmp_path / 'segments.json')).segments) > max(old_ids)
    assert result['build']['status'] == 'completed'
    assert Path(lesson_path(lesson, 'rielaborato.md')).is_file()


def test_material_refresh_ignores_both_complete_and_per_page_cache(tmp_path, monkeypatch):
    from rt.core.materials import material_pages
    legacy(tmp_path)
    source = add_source(str(tmp_path), 'materiale', 'foto.png', png_bytes())
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda *a: calls.append(1) or f'Lettura {len(calls)}')
    assert material_pages(str(tmp_path), source)[0]['testo'] == 'Lettura 1'
    assert material_pages(str(tmp_path), source)[0]['testo'] == 'Lettura 1'
    assert material_pages(str(tmp_path), source, refresh=True)[0]['testo'] == 'Lettura 2'
    assert len(calls) == 2


def test_reingest_failure_restores_material_cache_and_source_state(tmp_path, monkeypatch):
    from rt.core.materials import material_pages
    lesson, _ = prepared(tmp_path, monkeypatch)
    source = add_source(lesson, 'materiale', 'foto.png', png_bytes())
    monkeypatch.setattr('rt.core.materials._describe', lambda *a: 'Prima lettura')
    material_pages(lesson, source)
    update.prepare_source_update(lesson, mock=True)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / 'materials').rglob('*') if p.is_file()}
    cache = update._read_state(lesson)
    segments = (tmp_path / 'segments.json').read_bytes()
    monkeypatch.setattr('rt.core.materials._describe', lambda *a: 'Seconda lettura')
    def fail(*args, **kwargs):
        update.prepare_source_update(lesson, mock=True, reingest=True)
        assert material_pages(lesson, source)[0]['testo'] == 'Seconda lettura'
        (tmp_path / 'materials' / 'nuovo.tmp').write_bytes(b'parziale')
        raise RuntimeError('Errore dopo la rilettura')
    monkeypatch.setattr(update, '_run_source_update', fail)
    with pytest.raises(RuntimeError, match='dopo la rilettura'):
        update.run_source_update(lesson, mode='rebuild', mock=True, reingest=True)
    after = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / 'materials').rglob('*') if p.is_file()}
    assert after == before
    assert update._read_state(lesson)['sources'] == cache['sources']
    assert update._read_state(lesson)['next_segment'] > cache['next_segment']
    assert (tmp_path / 'segments.json').read_bytes() == segments


def test_build_failure_is_inside_the_reingest_rollback(tmp_path, monkeypatch):
    lesson, _ = prepared(tmp_path, monkeypatch)
    cache = update._read_state(lesson)['sources']
    segments = (tmp_path / 'segments.json').read_bytes()
    def fail(*args, **kwargs):
        (tmp_path / 'parziale.md').write_text('Documento parziale', encoding='utf-8', newline='\n')
        raise RuntimeError('Documento non scritto')
    monkeypatch.setattr('rt.pipeline.build.run_build', fail)
    with pytest.raises(RuntimeError, match='Documento non scritto'):
        update.run_source_update(lesson, mode='rebuild', mock=True, reingest=True)
    assert not (tmp_path / 'parziale.md').exists()
    assert (tmp_path / 'segments.json').read_bytes() == segments
    assert update._read_state(lesson)['sources'] == cache


def test_reingest_requires_available_originals_and_rebuild(tmp_path, monkeypatch):
    lesson, calls = prepared(tmp_path, monkeypatch)
    assert update.reingest_availability(lesson)['reingest_available']
    with pytest.raises(ValueError, match='Ricostruisci'):
        update.run_source_update(lesson, mode='extend', reingest=True)
    (tmp_path / 'original.wav').unlink()
    assert update.reingest_availability(lesson) == {'reingest_available': False, 'reingest_reason': 'Audio originale non disponibile.'}
    with pytest.raises(ValueError, match='Audio originale'):
        update.run_source_update(lesson, mode='rebuild', reingest=True)
    assert calls == []
    empty = tmp_path / 'vuota'; empty.mkdir()
    (empty / 'info.yaml').write_text('materia: Test\nfile_audio: \'\'\n', encoding='utf-8', newline='\n')
    assert not update.reingest_availability(str(empty))['reingest_available']


def test_review_runs_before_document_without_accepting_pending_corrections(tmp_path, monkeypatch):
    lesson, _ = prepared(tmp_path, monkeypatch)
    from rt.pipeline.review import run_review
    from rt.pipeline.build import write_automatic_documents
    order = []
    def review(*a, **kw):
        order.append('revisione')
        return run_review(*a, **kw)
    def document(*a, **kw):
        order.append('documento')
        return write_automatic_documents(*a, **kw)
    monkeypatch.setattr('rt.pipeline.review.run_review', review)
    monkeypatch.setattr('rt.pipeline.build.write_automatic_documents', document)
    result = update.run_source_update(lesson, mode='rebuild', mock=True, reingest=True, with_review=True)
    assert result['pending_review'] > 0
    assert order == ['revisione', 'documento']
    from rt.core.state import read_info_yaml
    assert read_info_yaml(str(tmp_path / 'info.yaml'))['fase_corrente'] != 'completato'
    document_path = Path(lesson_path(lesson, 'rielaborato.md'))
    assert document_path.is_file()
    undo_update(lesson)
    assert not document_path.exists()


def test_update_request_and_api_reject_unavailable_reingest(api_client, rt_db, tmp_path, monkeypatch):
    from rt.api.routers.lesson_sources import UpdateRequest
    from tests.api_support import isolated_workspace, make_lesson
    with pytest.raises(ValueError):
        UpdateRequest(mode='extend', reingest=True)
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    view = api_client.get(f'/api/v1/lessons/{lid}/sources').json()
    assert view['reingest_available'] is False
    response = api_client.post(f'/api/v1/lessons/{lid}/update', json={'mode': 'rebuild', 'reingest': True})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'reingest_unavailable'


def test_snapshot_restores_material_cache_on_database_storage(rt_db, tmp_path):
    from rt.storage import fs
    from rt.core.update_history import snapshot_update
    lesson = fs.create_db_lesson(str(tmp_path / 'virtual'))
    for name, text in {'sources.json': '[]', 'info.yaml': 'materia: Test\n', 'source_update.json': '{"next_segment": 1, "sources": {}}'}.items():
        with fs.open(lesson_path(lesson, name), 'w') as stream:
            stream.write(text)
    old = {'materials/abc/pages.json': b'prima', 'materials/abc/page-1.png': b'immagine prima'}
    for name, data in old.items():
        with fs.open(str(Path(lesson) / name), 'wb') as stream:
            stream.write(data)
    snapshot_update(lesson)
    for name in (*old, 'materials/abc/page-2.json'):
        with fs.open(str(Path(lesson) / name), 'wb') as stream:
            stream.write(b'dopo')
    undo_update(lesson)
    for name, data in old.items():
        with fs.open(str(Path(lesson) / name), 'rb') as stream:
            assert stream.read() == data
    assert not fs.isfile(str(Path(lesson) / 'materials/abc/page-2.json'))


@pytest.mark.parametrize('database', [False, True])
def test_failed_cache_restore_keeps_current_data_intact(rt_db, tmp_path, monkeypatch, database):
    from rt.storage import fs
    from rt.core.update_history import snapshot_update
    lesson = str(tmp_path / 'lezione')
    if database:
        fs.create_db_lesson(lesson)
    else:
        fs.makedirs(lesson)
    for name, text in {'sources.json': '[]', 'info.yaml': 'materia: Test\n', 'source_update.json': '{"next_segment": 1, "sources": {}}'}.items():
        with fs.open(lesson_path(lesson, name), 'w') as stream:
            stream.write(text)
    cached = {'materials/abc/a.png': png_bytes(), 'materials/abc/z.json': b'prima'}
    for name, data in cached.items():
        fs.makedirs(str((Path(lesson) / name).parent), exist_ok=True)
        with fs.open(str(Path(lesson) / name), 'wb') as stream:
            stream.write(data)
    snapshot_update(lesson)
    for name in cached:
        with fs.open(str(Path(lesson) / name), 'wb') as stream:
            stream.write(b'dati attuali')
    copy = fs.copy2
    failed = False
    def fail_once(source, target):
        nonlocal failed
        normalized = str(source).replace('\\', '/')
        if not failed and '/history/' in normalized and normalized.endswith('/z.json'):
            failed = True
            raise OSError('Errore nella copia della cache')
        return copy(source, target)
    monkeypatch.setattr(fs, 'copy2', fail_once)
    with pytest.raises(OSError, match='copia della cache'):
        undo_update(lesson)
    assert failed
    for name in cached:
        with fs.open(str(Path(lesson) / name), 'rb') as stream:
            assert stream.read() == b'dati attuali'


def test_missing_uncached_material_still_reports_why_reingest_is_unavailable(tmp_path, monkeypatch):
    from rt.services.sources_view import sources_view
    lesson, _ = prepared(tmp_path, monkeypatch)
    source = add_source(lesson, 'materiale', 'foto.png', png_bytes())
    (tmp_path / source.file).unlink()
    view = sources_view(lesson)
    assert view['reingest_available'] is False
    assert view['reingest_reason'] == 'Documento originale non disponibile.'
    assert next(s for s in view['sources'] if s.id == source.id).pagine is None
