import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from rt.core import archive
from rt.core.materials import material_pages
from rt.core.sources import add_source
from tests.test_materials import pdf_bytes, png_bytes


def lesson(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    (path / 'info.yaml').write_text('materia: Test\n')
    return str(path)


def test_shared_pages_and_filters(tmp_path, monkeypatch):
    first, second = lesson(tmp_path, 'one'), lesson(tmp_path, 'two')
    content = png_bytes()
    one = add_source(first, 'materiale', 'photo.png', content)
    describe = Mock(return_value='Una figura')
    monkeypatch.setattr('rt.core.materials._describe', describe)
    pages = material_pages(first, one)
    two = add_source(second, 'materiale', 'photo.png', content)
    monkeypatch.setattr('rt.core.materials._extract', Mock(side_effect=AssertionError('estrazione ripetuta')))
    assert material_pages(second, two) == pages
    assert describe.call_count == 1
    archive.save_meta(one.impronta, {'ignorate': [1]})
    assert archive.pages_for_use(one.impronta) == []
    archive.save_meta(one.impronta, {'ignorate': [], 'eliminate': [1]})
    assert archive.pages_for_use(one.impronta, [1]) == []
    archive.save_meta(one.impronta, {'eliminate': []})
    assert archive.pages_for_use(one.impronta, [2]) == []
    assert archive.pages_for_use(one.impronta, [1]) == pages


def test_legacy_cache_import(tmp_path, monkeypatch):
    directory = lesson(tmp_path, 'legacy')
    source = add_source(directory, 'materiale', 'old.pdf', pdf_bytes())
    old = Path(directory) / 'materials' / source.impronta
    old.mkdir(parents=True)
    (old / 'page-1-1.png').write_bytes(png_bytes())
    (old / 'pages.json').write_text(json.dumps({'impronta': source.impronta, 'pages': [
        {'numero': 1, 'testo': 'Già letto', 'has_figures': True,
         'immagini': [f'materials/{source.impronta}/page-1-1.png']}]}))
    monkeypatch.setattr('rt.core.materials._extract', Mock(side_effect=AssertionError('modello')))
    assert material_pages(directory, source)[0]['testo'] == 'Già letto'
    assert Path(archive.page_image_path(source.impronta, 'page-1-1.png')).exists()
    assert old.exists()


def test_audio_alias_and_engine_cache(tmp_path, monkeypatch):
    one, two = lesson(tmp_path, 'one'), lesson(tmp_path, 'two')
    def convert(_input, output):
        Path(output).write_bytes(b'optimized audio')
        return True
    converter = Mock(side_effect=convert)
    monkeypatch.setattr('rt.pipeline.setup.transcode_audio_for_storage', converter)
    first = add_source(one, 'audio', 'recording.wav', b'original wav')
    archive.store_transcript(first.impronta, 'macparakeet', {'segments': [], 'duration': 0})
    second = add_source(two, 'audio', 'recording.wav', b'original wav')
    assert first.impronta == second.impronta
    assert converter.call_count == 1
    import hashlib
    upload = hashlib.sha256(b'original wav').hexdigest()
    assert archive.find(upload)['impronta'] == first.impronta
    assert archive.cached_transcript(upload, 'parakeet') is None
    from rt.pipeline.source_update import _transcribe
    assert _transcribe(str(Path(two) / second.file)) == []


def test_backfill_once(tmp_path, monkeypatch):
    from rt.services.archive_backfill import archive_backfill
    directories = [lesson(tmp_path, str(i)) for i in range(2)]
    for directory in directories:
        source = add_source(directory, 'materiale', 'old.pdf', pdf_bytes(directory))
        old = Path(directory) / 'materials' / source.impronta
        old.mkdir(parents=True)
        (old / 'pages.json').write_text(json.dumps({'impronta': source.impronta,
            'pages': [{'numero': 1, 'testo': 'testo', 'immagini': [], 'has_figures': False}]}))
        images = Path(directory) / 'assets/images'
        images.mkdir(parents=True)
        (images / 'photo.png').write_bytes(png_bytes())
    monkeypatch.setattr('rt.core.materials._describe', Mock(side_effect=AssertionError('modello')))
    archive_backfill(directories)
    assert archive.read_json(str(Path(archive.archive_dir()) / 'indice.json'))['backfill_done']
    assert len([p for p in Path(archive.archive_dir()).iterdir() if p.is_dir()]) == 3
    monkeypatch.setattr('rt.services.archive_backfill.load_sources', Mock(side_effect=AssertionError), raising=False)
    archive_backfill(['missing'])


def test_upgrade_only_adds_images(tmp_path, monkeypatch):
    directory = lesson(tmp_path, 'upgrade')
    source = add_source(directory, 'materiale', 'document.pdf', pdf_bytes())
    source = source.model_copy(update={'estrai': 'testo'})
    before = material_pages(directory, source)
    assert not before[0]['immagini']
    monkeypatch.setattr('rt.core.materials._describe', Mock(side_effect=AssertionError('vision ripetuta')))
    source = source.model_copy(update={'estrai': 'immagini'})
    after = material_pages(directory, source)
    assert after[0]['immagini'] and after[0]['testo'] == before[0]['testo']
    assert archive.load_meta(source.impronta)['estrai'] == 'immagini'


def test_editor_image_gets_vision_once_then_reused_as_source(tmp_path, monkeypatch):
    from rt.pipeline.add_images import save_raw_image, compute_image_hash
    directory = lesson(tmp_path, 'editor')
    content = png_bytes()
    save_raw_image(directory, content, compute_image_hash(content))
    source = add_source(directory, 'materiale', 'photo.png', content)
    describe = Mock(return_value='Figura descritta')
    monkeypatch.setattr('rt.core.materials._describe', describe)
    assert 'Figura descritta' in material_pages(directory, source)[0]['testo']
    assert describe.call_count == 1
    assert archive.read_json(str(Path(archive.entry_dir(source.impronta)) / 'descrizione.json'))['ocr_text'] == 'Figura descritta'


def test_enrichment_vision_is_reused_in_another_lesson(tmp_path, monkeypatch):
    from rt.pipeline.add_images import save_raw_image, save_image_descriptions, compute_image_hash
    first, second = lesson(tmp_path, 'enrichment'), lesson(tmp_path, 'material')
    content = png_bytes()
    sha = compute_image_hash(content)
    relative = save_raw_image(first, content, sha)
    save_image_descriptions(first, {sha: {'filename': relative, 'ocr_text': 'Vision condivisa'}})
    source = add_source(second, 'materiale', 'photo.png', content)
    monkeypatch.setattr('rt.core.materials._describe', Mock(side_effect=AssertionError('vision ripetuta')))
    monkeypatch.setattr('rt.core.materials._extract', Mock(side_effect=AssertionError('estrazione ripetuta')))
    assert 'Vision condivisa' in material_pages(second, source)[0]['testo']


def test_backfill_optimizes_legacy_wav_and_preserves_known_engine(tmp_path, monkeypatch):
    from rt.services.archive_backfill import archive_backfill
    from rt.pipeline.source_update import _write_state
    directory = lesson(tmp_path, 'legacy-wav')
    monkeypatch.setattr('rt.pipeline.setup.transcode_audio_for_storage', lambda *_: False)
    source = add_source(directory, 'audio', 'old.wav', b'legacy wav')
    _write_state(directory, {'sources': {source.id: {'motore': 'macparakeet', 'segments': [], 'duration': 12}}})
    def convert(_path, target):
        Path(target).write_bytes(b'optimized m4a')
        return True
    monkeypatch.setattr('rt.pipeline.setup.transcode_audio_for_storage', convert)
    archive_backfill([directory])
    entry = archive.find(source.impronta)
    assert entry['estensione'] == '.m4a'
    assert archive.cached_transcript(source.impronta, 'macparakeet')['duration'] == 12
    assert not list(Path(archive.archive_dir()).rglob('originale.wav'))


def test_archive_keeps_only_m4a_for_compressed_audio(tmp_path, monkeypatch):
    directory = lesson(tmp_path, 'compressed')
    def convert(_path, target):
        Path(target).write_bytes(b'optimized compressed audio')
        return True
    monkeypatch.setattr('rt.pipeline.setup.transcode_audio_for_storage', convert)
    first = add_source(directory, 'audio', 'recording.mp3', b'original mp3')
    entry = archive.find(first.impronta)
    assert entry['estensione'] == '.m4a'
    assert Path(archive.original_path(first.impronta)).suffix == '.m4a'
    assert not list(Path(archive.archive_dir()).rglob('originale.mp3'))
    assert (Path(directory) / first.file).read_bytes() == b'original mp3'
