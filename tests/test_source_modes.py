"""Fonti 4.3.4: tre modalità di estrazione, default dal file, Vision solo sulle pagine scelte,
PDF del pannello nell'archivio e guida solo senza registrazione."""
import fitz
import pytest

from rt.core import archive
from rt.core.materials import material_pages
from rt.core.source_options import default_extraction
from rt.core.sources import add_source


@pytest.fixture(autouse=True)
def lesson_info(tmp_path):
    (tmp_path / "info.yaml").write_text("materia: Test\n")


def figures_pdf(path, pages=3, landscape=True):
    """Pagine con una figura e poche parole: le descrive Vision."""
    width, height = (842, 595) if landscape else (595, 842)
    with fitz.open() as document:
        for i in range(pages):
            page = document.new_page(width=width, height=height)
            page.insert_text((50, 50), f"Figura {i + 1}")
            page.draw_rect(fitz.Rect(80, 80, 400, 400), fill=(0.2, 0.4, 0.8))
        document.save(path)
    return path


def text_pdf(path):
    with fitz.open() as document:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 550, 800), "Capitolo del libro. " * 80)
        document.save(path)
    return path


def test_default_extraction_follows_the_file(tmp_path):
    assert default_extraction('slide.pdf', figures_pdf(str(tmp_path / 'slide.pdf'))) == 'immagini'
    assert default_extraction('libro.pdf', text_pdf(str(tmp_path / 'libro.pdf'))) == 'testo'
    assert default_extraction('foto.png') == 'immagini' and default_extraction('slide.pptx') == 'immagini'
    for name in ('sbobina.docx', 'note.txt', 'appunti.md'):
        assert default_extraction(name) == 'testo'


def test_markdown_is_a_text_material(tmp_path):
    source = add_source(str(tmp_path), 'materiale', 'appunti.md', "# Titolo\n\nTesto in **Markdown**.".encode(),
                        estrai='solo_immagini')
    assert source.estrai == 'testo'
    assert 'Testo in' in material_pages(str(tmp_path), source, mock=True)[0]['testo']


def test_vision_only_on_chosen_pages_and_solo_immagini_never(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda data, *a: calls.append(1) or 'Descritta')
    path = figures_pdf(str(tmp_path / 'deck.pdf'))
    data = open(path, 'rb').read()
    only = add_source(str(tmp_path), 'materiale', 'deck.pdf', data, estrai='solo_immagini')
    pages = material_pages(str(tmp_path), only, mock=True)
    assert calls == [] and all(p['immagini'] and p['testo'] == '' for p in pages)
    first = add_source(str(tmp_path), 'materiale', 'deck.pdf', data, pagine=[1], estrai='immagini')
    pages = material_pages(str(tmp_path), first, mock=True)
    assert len(calls) == 1 and pages[0]['testo'].endswith('Descritta')
    rest = add_source(str(tmp_path), 'materiale', 'deck.pdf', data, pagine=[2, 3], estrai='immagini')
    material_pages(str(tmp_path), rest, mock=True)
    assert len(calls) == 3
    again = add_source(str(tmp_path), 'materiale', 'deck.pdf', data, estrai='immagini')
    material_pages(str(tmp_path), again, mock=True)
    assert len(calls) == 3


def test_panel_pdf_goes_to_the_archive_and_the_source_reuses_it(tmp_path, monkeypatch):
    from rt.core.image_extract import extract_images, update_archived_descriptions
    from rt.core.idempotency import compute_file_sha256
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda data, *a: calls.append(1) or 'Vision')
    path = figures_pdf(str(tmp_path / 'deck.pdf'), pages=2)
    sha = compute_file_sha256(path)
    images = extract_images(path)
    assert archive.find(sha)['nome'] == 'deck.pdf'
    stored = archive.read_json(archive.entry_dir(sha) + '/pages.json')['pages']
    assert [p.get('vision_pending') for p in stored] == [True, True]
    from rt.pipeline.add_images import compute_image_hash
    update_archived_descriptions(images, {compute_image_hash(i.image_bytes): {'ocr_text': f'Pagina {i.page_number}'}
                                          for i in images})
    source = add_source(str(tmp_path), 'materiale', 'deck.pdf', open(path, 'rb').read(), estrai='immagini')
    pages = material_pages(str(tmp_path), source, mock=True)
    assert calls == [] and [p['mapping_text'] for p in pages] == ['Pagina 1', 'Pagina 2']
    reused = extract_images(path)
    assert [i.text for i in reused] == ['Pagina 1', 'Pagina 2']


def test_archive_search_reads_descriptions_and_page_text(tmp_path):
    from PIL import Image
    image = tmp_path / 'grafico.png'
    Image.new('RGB', (40, 40), 'blue').save(image)
    meta = archive.register_image(str(image), {'ocr_text': 'Curva pressione-volume', 'visual_elements': 'grafico'})
    from rt.services.archive_service import list_entries
    assert [e['impronta'] for e in list_entries(q='PRESSIONE')] == [meta['impronta']]
    assert list_entries(q='inesistente') == []
