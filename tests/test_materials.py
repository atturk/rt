from contextlib import nullcontext
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
    assert material_pages(lesson, blank)[0]['testo'] == ''
    assert material_pages(lesson, blank)[0]['mapping_skip'] is True
    material_pages(lesson, blank)
    assert len(calls) == 0
    assert (tmp_path / source.file).read_bytes() == original
    (tmp_path / blank.file).write_bytes(original)
    with pytest.raises(ValueError, match='originale'):
        material_pages(lesson, blank)


def test_image_and_pptx_extract_text_and_embedded_images_without_quicklook(tmp_path, monkeypatch):
    from pptx import Presentation
    from pptx.util import Inches
    calls = []
    monkeypatch.setattr('rt.core.materials._describe', lambda *args: calls.append(args) or 'image context')
    monkeypatch.setattr('rt.core.materials._quicklook_slides', lambda *args: nullcontext())
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'Slide native text'
    slide.shapes.add_picture(io.BytesIO(png_bytes()), Inches(1), Inches(2))
    stream = io.BytesIO()
    presentation.save(stream)
    lesson = str(tmp_path)
    source = add_source(lesson, 'materiale', 'slides.pptx', stream.getvalue())
    pages = material_pages(lesson, source)
    assert 'Slide native text' in pages[0]['testo'] and 'image context' in pages[0]['testo']
    assert len(pages[0]['immagini']) == 1 and pages[0]['has_figures']
    assert page_count(str(tmp_path / source.file)) == 1
    image = add_source(lesson, 'materiale', 'photo.png', png_bytes())
    assert material_pages(lesson, image)[0]['testo'] == 'image context'
    material_pages(lesson, image)
    assert len(calls) == 2


def test_quicklook_attempt_and_missing_fallback(tmp_path, monkeypatch):
    from rt.core.materials import _quicklook_slides
    monkeypatch.setattr('rt.core.materials.sys.platform', 'darwin')
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda _: None)
    with _quicklook_slides('unused.pptx', 1) as render:
        assert render is None
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda _: '/usr/bin/qlmanage')
    def render(command, **kwargs):
        assert command[:2] == ['/usr/bin/qlmanage', '-p']
        from pathlib import Path
        Path(command[3], 'Preview.pdf').write_bytes(pdf_bytes())
    monkeypatch.setattr('rt.core.materials.subprocess.run', render)
    with _quicklook_slides('unused.pptx', 1) as render:
        assert render(0).startswith(b'\x89PNG')


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
    assert [(s['nome'], s['pagine_totali'], s['usata']) for s in materials] == [('a.pdf', 1, False), ('b.png', 1, False)]


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


def _parallel_source(tmp_path, monkeypatch, count=6):
    import rt.core.materials as materials
    from rt.core.config import load_config
    source = add_source(str(tmp_path), 'materiale', 'parallel.pdf', pdf_bytes())
    monkeypatch.setattr(materials, '_extract', lambda _: (('', [png_bytes()], True) for _ in range(count)))
    cfg = load_config()
    cfg.pipeline.parallel_pages = 3
    monkeypatch.setattr('rt.core.config.load_config', lambda: cfg)
    return source


def test_material_pages_parallel_order_cache_and_context(tmp_path, monkeypatch):
    import time
    from contextvars import ContextVar
    from rt.services.context import RunContext
    from rt.services.events import ListReporter
    marker = ContextVar('test_material_context', default='missing')
    marker.set('copied')
    source = _parallel_source(tmp_path, monkeypatch)
    calls = []
    import threading
    running, peak, guard = [0], [0], threading.Lock()

    def describe(*args):
        assert marker.get() == 'copied'
        calls.append(1)
        with guard:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(.2)
        with guard:
            running[0] -= 1
        return 'Testo visivo'

    monkeypatch.setattr('rt.core.materials._describe', describe)
    reporter = ListReporter()
    ctx = RunContext(reporter=reporter)
    pages = material_pages(str(tmp_path), source, ctx=ctx)
    assert peak[0] >= 2  # pagine lette in parallelo (il tempo reale varia troppo sui runner)
    assert [p['numero'] for p in pages] == list(range(1, 7))
    from pathlib import Path
    from rt.core.archive import entry_dir
    folder = Path(entry_dir(source.impronta))
    assert all((folder / f'page-{n}.json').exists() for n in range(1, 7))
    (folder / 'pages.json').unlink()
    for n in range(4, 7):
        (folder / f'page-{n}.json').unlink()
    calls.clear()
    assert material_pages(str(tmp_path), source, ctx=ctx) == pages
    assert len(calls) == 3
    messages = [getattr(e, 'message', '') for e in reporter.events]
    assert any('pagina 6 di 6' in m for m in messages)
    assert any('Vision 3 chiamate' in m for m in messages)


def test_material_pages_cancel_keeps_finished_pages(tmp_path, monkeypatch):
    import threading
    import time
    from rt.services.context import RunContext, RunCancelled
    source = _parallel_source(tmp_path, monkeypatch)
    ctx = RunContext()
    barrier = threading.Barrier(3)
    calls = []

    def describe(*args):
        calls.append(1)
        barrier.wait(timeout=3)
        ctx.cancel_token.cancel()
        time.sleep(.02)
        return 'finita'

    monkeypatch.setattr('rt.core.materials._describe', describe)
    with pytest.raises(RunCancelled):
        material_pages(str(tmp_path), source, ctx=ctx)
    assert len(calls) == 3
    from pathlib import Path
    from rt.core.archive import entry_dir
    folder = Path(entry_dir(source.impronta))
    assert len(list(folder.glob('page-*.json'))) == 3
    assert not (folder / 'pages.json').exists()


def test_material_pages_error_saves_other_running_pages(tmp_path, monkeypatch):
    import threading
    from rt.services.context import RunContext
    source = _parallel_source(tmp_path, monkeypatch)
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    calls = []

    def describe(*args):
        with lock:
            calls.append(1)
            number = len(calls)
        barrier.wait(timeout=3)
        if number == 1:
            raise ValueError('Vision fallita')
        return 'finita'

    monkeypatch.setattr('rt.core.materials._describe', describe)
    with pytest.raises(ValueError, match='Vision fallita'):
        material_pages(str(tmp_path), source, ctx=RunContext())
    assert len(calls) == 3
    from pathlib import Path
    from rt.core.archive import entry_dir
    folder = Path(entry_dir(source.impronta))
    assert len(list(folder.glob('page-*.json'))) == 2


def test_material_pages_reports_original_failure_even_if_another_worker_is_cancelled(tmp_path, monkeypatch):
    import threading
    import time
    from concurrent.futures import wait
    from rt.services.context import RunCancelled
    source = _parallel_source(tmp_path, monkeypatch, count=2)
    barrier = threading.Barrier(2)
    counter = []
    lock = threading.Lock()

    def describe(*args):
        with lock:
            counter.append(1)
            number = len(counter)
        barrier.wait(timeout=3)
        if number == 1:
            time.sleep(.02)
            raise ValueError('errore originale')
        raise RunCancelled('worker fermato')

    def cancelled_first(futures, **kwargs):
        done, pending = wait(futures)
        return sorted(done, key=lambda future: not isinstance(future.exception(), RunCancelled)), pending

    monkeypatch.setattr('rt.core.materials._describe', describe)
    monkeypatch.setattr('rt.core.materials.wait', cancelled_first)
    with pytest.raises(ValueError, match='errore originale'):
        material_pages(str(tmp_path), source)
