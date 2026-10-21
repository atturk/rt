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
    from rt.pipeline.add_images import compute_image_hash
    from rt.services.archive_backfill import archive_backfill
    directories = [lesson(tmp_path, str(i)) for i in range(2)]
    content = png_bytes()
    sha = compute_image_hash(content)
    for directory in directories:
        source = add_source(directory, 'materiale', 'old.pdf', pdf_bytes(directory))
        old = Path(directory) / 'materials' / source.impronta
        old.mkdir(parents=True)
        (old / 'pages.json').write_text(json.dumps({'impronta': source.impronta,
            'pages': [{'numero': 1, 'testo': 'testo', 'immagini': [], 'has_figures': False}]}))
        images = Path(directory) / 'assets/images'
        images.mkdir(parents=True)
        (images / 'photo.png').write_bytes(content)
        # Solo le immagini descritte con source standalone vengono registrate
        (images / 'descriptions.json').write_text(json.dumps({
            sha: {'filename': 'assets/images/photo.png', 'source': 'folder:photo.png'}
        }))
        # photo_no_desc.png senza descrizione: non deve essere registrata
        (images / 'photo_no_desc.png').write_bytes(png_bytes())
    monkeypatch.setattr('rt.core.materials._describe', Mock(side_effect=AssertionError('modello')))
    steps = []
    archive_backfill(directories, progress=lambda current, total, name: steps.append((current, total)))
    assert steps == [(0, 2), (1, 2)]
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
    save_image_descriptions(first, {sha: {'filename': relative, 'source': 'folder:photo.png', 'ocr_text': 'Vision condivisa'}})
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


def test_pdf_pages_do_not_become_archive_images(tmp_path, monkeypatch):
    """Aggiungere un PDF a una lezione (fixture con 3 pagine, percorso material: e pdf:)
    non crea voci 'immagine' nell'archivio; il PDF c'è come slide/documento."""
    import fitz
    from rt.pipeline.add_images import run_add_images

    doc = fitz.open()
    for i in range(1, 4):
        p = doc.new_page()
        p.insert_text((50, 50), f"Pagina {i}")
    pdf_data = doc.tobytes()
    doc.close()

    directory = lesson(tmp_path, "pdf_lesson")
    # Percorso material:
    source = add_source(directory, "materiale", "slides.pdf", pdf_data)
    monkeypatch.setattr("rt.core.materials._describe", Mock(return_value="Descrizione figura"))
    pages = material_pages(directory, source)
    assert len(pages) == 3

    # Percorso pdf: (estrazione e preparazione pagine caricate)
    pdf_file = Path(directory) / "sources/input.pdf"
    pdf_file.parent.mkdir(parents=True, exist_ok=True)
    pdf_file.write_bytes(pdf_data)
    from rt.core.image_extract import extract_images
    from rt.pipeline.add_images import prepare_uploaded_images
    uploaded = extract_images(str(pdf_file))
    prepare_uploaded_images(directory, uploaded, force_mock=True)

    # Verifica archivio: solo il PDF come slide, nessuna voce con tipo == 'immagine'
    arch_entries = []
    for d in Path(archive.archive_dir()).iterdir():
        if d.is_dir() and len(d.name) == 64:
            meta = archive.load_meta(d.name)
            if meta:
                arch_entries.append(meta)

    image_entries = [e for e in arch_entries if e.get("tipo") == "immagine"]
    assert len(image_entries) == 0, f"Trovate voci immagine in archivio: {image_entries}"
    slide_entries = [e for e in arch_entries if e.get("tipo") in ("slide", "documento")]
    assert len(slide_entries) >= 1
    assert any(e.get("impronta") == source.impronta for e in slide_entries)


def test_editor_and_folder_images_registered(tmp_path):
    """Un'immagine editor: e una folder: vengono registrate."""
    from rt.pipeline.add_images import compute_image_hash, save_image_descriptions, save_raw_image

    directory = lesson(tmp_path, "standalone_lesson")
    content1 = png_bytes()
    content2 = png_bytes() + b"extra"
    sha1 = compute_image_hash(content1)
    sha2 = compute_image_hash(content2)

    rel1 = save_raw_image(directory, content1, sha1)
    rel2 = save_raw_image(directory, content2, sha2)

    save_image_descriptions(directory, {
        sha1: {"filename": rel1, "source": "editor:screenshot.png", "alt_text": "Screenshot"},
        sha2: {"filename": rel2, "source": "folder:diagram.png", "alt_text": "Diagram"},
    })

    meta1 = archive.find(sha1)
    meta2 = archive.find(sha2)
    assert meta1 is not None and meta1.get("tipo") == "immagine"
    assert meta2 is not None and meta2.get("tipo") == "immagine"


def test_prune_page_images(tmp_path):
    """prune_page_images: con un archivio che ha una pagina estratta registrata per errore,
    una immagine folder: e un ritaglio dall'Archivio, elimina solo la prima;
    seconda esecuzione non fa niente (marcatore)."""
    from rt.pipeline.add_images import compute_image_hash, save_raw_image
    from rt.services.archive_backfill import prune_page_images

    directory = lesson(tmp_path, "prune_lesson")
    img_dir = Path(directory) / "assets/images"
    img_dir.mkdir(parents=True, exist_ok=True)

    c1 = png_bytes() + b"page1"
    c2 = png_bytes() + b"photo"
    c3 = png_bytes() + b"crop"
    sha1 = compute_image_hash(c1)
    sha2 = compute_image_hash(c2)
    sha3 = compute_image_hash(c3)

    p1 = save_raw_image(directory, c1, sha1)
    p2 = save_raw_image(directory, c2, sha2)
    p3 = save_raw_image(directory, c3, sha3)

    # In descriptions.json:
    # sha1 ha source 'pdf:doc.pdf#1' (NON standalone)
    # sha2 ha source 'folder:foto.png' (standalone)
    # sha3 non è standalone (o assente da descriptions della lezione)
    (img_dir / "descriptions.json").write_text(json.dumps({
        sha1: {"filename": p1, "source": "pdf:doc.pdf#1"},
        sha2: {"filename": p2, "source": "folder:foto.png"},
    }))

    # Registra tutti e tre in archivio come 'immagine'
    archive.register_file(str(Path(directory) / p1), nome="page1.png", tipo="immagine", sha=sha1)
    archive.register_file(str(Path(directory) / p2), nome="foto.png", tipo="immagine", sha=sha2)
    meta_crop = archive.register_file(str(Path(directory) / p3), nome="crop.png", tipo="immagine", sha=sha3)
    archive.save_meta(sha3, {"ritaglio_di": {"sha": "parent_sha", "pagina": 1}})

    # Prima esecuzione: sha1 deve essere eliminata, sha2 e sha3 conservate
    prune_page_images([directory])

    assert archive.find(sha1) is None
    assert archive.find(sha2) is not None
    assert archive.find(sha3) is not None

    # Verifica marcatore
    marker = archive.read_json(str(Path(archive.archive_dir()) / "indice.json"))
    assert marker.get("prune_page_images_done") is True

    # Registra di nuovo sha1 come finto errore per verificare che la seconda esecuzione non faccia nulla
    archive.register_file(str(Path(directory) / p1), nome="page1.png", tipo="immagine", sha=sha1)
    assert archive.find(sha1) is not None

    prune_page_images([directory])
    # Grazie al marcatore, la seconda esecuzione non ha fatto niente
    assert archive.find(sha1) is not None
