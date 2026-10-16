from pathlib import Path

import fitz
import pytest

from rt.core.image_extract import extract_images
from rt.core.material_page_filter import cleaned_page_texts, few_words
from rt.core.materials import material_pages
from rt.core.sources import add_source
from rt.pipeline.add_images import prepare_uploaded_images, place_uploaded_images
from rt.pipeline.material_mapping import place_page_in_outline
from tests.test_add_images_mapping import lesson  # noqa: F401
from tests.test_materials import png_bytes


def document_bytes():
    with fitz.open() as doc:
        for index, title in enumerate(['Patologia generale', 'Emostasi', 'Grazie', 'Schema', 'Foto']):
            page = doc.new_page(width=500, height=400)
            page.insert_text((25, 25), 'Corso universitario medicina patologia generale biologica cellulare')
            page.insert_text((25, 70), title)
            if index == 3:
                page.draw_rect(fitz.Rect(50, 100, 400, 350))
            if index == 4:
                page.insert_image(fitz.Rect(50, 100, 400, 350), stream=png_bytes())
        return doc.tobytes()


def test_repeated_lines_are_counted_per_page_and_only_in_long_documents():
    header = 'Corso universitario di medicina'
    texts = [header + '\n' + header + '\nTitolo', header, header, 'Altro']
    assert cleaned_page_texts(texts) == ['Titolo', '', '', 'Altro']
    assert cleaned_page_texts(texts[:3]) == texts[:3]
    assert few_words(header)


def test_import_filters_before_models_preserving_original_text(tmp_path, monkeypatch):
    (tmp_path / 'info.yaml').write_text('materia: Test\n')
    source = add_source(str(tmp_path), 'materiale', 'slide.pdf', document_bytes())
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda *a: calls.append(a) or 'Schema didattico mitocondriale')
    pages = material_pages(str(tmp_path), source)
    assert len(calls) == 2
    assert [p['has_figures'] for p in pages] == [False, False, False, True, True]
    assert [p['mapping_skip'] for p in pages] == [True, True, True, False, False]
    assert all('Corso universitario' in p['testo'] for p in pages)
    assert all('Corso universitario' not in p['mapping_text'] for p in pages)
    monkeypatch.setattr('rt.pipeline.material_mapping.classify_material_page', lambda *a, **k: pytest.fail('judge called'))
    for page in pages[:3]:
        assert place_page_in_outline(page, [], {}, source, str(tmp_path), {}, mock=True, mock_fallback=True) == ([], [])
    assert material_pages(str(tmp_path), source) == pages
    assert len(calls) == 2


def test_enrichment_skips_sparse_pages_without_vision_or_judge(lesson, tmp_path, monkeypatch):
    path = tmp_path / 'empty.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((25, 70), 'Mitocondri')
        doc.save(path)
    images = extract_images(str(path))
    assert images[0].mapping_skip and not images[0].has_figures
    monkeypatch.setattr('rt.pipeline.add_images.describe_new_images', lambda *a, **k: pytest.fail('Vision called'))
    monkeypatch.setattr('rt.pipeline.material_mapping.classify_material_page', lambda *a, **k: pytest.fail('judge called'))
    prepare_uploaded_images(lesson, images, force_mock=True)
    from rt.pipeline.outline import load_outline
    assert place_uploaded_images(lesson, load_outline(lesson), images, force_mock=True) == ({}, {})
    assert Path(lesson, 'assets/images/descriptions.json').exists()


def test_extraction_distinguishes_vector_and_embedded_figures(tmp_path):
    path = tmp_path / 'slides.pdf'
    path.write_bytes(document_bytes())
    images = extract_images(str(path))
    assert [p.has_figures for p in images] == [False, False, False, True, True]
    assert all(p.mapping_skip for p in images[:3])
    assert images[3].text == images[4].text == ''


def test_repeated_logo_and_background_are_not_figures():
    """Esportazioni di slide: sfondo e logo su ogni pagina non rendono 'figura' la copertina."""
    import io

    import fitz
    from PIL import Image

    from rt.core.material_page_filter import pdf_pages_have_figures

    def png(color, size):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="PNG")
        return buf.getvalue()

    logo, chart = png((10, 20, 200), (40, 40)), png((200, 30, 30), (300, 200))
    doc = fitz.open()
    for number in range(5):
        page = doc.new_page(width=800, height=600)
        page.draw_rect(page.rect, color=(0.9, 0.9, 0.9), fill=(0.95, 0.95, 0.95))  # sfondo
        page.insert_image(fitz.Rect(20, 20, 220, 220), stream=logo)  # logo grande ripetuto
        page.insert_text((300, 300), f"Titolo {number}")
        if number == 3:
            page.insert_image(fitz.Rect(250, 250, 750, 580), stream=chart)
    assert pdf_pages_have_figures(doc) == [False, False, False, True, False]
