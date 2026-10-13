import io

import fitz
from PIL import Image
import pytest

from rt.core.materials import material_pages, page_count
from rt.core.sources import add_source


@pytest.fixture(autouse=True)
def lesson_info(tmp_path):
    (tmp_path / "info.yaml").write_text("materia: Test\n")


def pdf_bytes(text='Testo della pagina'):
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((50, 50), text)
    data = document.tobytes()
    document.close()
    return data


def png_bytes():
    stream = io.BytesIO()
    Image.new('RGB', (30, 20), 'red').save(stream, format='PNG')
    return stream.getvalue()


def test_pdf_native_text_and_blank_page_vision_cached_once(tmp_path, monkeypatch):
    lesson = str(tmp_path)
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda *args: calls.append(args) or 'Vision text')
    original = pdf_bytes()
    source = add_source(lesson, 'materiale', 'pages.pdf', original)
    pages = material_pages(lesson, source)
    assert 'Testo della pagina' in pages[0]['testo'] and pages[0]['immagini']
    assert calls == []
    assert material_pages(lesson, source) == pages
    blank = add_source(lesson, 'materiale', 'blank.pdf', pdf_bytes(''))
    assert material_pages(lesson, blank)[0]['testo'] == 'Vision text'
    material_pages(lesson, blank)
    assert len(calls) == 1
    assert (tmp_path / source.file).read_bytes() == original
    (tmp_path / blank.file).write_bytes(original)
    with pytest.raises(ValueError, match='originale'):
        material_pages(lesson, blank)


def test_image_and_pptx_extract_text_and_embedded_images_without_quicklook(tmp_path, monkeypatch):
    from pptx import Presentation
    from pptx.util import Inches
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda *args: calls.append(args) or 'image context')
    monkeypatch.setattr('rt.core.materials._quicklook_slides', lambda *args: None)
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'Slide native text'
    slide.shapes.add_picture(io.BytesIO(png_bytes()), Inches(1), Inches(2))
    stream = io.BytesIO()
    presentation.save(stream)
    lesson = str(tmp_path)
    source = add_source(lesson, 'materiale', 'slides.pptx', stream.getvalue())
    pages = material_pages(lesson, source)
    assert pages[0]['testo'] == 'Slide native text' and len(pages[0]['immagini']) == 1
    assert page_count(str(tmp_path / source.file)) == 1
    image = add_source(lesson, 'materiale', 'photo.png', png_bytes())
    assert material_pages(lesson, image)[0]['testo'] == 'image context'
    material_pages(lesson, image)
    assert len(calls) == 1


def test_quicklook_attempt_and_missing_fallback(tmp_path, monkeypatch):
    from rt.core.materials import _quicklook_slides
    monkeypatch.setattr('rt.core.materials.sys.platform', 'darwin')
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda _: None)
    assert _quicklook_slides('unused.pptx', 1) is None
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda _: '/usr/bin/qlmanage')
    def render(command, **kwargs):
        assert command[:2] == ['/usr/bin/qlmanage', '-p']
        from pathlib import Path
        Path(command[3], 'Preview.pdf').write_bytes(pdf_bytes())
    monkeypatch.setattr('rt.core.materials.subprocess.run', render)
    assert len(_quicklook_slides('unused.pptx', 1)) == 1


def test_materials_upload_multiple_and_source_view(api_client, rt_db, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace, make_lesson
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    url = f'/api/v1/lessons/{lid}/sources'
    response = api_client.post(url, data={'tipo': 'materiale'}, files=[
        ('file', ('a.pdf', pdf_bytes(), 'application/pdf')),
        ('file', ('b.png', png_bytes(), 'image/png'))])
    assert response.status_code == 201, response.text
    assert len(response.json()) == 2
    view = api_client.get(url).json()
    materials = [s for s in view['sources'] if s['tipo'] == 'materiale']
    assert [(s['nome'], s['pagine'], s['usata']) for s in materials] == [('a.pdf', 1, False), ('b.png', 1, False)]


def test_single_material_response_and_invalid_order_are_compatible_and_atomic(api_client, rt_db, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace, make_lesson
    root = isolated_workspace(tmp_path, monkeypatch)
    make_lesson(root)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    url = f'/api/v1/lessons/{lid}/sources'
    response = api_client.post(url, data={'tipo': 'materiale'},
                              files={'file': ('doc.pdf', pdf_bytes(), 'application/pdf')})
    assert response.status_code == 201 and response.json()['tipo'] == 'materiale'
    before = api_client.get(url).json()['sources']
    response = api_client.post(url, data={'tipo': 'materiale', 'ordine': 99}, files=[
        ('file', ('a.pdf', pdf_bytes(), 'application/pdf')),
        ('file', ('b.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 422 and response.json()['error']['code'] == 'validation_error'
    assert api_client.get(url).json()['sources'] == before
