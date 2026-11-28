from contextlib import nullcontext
import io

import pymupdf as fitz
from PIL import Image
import pytest

from rt.core.materials import material_pages, page_count
from rt.core.sources import add_source


@pytest.fixture(autouse=True)
def lesson_info(tmp_path):
    (tmp_path / "info.yaml").write_text("materia: Test\n")


def pdf_bytes(text='Testo della pagina'):
    # Pagina orizzontale: come le slide, il default è testo e immagini.
    document = fitz.open()
    page = document.new_page(width=842, height=595)
    if text:
        page.insert_text((50, 50), text)
    data = document.tobytes()
    document.close()
    return data


def png_bytes(width=100, height=100):
    stream = io.BytesIO()
    Image.new('RGB', (width, height), 'red').save(stream, format='PNG')
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
    slide.shapes.add_picture(io.BytesIO(png_bytes(100, 100)), Inches(1), Inches(2), width=Inches(3), height=Inches(3))
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
    monkeypatch.setattr('rt.core.materials._component_soffice', lambda: None)
    monkeypatch.setattr('rt.core.materials._soffice', lambda: None)
    monkeypatch.setattr('rt.core.materials._has_keynote', lambda: False)
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


def test_slide_render_methods_order(tmp_path, monkeypatch):
    from rt.core.materials import _slide_render_methods
    monkeypatch.setenv('RT_DATA_DIR', str(tmp_path))
    monkeypatch.setattr('rt.core.materials.sys.platform', 'darwin')
    monkeypatch.setattr('rt.core.materials._component_soffice', lambda: None)
    monkeypatch.setattr('rt.core.materials._soffice', lambda: '/usr/local/bin/soffice')
    monkeypatch.setattr('rt.core.materials._has_keynote', lambda: True)
    monkeypatch.setattr('rt.core.materials._is_keynote_blocked', lambda: False)
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda cmd: f'/bin/{cmd}')

    # Mac: Keynote -> LibreOffice -> Quick Look
    methods = _slide_render_methods('slides.pptx', '/tmp/target')
    assert [name for name, _ in methods] == ['Keynote', 'LibreOffice', 'Quick Look']

    # Componente LibreOffice ha la precedenza sul LibreOffice di sistema e usa il profilo dedicato
    comp_bin = '/fake/components/libreoffice/LibreOffice.app/Contents/MacOS/soffice'
    monkeypatch.setattr('rt.core.materials._component_soffice', lambda: comp_bin)
    methods = _slide_render_methods('slides.pptx', '/tmp/target')
    assert [name for name, _ in methods] == ['Keynote', 'LibreOffice', 'Quick Look']
    lo_cmd = dict(methods)['LibreOffice']
    assert lo_cmd[0] == comp_bin
    assert lo_cmd[1].startswith('-env:UserInstallation=file://')
    assert 'libreoffice-profile' in lo_cmd[1]
    assert '--headless' in lo_cmd and '--norestore' in lo_cmd

    # Senza Keynote (o bloccato): LibreOffice -> Quick Look
    monkeypatch.setattr('rt.core.materials._has_keynote', lambda: False)
    methods = _slide_render_methods('slides.pptx', '/tmp/target')
    assert [name for name, _ in methods] == ['LibreOffice', 'Quick Look']

    # Senza LibreOffice: Quick Look
    monkeypatch.setattr('rt.core.materials._component_soffice', lambda: None)
    monkeypatch.setattr('rt.core.materials._soffice', lambda: None)
    methods = _slide_render_methods('slides.pptx', '/tmp/target')
    assert [name for name, _ in methods] == ['Quick Look']


def test_slide_render_methods_windows_powerpoint_before_libreoffice_without_path_interpolation(monkeypatch):
    from rt.core.materials import _slide_render_methods, _quicklook_slides
    from pathlib import Path
    monkeypatch.setattr('rt.core.materials.sys.platform', 'win32')
    monkeypatch.setattr('rt.core.materials._component_soffice', lambda: None)
    monkeypatch.setattr('rt.core.materials._soffice', lambda: 'C:\\LibreOffice\\soffice.exe')
    monkeypatch.setattr('rt.core.materials._has_powerpoint', lambda: True)
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda cmd: 'C:\\Windows\\powershell.exe' if cmd == 'powershell' else None)

    pptx_path = "C:\\Users\\Mario's\\Desktop\\lezione $test.pptx"
    target_dir = "C:\\Temp\\rt-slides-xyz"
    methods = _slide_render_methods(pptx_path, target_dir)
    assert [name for name, _ in methods] == ['PowerPoint', 'LibreOffice']

    ps_command = dict(methods)['PowerPoint']
    script = ps_command[-1]
    assert 'PowerPoint.Application' in script
    assert '$env:RT_PPTX_INPUT' in script and '$env:RT_PDF_OUTPUT' in script
    assert pptx_path not in script and target_dir not in script
    assert all(pptx_path not in token and target_dir not in token for token in ps_command)

    # Verifica che _quicklook_slides passi i percorsi via env e legga il PDF prodotto
    monkeypatch.setattr('rt.core.materials._soffice', lambda: None)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['env'] = kwargs.get('env', {})
        captured['creationflags'] = kwargs.get('creationflags')
        Path(captured['env']['RT_PDF_OUTPUT']).write_bytes(pdf_bytes())

    monkeypatch.setattr('rt.core.materials.subprocess.run', fake_run)
    with _quicklook_slides(pptx_path, 1) as render:
        assert render is not None
        assert render(0).startswith(b'\x89PNG')
    assert captured['env']['RT_PPTX_INPUT'].endswith("lezione $test.pptx")
    assert captured['env']['RT_PDF_OUTPUT'].endswith("powerpoint_export.pdf")
    assert captured['creationflags'] == 0x08000000


def test_slide_render_page_count_verification_and_worker_log(monkeypatch, caplog):
    import logging
    from rt.core.materials import _quicklook_slides
    from pathlib import Path

    monkeypatch.setattr('rt.core.materials.sys.platform', 'darwin')
    monkeypatch.setattr('rt.core.materials._component_soffice', lambda: None)
    monkeypatch.setattr('rt.core.materials._soffice', lambda: '/bin/soffice')
    monkeypatch.setattr('rt.core.materials._has_keynote', lambda: True)
    monkeypatch.setattr('rt.core.materials._is_keynote_blocked', lambda: False)
    monkeypatch.setattr('rt.core.materials.shutil.which', lambda cmd: f'/bin/{cmd}')

    called_methods = []
    def fake_subprocess_run(cmd, **kwargs):
        prog = cmd[0]
        if prog == 'osascript':
            called_methods.append('Keynote')
            assert kwargs.get('timeout') == 45
            # 1 pagina solo (fallisce il conteggio di 28)
            Path(cmd[4]).write_bytes(pdf_bytes())
        elif 'soffice' in prog:
            called_methods.append('LibreOffice')
            outdir = cmd[cmd.index('--outdir') + 1]
            # 28 pagine (soddisfa il conteggio di 28)
            doc = fitz.open()
            for _ in range(28):
                doc.new_page(width=842, height=595)
            Path(outdir, 'soffice.pdf').write_bytes(doc.tobytes())
            doc.close()
        elif 'qlmanage' in prog:
            called_methods.append('Quick Look')

    monkeypatch.setattr('rt.core.materials.subprocess.run', fake_subprocess_run)

    with _quicklook_slides('sample.pptx', 28) as render:
        assert render is not None
        assert called_methods == ['Keynote', 'LibreOffice']
        assert 'Quick Look' not in called_methods

    # Se tutti i metodi falliscono: riga chiara nel log del worker
    def all_fail(cmd, **kwargs):
        pass
    monkeypatch.setattr('rt.core.materials.subprocess.run', all_fail)

    with caplog.at_level(logging.WARNING):
        with _quicklook_slides('sample.pptx', 28) as render:
            assert render is None
        assert "Resa delle slide per 'sample.pptx' non riuscita" in caplog.text
        assert "Keynote, LibreOffice, Quick Look" in caplog.text


def test_keynote_timeout_or_1743_blocks_keynote_and_falls_back_to_libreoffice(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path
    from rt.core import components, materials

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    monkeypatch.setattr(materials.sys, 'platform', 'darwin')
    monkeypatch.setattr(materials, '_has_keynote', lambda: True)
    monkeypatch.setattr(materials, '_soffice', lambda: '/bin/soffice')
    monkeypatch.setattr(materials, '_component_soffice', lambda: None)
    monkeypatch.setattr(materials.shutil, 'which', lambda _cmd: None)

    calls = []

    def fail_1743_then_soffice(cmd, **kwargs):
        calls.append((cmd[0], kwargs.get('timeout')))
        if cmd[0] == 'osascript':
            raise subprocess.CalledProcessError(1, cmd, stderr=b'execution error: Not authorized to send Apple events to Keynote. (-1743)')
        outdir = cmd[cmd.index('--outdir') + 1]
        Path(outdir, 'out.pdf').write_bytes(pdf_bytes())

    monkeypatch.setattr(materials.subprocess, 'run', fail_1743_then_soffice)
    with materials._quicklook_slides('slides.pptx', 1) as render:
        assert render is not None
    assert calls == [('osascript', 45), ('/bin/soffice', 120)]
    assert components.is_keynote_blocked()
    assert 'Keynote' not in materials.available_slide_methods()

    # Seconda conversione: Keynote viene saltato subito
    calls.clear()
    with materials._quicklook_slides('slides.pptx', 1) as render:
        assert render is not None
    assert calls == [('/bin/soffice', 120)]

    # Anche timeout su Keynote lo blocca per 7 giorni
    components.clear_keynote_blocked()
    assert not components.is_keynote_blocked()

    def timeout_then_soffice(cmd, **kwargs):
        calls.append((cmd[0], kwargs.get('timeout')))
        if cmd[0] == 'osascript':
            raise subprocess.TimeoutExpired(cmd, kwargs.get('timeout'))
        outdir = cmd[cmd.index('--outdir') + 1]
        Path(outdir, 'out.pdf').write_bytes(pdf_bytes())

    calls.clear()
    monkeypatch.setattr(materials.subprocess, 'run', timeout_then_soffice)
    with materials._quicklook_slides('slides.pptx', 1) as render:
        assert render is not None
    assert components.is_keynote_blocked()
    until = components.keynote_blocked_until()
    assert until is not None and until > 0


def test_component_libreoffice_fontconfig_and_registry_profile(tmp_path, monkeypatch):
    from pathlib import Path
    from rt.core import components, materials

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    monkeypatch.setattr(materials.sys, 'platform', 'darwin')
    monkeypatch.setattr(components.sys, 'platform', 'darwin')
    monkeypatch.setattr(materials, '_has_keynote', lambda: False)
    monkeypatch.setattr(materials, '_soffice', lambda: None)
    monkeypatch.setattr(materials.shutil, 'which', lambda _cmd: None)

    lo_app = tmp_path / "components" / "libreoffice" / "LibreOffice.app" / "Contents"
    soffice_bin = lo_app / "MacOS" / "soffice"
    app_fonts = lo_app / "Resources" / "fontconfig" / "fonts.conf"
    soffice_bin.parent.mkdir(parents=True)
    soffice_bin.write_bytes(b"fake")
    app_fonts.parent.mkdir(parents=True)
    app_fonts.write_text("<fontconfig/>", encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['env'] = kwargs.get('env', {})
        outdir = cmd[cmd.index('--outdir') + 1]
        Path(outdir, 'out.pdf').write_bytes(pdf_bytes())

    monkeypatch.setattr(materials.subprocess, 'run', fake_run)
    with materials._quicklook_slides('slides.pptx', 1) as render:
        assert render is not None

    fonts_conf_path = tmp_path / "components" / "libreoffice-fonts.conf"
    assert captured['env'].get('FONTCONFIG_FILE') == str(fonts_conf_path)
    conf_text = fonts_conf_path.read_text(encoding='utf-8')
    assert '/System/Library/Fonts' in conf_text
    assert '/System/Library/Fonts/Supplemental' in conf_text
    assert '/Library/Fonts' in conf_text
    assert str(fake_home / 'Library' / 'Fonts') in conf_text
    assert f'<include ignore_missing="yes">{app_fonts}</include>' in conf_text
    assert str(tmp_path / 'components' / 'libreoffice-fontcache') in conf_text

    # sostituzioni come alias <accept> (il font vero, se installato, vince)
    assert '<family>Cambria Math</family><accept><family>STIX Two Math</family></accept>' in conf_text
    assert 'Carlito' in conf_text and 'Caladea' in conf_text

    # Su Windows non crea libreoffice-fonts.conf né imposta FONTCONFIG_FILE
    monkeypatch.setattr(components.sys, 'platform', 'win32')
    assert components.prepare_libreoffice_runtime() == {}


def test_first_pptx_without_converters_starts_libreoffice_download_once(tmp_path, monkeypatch):
    from pptx import Presentation
    from pptx.util import Inches
    from rt.core import components, materials
    from rt.services.context import RunContext
    from rt.services.events import ListReporter

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    monkeypatch.setattr(materials, 'available_slide_methods', lambda: [])
    monkeypatch.setattr(materials, '_quicklook_slides', lambda *args: nullcontext())
    monkeypatch.setattr(materials, '_describe', lambda *args: 'Testo visivo')

    started = []

    def fake_start_download(cid):
        started.append(cid)
        components._write_component_state(cid, {'state': 'downloading', 'auto_resume': True})
        return {
            'id': cid,
            'available': True,
            'state': 'downloading',
        }

    # Flusso del Mac anche sui runner Windows (dove PowerPoint o LibreOffice di sistema cambierebbero l'esito).
    monkeypatch.setattr(components.sys, 'platform', 'darwin')
    monkeypatch.setattr(components, 'detect_system_slide_app', lambda: None)
    monkeypatch.setattr(components, 'libreoffice_available', lambda: True)
    monkeypatch.setattr(components, '_libreoffice_platform_spec', lambda: ('http://127.0.0.1/lo.dmg', 100, '0' * 64, '.dmg'))
    monkeypatch.setattr(components, 'start_download', fake_start_download)
    # Seconda chiamata: simula download già attivo
    monkeypatch.setattr(components, 'is_download_active', lambda cid: cid == components.LIBREOFFICE_ID and len(started) > 0)

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'Slide senza convertitore'
    buf = io.BytesIO()
    prs.save(buf)

    lesson = str(tmp_path / "lesson")
    (tmp_path / "lesson").mkdir()
    (tmp_path / "lesson" / "info.yaml").write_text("materia: Test\n")
    s1 = add_source(lesson, 'materiale', 'uno.pptx', buf.getvalue())
    s2 = add_source(lesson, 'materiale', 'due.pptx', buf.getvalue())

    reporter = ListReporter()
    ctx = RunContext(reporter=reporter)
    pages1 = material_pages(lesson, s1, ctx=ctx)
    pages2 = material_pages(lesson, s2, ctx=ctx)

    assert len(pages1) == 1 and 'Slide senza convertitore' in pages1[0]['testo']
    assert len(pages2) == 1
    assert started == [components.LIBREOFFICE_ID]
    messages = [getattr(e, 'message', '') for e in reporter.events]
    assert any(
        'Slide importate senza resa grafica: sto scaricando il convertitore delle presentazioni. '
        'Le prossime presentazioni avranno le slide complete.' in m
        for m in messages
    )


def test_filter_slide_images_small_and_corrupt():
    from pptx import Presentation
    from pptx.util import Inches
    from rt.core.materials import _filter_slide_images

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # 1. Piccola lato minore < 64 px (15x18)
    stream_small = io.BytesIO()
    Image.new('RGB', (15, 18), 'blue').save(stream_small, format='PNG')
    slide.shapes.add_picture(stream_small, Inches(0), Inches(0), Inches(1), Inches(1))

    # 2. Piccola area < 2% slide (0.5x0.5 in = 0.25 in^2 su 75 in^2 = 0.3% < 2%)
    stream_tiny_area = io.BytesIO()
    Image.new('RGB', (100, 100), 'yellow').save(stream_tiny_area, format='PNG')
    slide.shapes.add_picture(stream_tiny_area, Inches(1), Inches(1), Inches(0.5), Inches(0.5))

    # 3. Utile media: 200x200 px, 2x2 inches (4 in^2 = 5.3% > 2%)
    stream_mid = io.BytesIO()
    Image.new('RGB', (200, 200), 'green').save(stream_mid, format='PNG')
    slide.shapes.add_picture(stream_mid, Inches(3), Inches(3), Inches(2), Inches(2))

    # 4. Utile grande (la più grande): 300x300 px, 3x3 inches (9 in^2 = 12% > 2%)
    stream_large = io.BytesIO()
    Image.new('RGB', (300, 300), 'white').save(stream_large, format='PNG')
    slide.shapes.add_picture(stream_large, Inches(4), Inches(4), Inches(3), Inches(3))

    # 5. Immagine corrotta/non decodificabile
    fake_corrupted = type('FakeCorrupted', (), {
        'image': type('Image', (), {'blob': b'corrupted bytes not an image'})(),
        'width': Inches(4),
        'height': Inches(4),
    })()
    real_shapes = list(slide.shapes)
    real_shapes.append(fake_corrupted)
    slide.shapes.__iter__ = lambda self: iter(real_shapes)

    res = _filter_slide_images(slide, prs.slide_width, prs.slide_height)
    assert len(res) == 1
    with Image.open(io.BytesIO(res[0])) as im:
        assert im.size == (300, 300)

    # Slide senza immagini utili -> ritorna lista vuota (niente "?")
    prs_empty = Presentation()
    slide_empty = prs_empty.slides.add_slide(prs_empty.slide_layouts[6])
    slide_empty.shapes.add_picture(io.BytesIO(stream_small.getvalue()), Inches(0), Inches(0), Inches(1), Inches(1))
    assert _filter_slide_images(slide_empty, prs_empty.slide_width, prs_empty.slide_height) == []


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


def test_webp_compression_photo_pdf_transparency_small_and_jpeg_fallback(tmp_path, monkeypatch):
    import random
    from types import SimpleNamespace
    from rt.core.materials import _page_image, _describe, image_ext

    # 1. Foto 4000x3000 -> WebP con lato max 2000 e < 600 KB
    rng = random.Random(42)
    photo = Image.new('RGB', (4000, 3000), (240, 240, 240))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(photo)
    for _ in range(300):
        x0, y0 = rng.randint(0, 3800), rng.randint(0, 2800)
        draw.rectangle((x0, y0, x0 + 180, y0 + 120), fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    raw_photo = io.BytesIO()
    photo.save(raw_photo, format='JPEG', quality=95)
    webp_photo, ext = _page_image(raw_photo.getvalue())
    assert ext == '.webp'
    assert image_ext(webp_photo) == '.webp'
    assert len(webp_photo) < 600 * 1024
    with Image.open(io.BytesIO(webp_photo)) as im:
        assert max(im.size) == 2000
        assert im.size == (2000, 1500)

    # 2. Pagina PDF -> WebP almeno 3x più piccola del PNG
    pdf_img = Image.new('RGB', (1600, 900))
    px = pdf_img.load()
    for y in range(900):
        for x in range(1600):
            px[x, y] = ((x * 255 // 1600 + (y % 7)) % 256, (y * 255 // 900 + (x % 5)) % 256, ((x + y) * 128 // 2500) % 256)
    pdf_img_buf = io.BytesIO()
    pdf_img.save(pdf_img_buf, format='PNG')
    doc = fitz.open()
    page = doc.new_page(width=800, height=450)
    page.insert_image(page.rect, stream=pdf_img_buf.getvalue())
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    old_png = pix.tobytes('png')
    webp_pdf, pdf_ext = _page_image(pix)
    doc.close()
    assert pdf_ext == '.webp'
    assert len(old_png) >= 3 * len(webp_pdf)

    # 3. Trasparenza preservata in WebP; piccola (< 64 px) resta PNG
    alpha_img = Image.new('RGBA', (120, 120), (255, 0, 0, 128))
    alpha_buf = io.BytesIO()
    alpha_img.save(alpha_buf, format='PNG')
    alpha_webp, alpha_ext = _page_image(alpha_buf.getvalue())
    assert alpha_ext == '.webp'
    with Image.open(io.BytesIO(alpha_webp)) as im:
        assert 'A' in im.getbands()

    small_bytes, small_ext = _page_image(png_bytes(32, 32))
    assert small_ext == '.png'
    assert image_ext(small_bytes) == '.png'

    # 4. Fallback JPEG se WebP non disponibile
    monkeypatch.setattr('PIL.features.check', lambda feat: False if feat == 'webp' else True)
    jpg_bytes, jpg_ext = _page_image(png_bytes(120, 120))
    assert jpg_ext == '.jpg'
    assert image_ext(jpg_bytes) == '.jpg'

    # 5. _describe riceve data URL JPEG o PNG, mai WebP
    captured_urls = []

    class FakeClient:
        def __init__(self, force_mock=False):
            pass

        def call_structured(self, **kwargs):
            captured_urls.append(kwargs.get('image_data_url', ''))
            return SimpleNamespace(slide_title='Titolo', ocr_text='Testo', visual_elements=[], alt_text='Alt')

    monkeypatch.setattr('rt.llm.client.LLMClient', FakeClient)
    _describe(webp_photo, str(tmp_path), mock=False)
    assert len(captured_urls) == 1
    assert captured_urls[0].startswith(('data:image/jpeg;base64,', 'data:image/png;base64,'))
    assert not captured_urls[0].startswith('data:image/webp;')
