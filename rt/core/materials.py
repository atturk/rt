"""Testo e pagine immagine derivati una volta sola da una fonte immutabile."""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextvars import copy_context
from contextlib import contextmanager
import logging

from rt.core.captions import clean_caption, page_alt
from rt.core.idempotency import compute_file_sha256
from rt.core.lesson_lock import lesson_lock
from rt.storage import fs

logger = logging.getLogger(__name__)

MATERIAL_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.heic', '.pptx', '.docx', '.txt', '.md'}


def page_count(path):
    with fs.materialize(path) as real:
        suffix = os.path.splitext(real)[1].lower()
        if suffix == '.pdf':
            import pymupdf as fitz
            with fitz.open(real) as document:
                return len(document)
        if suffix == '.pptx':
            from pptx import Presentation
            return len(Presentation(real).slides)
        if suffix in ('.txt', '.md', '.docx'):
            return len(list(_document_pages(real)))
        from PIL import Image
        from pillow_heif import register_heif_opener
        register_heif_opener()
        with Image.open(real) as image:
            image.verify()
        return 1


def image_ext(data: bytes) -> str:
    """Ricava l'estensione dell'immagine dai magic bytes."""
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    if data.startswith(b'\xff\xd8'):
        return '.jpg'
    return '.png'


def image_mime(data: bytes) -> str:
    """MIME type dai magic bytes dell'immagine."""
    ext = image_ext(data)
    if ext == '.webp':
        return 'image/webp'
    if ext == '.jpg':
        return 'image/jpeg'
    return 'image/png'


def _page_image(data_or_pixmap) -> tuple[bytes, str]:
    """Normalizza foto, immagini di documenti o pixmap PDF in WebP (o PNG/JPEG di ripiego)."""
    from PIL import Image, ImageOps, features
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass

    if hasattr(data_or_pixmap, 'samples') and hasattr(data_or_pixmap, 'width') and hasattr(data_or_pixmap, 'height'):
        pixmap = data_or_pixmap
        if getattr(pixmap, 'n', 0) not in (3, 4):
            import pymupdf as fitz
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
        mode = 'RGBA' if getattr(pixmap, 'alpha', False) else 'RGB'
        image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
    else:
        with Image.open(io.BytesIO(data_or_pixmap)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()

    has_alpha = False
    if image.mode in ('RGBA', 'LA', 'PA') or (image.mode == 'P' and 'transparency' in image.info):
        rgba = image.convert('RGBA')
        min_a, _max_a = rgba.getchannel('A').getextrema()
        if min_a < 255:
            has_alpha = True
            image = rgba
        else:
            image = rgba.convert('RGB')
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    if max(image.size) > 2000:
        image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    if min(image.size) < 64:
        image.save(out, format='PNG', optimize=True)
        return out.getvalue(), '.png'

    if features.check('webp'):
        image.save(out, format='WEBP', quality=80, method=6)
        return out.getvalue(), '.webp'

    if has_alpha:
        bg = Image.new('RGB', image.size, 'white')
        bg.paste(image, mask=image.getchannel('A'))
        image = bg
    image.save(out, format='JPEG', quality=85, optimize=True)
    return out.getvalue(), '.jpg'


def _describe(data, lesson_dir, mock):
    from rt.llm.client import LLMClient
    from rt.llm.decision_images import normalize_image
    from rt.llm.prompts import ImageDescription, IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT
    from rt.services.prompt_settings import effective_system
    try:
        encoded, mime = normalize_image(data)
    except Exception:
        encoded, mime = data, 'image/png'
    result = LLMClient(force_mock=mock).call_structured(
        prompt='Trascrivi tutto il testo leggibile e descrivi i contenuti della pagina per studiarli.',
        system_prompt=effective_system('image_description', IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT),
        response_model=ImageDescription, job_name='image_description', lesson_dir=lesson_dir,
        image_data_url=f'data:{mime};base64,' + base64.b64encode(encoded).decode('ascii'))
    text = description_text(result.slide_title, result.ocr_text, result.visual_elements)
    return {
        'text': text,
        'slide_title': result.slide_title or '',
        'alt_text': result.alt_text or '',
    }


def description_text(title, ocr, visuals):
    """Testo della pagina per il classificatore: le figure come frasi, non come lista Python."""
    parts = [str(title or ''), str(ocr or '')]
    for item in visuals or []:
        item = item if isinstance(item, dict) else getattr(item, '__dict__', {'description': item})
        parts.append(str(item.get('description') or ''))
    return '\n'.join(part for part in parts if part.strip())


def _soffice():
    """LibreOffice, se installato: nel PATH o nella cartella standard di Windows/macOS."""
    found = shutil.which('soffice') or shutil.which('libreoffice')
    if found:
        return found
    if os.name == 'nt':
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
            candidate = os.path.join(base or '', 'LibreOffice', 'program', 'soffice.exe')
            if base and os.path.isfile(candidate):
                return candidate
    elif sys.platform == 'darwin':
        mac_app = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
        if os.path.isfile(mac_app):
            return mac_app
    return None


def _has_keynote():
    """Keynote su macOS, se presente l'applicazione e osascript."""
    if sys.platform != 'darwin' or not shutil.which('osascript'):
        return False
    for path in ('/Applications/Keynote.app', '/System/Applications/Keynote.app'):
        if os.path.isdir(path):
            return True
    return False


def _has_powerpoint():
    """PowerPoint su Windows, se presente nel registro, nel PATH o nei percorsi Office standard."""
    if sys.platform != 'win32':
        return False
    if not (shutil.which('powershell') or shutil.which('pwsh')):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'PowerPoint.Application'):
            return True
    except OSError:
        pass
    except ImportError:
        pass
    if shutil.which('powerpnt'):
        return True
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if not base:
            continue
        for office_root in ('Microsoft Office\\root', 'Microsoft Office'):
            for version in ('Office16', 'Office15', 'Office14'):
                candidate = os.path.join(base, office_root, version, 'POWERPNT.EXE')
                if os.path.isfile(candidate):
                    return True
    return False


def _component_soffice():
    """Eseguibile soffice del componente LibreOffice scaricato da RT, se pronto."""
    from rt.core.components import libreoffice_executable
    return libreoffice_executable()


def _effective_soffice():
    """LibreOffice disponibile: il componente scaricato ha la precedenza su quello di sistema."""
    return _component_soffice() or _soffice()


def _is_keynote_blocked() -> bool:
    from rt.core.components import is_keynote_blocked
    return is_keynote_blocked()


def _mark_keynote_blocked() -> None:
    from rt.core.components import mark_keynote_blocked
    mark_keynote_blocked()


def _clear_keynote_blocked() -> None:
    from rt.core.components import clear_keynote_blocked
    clear_keynote_blocked()


def available_slide_methods() -> list[str]:
    """Programmi affidabili installati per convertire presentazioni in immagini/PDF (esclude Quick Look)."""
    methods: list[str] = []
    if _has_powerpoint():
        methods.append('PowerPoint')
    if _has_keynote() and not _is_keynote_blocked():
        methods.append('Keynote')
    if _effective_soffice():
        methods.append('LibreOffice')
    return methods


def has_quicklook() -> bool:
    """True su macOS se qlmanage è disponibile (ripiego a qualità ridotta per le .pptx)."""
    return sys.platform == 'darwin' and bool(shutil.which('qlmanage'))


def _libreoffice_component_command(soffice_bin: str, target: str, real: str) -> list[str]:
    from pathlib import Path
    from rt.core.components import libreoffice_profile_dir

    profile_uri = Path(os.path.abspath(libreoffice_profile_dir())).as_uri()
    return [
        soffice_bin,
        f'-env:UserInstallation={profile_uri}',
        '--headless',
        '--norestore',
        '--convert-to',
        'pdf',
        '--outdir',
        target,
        real,
    ]


def _slide_render_methods(real, target):
    """Genera i metodi di resa disponibili in ordine di priorità:
    1. PowerPoint (su Windows se installato)
    2. Keynote (su macOS se installato e non bloccato)
    3. LibreOffice (componente scaricato da RT oppure installazione di sistema)
    4. Quick Look (su macOS se disponibile qlmanage)
    """
    methods = []
    if _has_powerpoint():
        ps = shutil.which('powershell') or shutil.which('pwsh') or 'powershell'
        # Percorsi letti da variabili d'ambiente: nessuna interpolazione di stringhe nello script PowerShell.
        script = (
            '$app = New-Object -ComObject PowerPoint.Application; '
            '$pres = $null; '
            'try { '
            '$pres = $app.Presentations.Open($env:RT_PPTX_INPUT, -1, 0, 0); '
            '$pres.SaveAs($env:RT_PDF_OUTPUT, 32) '
            '} finally { '
            'if ($pres -ne $null) { try { $pres.Close() } catch {} }; '
            'if ($app -ne $null) { try { $app.Quit() } catch {} } '
            '}'
        )
        methods.append(('PowerPoint', [ps, '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script]))
    if _has_keynote() and not _is_keynote_blocked():
        pdf_out = os.path.join(target, 'keynote_export.pdf')
        # Percorsi passati come argomenti: niente problemi con virgolette nei nomi
        script = (
            'on run argv\n'
            '  tell application "Keynote"\n'
            '    set doc to open POSIX file (item 1 of argv)\n'
            '    try\n'
            '      export doc to POSIX file (item 2 of argv) as PDF\n'
            '    end try\n'
            '    close doc saving no\n'
            '  end tell\n'
            'end run'
        )
        methods.append(('Keynote', ['osascript', '-e', script, real, pdf_out]))
    comp_soffice = _component_soffice()
    if comp_soffice:
        methods.append(('LibreOffice', _libreoffice_component_command(comp_soffice, target, real)))
    else:
        sys_soffice = _soffice()
        if sys_soffice:
            methods.append(('LibreOffice', [sys_soffice, '--headless', '--convert-to', 'pdf', '--outdir', target, real]))
    if sys.platform == 'darwin' and shutil.which('qlmanage'):
        methods.append(('Quick Look', [shutil.which('qlmanage'), '-p', '-o', target, real]))
    return methods


def _is_component_libreoffice_command(command: list[str]) -> bool:
    return any(isinstance(arg, str) and arg.startswith('-env:UserInstallation=') for arg in command)


def _error_output_text(exc: subprocess.CalledProcessError) -> str:
    parts = []
    for stream in (exc.stderr, exc.stdout):
        if isinstance(stream, bytes):
            parts.append(stream.decode('utf-8', errors='replace'))
        elif isinstance(stream, str):
            parts.append(stream)
    return '\n'.join(parts)


@contextmanager
def _quicklook_slides(real, count):
    """La resa delle slide (PowerPoint / Keynote -> LibreOffice -> Quick Look) è facoltativa; si usa solo se copre
    esattamente tutte le slide (count). Altrimenti registra nel log del worker e cede il passo al ripiego."""
    with tempfile.TemporaryDirectory(prefix='rt-slides-') as target:
        methods = _slide_render_methods(real, target)
        tried_methods = []
        render = None
        document = None

        from pathlib import Path
        import pymupdf as fitz

        for name, command in methods:
            tried_methods.append(name)
            try:
                timeout = 45 if name == 'Keynote' else 120
                run_kwargs = {'capture_output': True, 'check': True, 'timeout': timeout}
                if name == 'PowerPoint':
                    run_kwargs['env'] = {
                        **os.environ,
                        'RT_PPTX_INPUT': os.path.abspath(real),
                        'RT_PDF_OUTPUT': os.path.join(target, 'powerpoint_export.pdf'),
                    }
                elif name == 'LibreOffice' and _is_component_libreoffice_command(command):
                    from rt.core.components import prepare_libreoffice_runtime
                    extra_env = prepare_libreoffice_runtime()
                    if extra_env:
                        run_kwargs['env'] = {**os.environ, **extra_env}
                if sys.platform == 'win32':
                    run_kwargs['creationflags'] = 0x08000000
                subprocess.run(command, **run_kwargs)
                for path in Path(target).rglob('*.pdf'):
                    candidate = fitz.open(path)
                    if len(candidate) == count:
                        document = candidate
                        render = lambda i, doc=document: doc[i].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
                        break
                    candidate.close()
                if render is not None:
                    if name == 'Keynote':
                        _clear_keynote_blocked()
                    break
                images = sorted(Path(target).rglob('*.png'))
                if len(images) == count:
                    render = lambda i, imgs=images: imgs[i].read_bytes()
                    if name == 'Keynote':
                        _clear_keynote_blocked()
                    break
                # Pulisce i file del metodo fallito prima del successivo
                for p in Path(target).iterdir():
                    if p.is_file():
                        p.unlink()
                    elif p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
            except subprocess.TimeoutExpired:
                if name == 'Keynote':
                    logger.warning("Keynote ha superato il timeout (%ss) per '%s': passo al convertitore successivo", timeout, os.path.basename(real))
                    _mark_keynote_blocked()
                continue
            except subprocess.CalledProcessError as exc:
                if name == 'Keynote' and '-1743' in _error_output_text(exc):
                    logger.warning("Keynote non autorizzato (-1743) per '%s': passo al convertitore successivo", os.path.basename(real))
                    _mark_keynote_blocked()
                continue
            except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
                continue

        if render is None:
            methods_str = ', '.join(tried_methods) if tried_methods else 'nessun metodo disponibile'
            logger.warning("Resa delle slide per '%s' non riuscita (metodi tentati: %s)", os.path.basename(real), methods_str)

        try:
            yield render
        finally:
            if document is not None:
                document.close()


def _slide_title(slide):
    title_shape = getattr(slide.shapes, 'title', None)
    if title_shape is not None and getattr(title_shape, 'text', None):
        return clean_caption(title_shape.text)
    return None


def _pdf_page_title(page):
    """Riga col carattere più grande nel 40% alto della pagina (3-120 caratteri, non solo numeri)."""
    height = getattr(page.rect, 'height', 0) or 0
    if height <= 0:
        return None
    y_limit = 0.4 * height
    page_dict = page.get_text('dict') or {}
    candidates = []
    top_sizes = []
    for block in page_dict.get('blocks', []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            bbox = line.get('bbox') or (0, 0, 0, 0)
            if bbox[1] > y_limit:
                continue
            spans = [s for s in line.get('spans', []) if str(s.get('text') or '').strip()]
            if not spans:
                continue
            line_text = ' '.join(''.join(str(s.get('text') or '') for s in line.get('spans', [])).split())
            if not (3 <= len(line_text) <= 120) or not any(ch.isalpha() for ch in line_text):
                continue
            line_size = max(float(s.get('size') or 0) for s in spans)
            top_sizes.append(line_size)
            cleaned = clean_caption(line_text)
            if cleaned:
                candidates.append((line_size, -bbox[1], cleaned))
    if not candidates:
        return None
    best_size, _neg_y, best_title = max(candidates)
    uniform_top = (max(top_sizes) - min(top_sizes)) < 0.5
    if (len(top_sizes) >= 3 and uniform_top) or (len(top_sizes) >= 2 and uniform_top and best_size <= 13):
        return None
    return best_title


def _slide_content(slide):
    texts, images = [], []
    def visit(shapes):
        for shape in shapes:
            if getattr(shape, 'has_text_frame', False):
                texts.append(shape.text)
            if getattr(shape, 'has_table', False):
                texts.extend(' | '.join(cell.text for cell in row.cells) for row in shape.table.rows)
            if hasattr(shape, 'image'):
                images.append(shape.image.blob)
            if hasattr(shape, 'shapes'):
                visit(shape.shapes)
    visit(slide.shapes)
    return '\n'.join(texts).strip(), images


def _filter_slide_images(slide, slide_width=None, slide_height=None):
    """Ripiego per le slide PPTX: scarta immagini con lato minore < 64 px,
    oppure area < 2% della slide, o che non si decodificano.
    Al massimo una per slide, la più grande."""
    from PIL import Image
    candidates = []
    slide_area = (slide_width or 0) * (slide_height or 0)

    def visit(shapes):
        for shape in shapes:
            if hasattr(shape, 'image'):
                try:
                    blob = shape.image.blob
                    with Image.open(io.BytesIO(blob)) as img:
                        w_px, h_px = img.size
                        # 1. Scarta se lato minore < 64 px
                        if min(w_px, h_px) < 64:
                            continue
                        # 2. Scarta se area < 2% della slide
                        shape_w = getattr(shape, 'width', None) or 0
                        shape_h = getattr(shape, 'height', None) or 0
                        shape_area = shape_w * shape_h
                        if slide_area > 0 and shape_area < 0.02 * slide_area:
                            continue
                        area = shape_area if shape_area > 0 else (w_px * h_px)
                        candidates.append((area, blob))
                except Exception:
                    continue
            if hasattr(shape, 'shapes'):
                visit(shape.shapes)

    visit(slide.shapes)
    if not candidates:
        return []

    # Al massimo una per slide, la più grande
    candidates.sort(key=lambda c: c[0], reverse=True)
    best_blob = candidates[0][1]
    try:
        return [_page_image(best_blob)[0]]
    except Exception:
        return []


def _document_pages(real, images=False):
    """Circa 400 parole, paragrafi indivisibili; ogni titolo apre una pagina."""
    import re
    blocks = []
    if real.lower().endswith(('.txt', '.md')):
        with open(real, 'rb') as stream:
            data = stream.read()
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('cp1252')
        for p in re.split(r'\n\s*\n', text):
            stripped = p.strip()
            if not stripped:
                continue
            first_line = stripped.splitlines()[0].strip()
            heading = bool(re.match(r'^#{1,6}\s+\S', first_line))
            blocks.append((stripped, heading, []))
    else:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        document = Document(real)
        for element in document.element.body:
            if element.tag.endswith('}p'):
                paragraph = Paragraph(element, document)
                pictures = []
                if images:
                    for blip in element.xpath('.//a:blip'):
                        rid = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                        if rid and rid in document.part.related_parts:
                            pictures.append(_page_image(document.part.related_parts[rid].blob)[0])
                blocks.append((paragraph.text, paragraph.style.name.startswith('Heading'), pictures))
            elif element.tag.endswith('}tbl'):
                table = Table(element, document)
                pictures = []
                if images:
                    for blip in element.xpath('.//a:blip'):
                        rid = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                        if rid and rid in document.part.related_parts:
                            pictures.append(_page_image(document.part.related_parts[rid].blob)[0])
                blocks.append(('\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows), False, pictures))
    texts, pictures, words, page_title = [], [], 0, None
    for text, heading, imgs in blocks:
        count = len(text.split())
        if texts and (heading or words + count > 400):
            yield '\n\n'.join(texts), pictures, bool(pictures), page_title
            texts, pictures, words, page_title = [], [], 0, None
        if not texts and heading and text.strip():
            heading_line = text.strip().splitlines()[0].strip()
            page_title = clean_caption(re.sub(r'^#{1,6}\s+', '', heading_line))
        if text.strip():
            texts.append(text)
        pictures.extend(imgs)
        words += count
    if texts or pictures:
        yield '\n\n'.join(texts), pictures, bool(pictures), page_title


def _extract(real):
    suffix = os.path.splitext(real)[1].lower()
    if suffix in ('.docx', '.txt', '.md'):
        yield from _document_pages(real, images=True)
    elif suffix == '.pdf':
        import pymupdf as fitz
        from rt.core.material_page_filter import pdf_pages_have_figures
        with fitz.open(real) as document:
            figures = pdf_pages_have_figures(document)
            for page, has_figures in zip(document, figures):
                yield page.get_text().strip(), [_page_image(page.get_pixmap(matrix=fitz.Matrix(2, 2)))[0]], has_figures, _pdf_page_title(page)
    elif suffix == '.pptx':
        from pptx import Presentation
        presentation = Presentation(real)
        sw = getattr(presentation, 'slide_width', None)
        sh = getattr(presentation, 'slide_height', None)
        with _quicklook_slides(real, len(presentation.slides)) as render:
            for i, slide in enumerate(presentation.slides):
                text, _ = _slide_content(slide)
                if render:
                    pictures = [_page_image(render(i))[0]]
                else:
                    pictures = _filter_slide_images(slide, sw, sh)
                yield text, pictures, bool(pictures), _slide_title(slide)
    else:
        with open(real, 'rb') as stream:
            yield '', [_page_image(stream.read())[0]], True, None


def _extract_text(real):
    suffix = os.path.splitext(real)[1].lower()
    if suffix in ('.docx', '.txt', '.md'):
        yield from _document_pages(real)
    elif suffix == '.pdf':
        import pymupdf as fitz
        with fitz.open(real) as document:
            for page in document:
                yield page.get_text().strip(), [], False, _pdf_page_title(page)
    elif suffix == '.pptx':
        from pptx import Presentation
        for slide in Presentation(real).slides:
            yield _slide_content(slide)[0], [], False, _slide_title(slide)
    else:
        yield '', [], False, None


def _extract_images(real, previous):
    """Upgrade di una cache testuale: conserva il testo, rende le sole immagini mancanti."""
    if real.lower().endswith('.pdf'):
        import pymupdf as fitz
        from rt.core.material_page_filter import pdf_pages_have_figures
        with fitz.open(real) as document:
            figures = pdf_pages_have_figures(document)
            for i, page in enumerate(document):
                old = previous[i] if i < len(previous) else {}
                yield old.get('testo', ''), [_page_image(page.get_pixmap(matrix=fitz.Matrix(2, 2)))[0]], figures[i], old.get('titolo') or _pdf_page_title(page)
    else:
        yield from _extract(real)


def cached_pages(lesson_dir, source):
    if not source.impronta:
        return None
    from rt.core.archive import import_material_cache, entry_dir, read_json, pages_for_use
    import_material_cache(lesson_dir, source)
    data = read_json(os.path.join(entry_dir(source.impronta), 'pages.json'))
    if not data:
        return None
    pages = pages_for_use(source.impronta, getattr(source, 'pagine', None))
    return for_mode(pages, getattr(source, 'estrai', None))


def for_mode(pages, mode):
    """L'archivio tiene tutto; la lezione vede solo testo, testo e immagini, o solo immagini."""
    if mode == 'testo':
        return [dict(p, immagini=[]) for p in pages]
    if mode == 'solo_immagini':
        return [dict(p, testo='', mapping_text='', mapping_skip=False) for p in pages]
    return pages


def _elapsed(seconds):
    seconds = max(0, round(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return ' '.join(value for value in (f'{hours}h' if hours else '', f'{minutes}m' if minutes else '',
                                       f'{seconds}s' if seconds or not (hours or minutes) else '') if value)


def material_pages(lesson_dir, source, **kwargs):
    from rt.core.archive import archive_lock
    with archive_lock(source.impronta + '-extract'):
        return _material_pages(lesson_dir, source, **kwargs)


def _material_pages(lesson_dir, source, *, mock=False, ctx=None, refresh=False, checked=False, timing=None):
    """Estrae su disco, poi descrive poche pagine alla volta; ogni risultato è riprendibile."""
    from rt.core.config import load_config
    from rt.core.material_page_filter import cleaned_page_texts, few_words
    from rt.services.context import RunCancelled
    started = time.monotonic()
    cfg = load_config()
    from rt.core.archive import register_file, file_type, entry_dir, pages_for_use, save_meta
    register_file(os.path.join(lesson_dir, source.file), nome=os.path.basename(source.file),
                  tipo=file_type(source.file), sha=source.impronta)
    name = os.path.basename(source.file)
    path = os.path.join(lesson_dir, source.file)
    if not checked and compute_file_sha256(path) != source.impronta:
        raise ValueError('Una fonte originale è cambiata: aggiungila come nuova fonte')
    stats = timing if timing is not None else {}
    stats.update(vision_calls=0, vision_seconds=0.0, pages=0, cached_pages=0)

    def progress(current, total):
        if ctx:
            ctx.progress('prepare', current=current, total=total,
                         message=f'Lettura di {name}: pagina {current} di {total}')

    def finish(pages):
        stats['pages'] = len(pages)
        stats['seconds'] = time.monotonic() - started
        calls = stats['vision_calls']
        mean = stats['vision_seconds'] / calls if calls else 0
        if ctx:
            detail = (f"già letta in precedenza, {stats['cached_pages']} pagin{'a' if stats['cached_pages'] == 1 else 'e'} "
                      f"riusat{'a' if stats['cached_pages'] == 1 else 'e'} senza Vision"
                      if not calls and stats['cached_pages'] else f"Vision {calls} chiamate, media {mean:.1f} s")
            ctx.progress('prepare', message=f"Lettura di {name}: finita in {_elapsed(stats['seconds'])} ({detail})")
        return for_mode(pages, mode)

    from rt.core.source_options import default_extraction
    mode = getattr(source, 'estrai', None) or default_extraction(source.file, path)
    # Testo e immagini e solo immagini estraggono le stesse pagine: cambia cosa vede la lezione.
    extract = 'testo' if mode == 'testo' else 'immagini'
    from rt.core.archive import load_meta
    cached = None if refresh else cached_pages(lesson_dir, source)
    previous_mode = (load_meta(source.impronta) or {}).get('estrai', 'testo')
    upgrading = extract == 'immagini' and previous_mode == 'testo'
    # Vision descrive solo le pagine scelte; solo immagini non descrive nulla.
    wanted_pages = getattr(source, 'pagine', None)
    if cached is not None and not upgrading and all('has_figures' in page and (
            mode == 'solo_immagini' or not page.get('vision_pending')) for page in cached):
        stats['cached_pages'] = len(cached)
        progress(len(cached), len(cached))
        return finish(cached)
    folder = entry_dir(source.impronta)
    with lesson_lock(lesson_dir):
        fs.makedirs(folder, exist_ok=True)
    is_pptx_images = source.file.lower().endswith('.pptx') and extract != 'testo'
    fallback_notified = False

    def maybe_start_libreoffice_fallback():
        nonlocal fallback_notified
        if not is_pptx_images or fallback_notified or available_slide_methods():
            return
        from rt.core.components import ensure_libreoffice_fallback_download
        status = ensure_libreoffice_fallback_download()
        fallback_notified = True
        if ctx and status.get('available') and status.get('state') == 'downloading':
            ctx.progress(
                'prepare',
                message=(
                    'Slide importate senza resa grafica: sto scaricando il convertitore '
                    'delle presentazioni (circa 300 MB). Le prossime presentazioni avranno le slide complete.'
                ),
            )

    maybe_start_libreoffice_fallback()
    extracted = []
    # I PNG si liberano a ogni iterazione, senza accumulare l'intero PDF in RAM.
    with fs.materialize(path) as real:
        from rt.core.archive import read_json
        previous = read_json(os.path.join(folder, 'pages.json'), {}).get('pages', [])
        extraction = (_extract_images(real, previous) if upgrading and previous else _extract(real)) if extract != 'testo' else _extract_text(real)
        crops = (load_meta(source.impronta) or {}).get('ritagli', {})
        for number, item in enumerate(extraction, 1):
            text, images, has_figures = item[:3]
            page_title = item[3] if len(item) > 3 else None
            if ctx:
                ctx.check_cancelled()
            filenames = []
            with lesson_lock(lesson_dir):
                for index, data in enumerate(images, 1):
                    ext = image_ext(data)
                    relative = f'page-{number}-{index}{ext}'
                    existing_crop = next(
                        (f'page-{number}-{index}{cand}' for cand in ('.webp', '.png', '.jpg')
                         if fs.isfile(os.path.join(folder, f'page-{number}-{index}{cand}'))),
                        None,
                    ) if str(number) in crops else None
                    if existing_crop:
                        relative = existing_crop
                    else:
                        with fs.open(os.path.join(folder, relative) + '.tmp', 'wb') as stream:
                            stream.write(data)
                        fs.replace(os.path.join(folder, relative) + '.tmp', os.path.join(folder, relative))
                    filenames.append(relative)
            extracted.append((text, filenames, has_figures, page_title))
    maybe_start_libreoffice_fallback()
    if not extracted:
        raise ValueError('Il materiale non ha pagine')
    cleaned = cleaned_page_texts([text for text, _, _, _ in extracted])
    pages = [None] * len(extracted)
    pending = []
    completed = 0

    def save(entry):
        entry_path = os.path.join(folder, f"page-{entry['numero']}.json")
        with lesson_lock(lesson_dir):
            with fs.open(entry_path + '.tmp', 'w', encoding='utf-8') as stream:
                json.dump(entry, stream, ensure_ascii=False)
            fs.replace(entry_path + '.tmp', entry_path)
        return entry

    for number, (text, filenames, has_figures, page_title) in enumerate(extracted, 1):
        entry_path = os.path.join(folder, f'page-{number}.json')
        if not refresh and fs.isfile(entry_path):
            with fs.open(entry_path, encoding='utf-8') as stream:
                saved = json.load(stream)
            if 'has_figures' in saved and not saved.get('vision_pending'):
                if upgrading:
                    saved['immagini'] = filenames
                    saved['has_figures'] = has_figures
                    if page_title and not saved.get('titolo'):
                        saved['titolo'] = page_title
                    saved['mapping_skip'] = few_words(saved.get('mapping_text', saved.get('testo', ''))) and not has_figures
                    if few_words(saved.get('mapping_text', saved.get('testo', ''))) and has_figures and filenames:
                        if mode == 'solo_immagini' or (wanted_pages is not None and number not in wanted_pages):
                            pages[number - 1] = dict(saved, vision_pending=True)
                            completed += 1
                            continue
                        pending.append(saved)
                        continue
                    save(saved)
                pages[number - 1] = saved
                stats['cached_pages'] += 1
                completed += 1
                progress(completed, len(pages))
                continue
        mapping_text = cleaned[number - 1]
        sparse = few_words(mapping_text)
        entry = {'numero': number, 'testo': text, 'immagini': filenames,
                 'mapping_text': mapping_text, 'has_figures': has_figures,
                 'mapping_skip': sparse and not has_figures}
        if page_title:
            entry['titolo'] = page_title
        if sparse and has_figures and filenames and (mode == 'solo_immagini' or (
                wanted_pages is not None and number not in wanted_pages)):
            # Descritta solo quando una lezione la sceglie: niente page-N.json, resta da fare.
            pages[number - 1] = dict(entry, vision_pending=True)
            completed += 1
            progress(completed, len(pages))
        elif sparse and has_figures and filenames:
            pending.append(entry)
        else:
            pages[number - 1] = save(entry)
            completed += 1
            progress(completed, len(pages))
    model = cfg.jobs['image_description'].primary.model if 'image_description' in cfg.jobs else 'predefinito'
    if ctx:
        ctx.progress('prepare', message=f'Lettura di {name}: {len(pages)} pagine, {len(pending)} da descrivere '
                     f'col modello visivo (modello: {model})')
    stopped = threading.Event()
    failures = []

    def describe(entry):
        texts, slide_titles, alt_texts, seconds = [], [], [], 0.0
        try:
            from rt.core.archive import read_json, write_json, archive_lock
            reusable = read_json(os.path.join(folder, 'descrizione.json')) if file_type(source.file) == 'immagine' else None
            if reusable and not refresh:
                described = description_text(reusable.get('slide_title'), reusable.get('ocr_text'), reusable.get('visual_elements'))
                first_line = next((line for line in described.splitlines() if line.strip()), '')
                titolo = (
                    clean_caption(reusable.get('titolo'))
                    or clean_caption(reusable.get('slide_title'))
                    or clean_caption(reusable.get('alt_text'))
                    or clean_caption(first_line)
                )
                stats['cached_pages'] += 1
                updated = dict(entry, testo=described, mapping_text=described)
                if titolo:
                    updated['titolo'] = titolo
                return save(updated), 0, 0.0
            for relative in entry['immagini']:
                if stopped.is_set():
                    raise RunCancelled('Lettura dei materiali interrotta')
                if ctx:
                    ctx.check_cancelled()
                with fs.open(os.path.join(folder, relative), 'rb') as stream:
                    data = stream.read()
                before = time.monotonic()
                res = _describe(data, lesson_dir, mock)
                seconds += time.monotonic() - before
                if isinstance(res, dict):
                    texts.append(str(res.get('text') or ''))
                    if res.get('slide_title'):
                        slide_titles.append(res['slide_title'])
                    if res.get('alt_text'):
                        alt_texts.append(res['alt_text'])
                else:
                    texts.append(str(res))
            described = '\n'.join(texts)
            first_slide_title = slide_titles[0] if slide_titles else ''
            first_alt_text = alt_texts[0] if alt_texts else ''
            if file_type(source.file) == 'immagine':
                # ocr_text contiene già il titolo: lo salvo a parte come 'titolo', non come slide_title,
                # così il riuso (che unisce slide_title e ocr_text) non lo duplica nel testo.
                payload = {'ocr_text': described}
                saved_title = clean_caption(first_slide_title) or clean_caption(first_alt_text)
                if saved_title:
                    payload['titolo'] = saved_title
                with archive_lock(source.impronta):
                    write_json(os.path.join(folder, 'descrizione.json'), payload)
            titolo = clean_caption(first_slide_title) or clean_caption(first_alt_text) or entry.get('titolo')
            entry = dict(entry, testo='\n'.join(filter(None, [entry['testo'], described])), mapping_text=described)
            if titolo:
                entry['titolo'] = titolo
            return save(entry), len(texts), seconds
        except BaseException as error:
            if not isinstance(error, RunCancelled):
                failures.append(error)
            stopped.set()
            raise

    # Non accodare l'intero documento: dopo un errore/annullamento non partono altre pagine.
    with ThreadPoolExecutor(max_workers=cfg.pipeline.parallel_pages, thread_name_prefix='rt-pages') as pool:
        iterator = iter(pending)
        active = set()
        def submit_next():
            if ctx:
                ctx.check_cancelled()
            entry = next(iterator, None)
            if entry is not None and not stopped.is_set():
                active.add(pool.submit(copy_context().run, describe, entry))
        try:
            for _ in range(min(cfg.pipeline.parallel_pages, len(pending))):
                submit_next()
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    entry, calls, seconds = future.result()
                    pages[entry['numero'] - 1] = entry
                    stats['vision_calls'] += calls
                    stats['vision_seconds'] += seconds
                    completed += 1
                    progress(completed, len(pages))
                if ctx:
                    ctx.check_cancelled()
                for _ in done:
                    submit_next()
        except BaseException:
            stopped.set()
            # Un worker fermato dall'errore di un altro non deve mascherare l'errore originale.
            if failures:
                raise failures[0]
            raise
    if ctx:
        ctx.check_cancelled()
    cache_path = os.path.join(folder, 'pages.json')
    with lesson_lock(lesson_dir):
        with fs.open(cache_path + '.tmp', 'w', encoding='utf-8') as stream:
            json.dump({'impronta': source.impronta, 'pages': pages}, stream, ensure_ascii=False)
        fs.replace(cache_path + '.tmp', cache_path)
    save_meta(source.impronta, {'pagine_totali': len(pages), 'estrai': extract if upgrading or previous_mode != 'immagini' else previous_mode})
    from rt.core.archive import refresh_search
    refresh_search(source.impronta)
    return finish(pages_for_use(source.impronta, getattr(source, 'pagine', None)))


def material_context_parts(lesson_dir, *, mock=False, ctx=None, include_materials: bool = True):
    """Contesto per la riscrittura: solo le fonti che non sono già nei segmenti, una volta sola."""
    from rt.core.sources import load_sources
    from rt.core.source_selection import selection
    from rt.pipeline.source_update import _read_state, segment_source_ids
    sources = load_sources(lesson_dir)
    parts = []
    primary = selection(lesson_dir)['principale']
    state = _read_state(lesson_dir)
    cache = state.get('sources', {})
    in_segments = segment_source_ids(sources, state, primary)
    for source in sources:
        if source.id in in_segments:
            continue
        if source.tipo == 'materiale':
            if include_materials:
                for page in material_pages(lesson_dir, source, mock=mock, ctx=ctx):
                    parts.append(f"[{source.id}, {os.path.basename(source.file)}, pagina {page['numero']}]\n{page['testo']}")
        else:
            texts = [segment['text_raw'] for segment in cache.get(source.id, {}).get('segments', [])]
            if texts:
                parts.append(f'[{source.id}, {os.path.basename(source.file)}]\n' + '\n'.join(texts))
    return parts
