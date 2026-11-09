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


def _png_image(data):
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    with Image.open(io.BytesIO(data)) as image:
        out = io.BytesIO()
        ImageOps.exif_transpose(image).convert('RGB').save(out, format='PNG')
        return out.getvalue()


def _describe(data, lesson_dir, mock):
    from rt.llm.client import LLMClient
    from rt.llm.prompts import ImageDescription, IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT
    from rt.services.prompt_settings import effective_system
    result = LLMClient(force_mock=mock).call_structured(
        prompt='Trascrivi tutto il testo leggibile e descrivi i contenuti della pagina per studiarli.',
        system_prompt=effective_system('image_description', IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT),
        response_model=ImageDescription, job_name='image_description', lesson_dir=lesson_dir,
        image_data_url='data:image/png;base64,' + base64.b64encode(data).decode('ascii'))
    return '\n'.join(str(value) for value in (result.slide_title, result.ocr_text, result.visual_elements) if value)


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


def _slide_render_methods(real, target):
    """Genera i metodi di resa disponibili in ordine di priorità:
    1. LibreOffice (se installato)
    2. Keynote (su macOS se installato)
    3. Quick Look (su macOS se disponibile qlmanage)
    """
    methods = []
    soffice = _soffice()
    if soffice:
        methods.append(('LibreOffice', [soffice, '--headless', '--convert-to', 'pdf', '--outdir', target, real]))
    if _has_keynote():
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
    if sys.platform == 'darwin' and shutil.which('qlmanage'):
        methods.append(('Quick Look', [shutil.which('qlmanage'), '-p', '-o', target, real]))
    return methods


@contextmanager
def _quicklook_slides(real, count):
    """La resa delle slide (LibreOffice -> Keynote -> Quick Look) è facoltativa; si usa solo se copre
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
                subprocess.run(command, capture_output=True, check=True, timeout=120)
                for path in Path(target).rglob('*.pdf'):
                    candidate = fitz.open(path)
                    if len(candidate) == count:
                        document = candidate
                        render = lambda i, doc=document: doc[i].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
                        break
                    candidate.close()
                if render is not None:
                    break
                images = sorted(Path(target).rglob('*.png'))
                if len(images) == count:
                    render = lambda i, imgs=images: imgs[i].read_bytes()
                    break
                # Pulisce i file del metodo fallito prima del successivo
                for p in Path(target).iterdir():
                    if p.is_file():
                        p.unlink()
                    elif p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
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
        return [_png_image(best_blob)]
    except Exception:
        return []


def _document_pages(real, images=False):
    """Circa 400 parole, paragrafi indivisibili; ogni titolo apre una pagina."""
    blocks = []
    if real.lower().endswith(('.txt', '.md')):
        with open(real, 'rb') as stream:
            data = stream.read()
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('cp1252')
        import re
        blocks = [(p.strip(), False, []) for p in re.split(r'\n\s*\n', text) if p.strip()]
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
                            pictures.append(_png_image(document.part.related_parts[rid].blob))
                blocks.append((paragraph.text, paragraph.style.name.startswith('Heading'), pictures))
            elif element.tag.endswith('}tbl'):
                table = Table(element, document)
                pictures = []
                if images:
                    for blip in element.xpath('.//a:blip'):
                        rid = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                        if rid and rid in document.part.related_parts:
                            pictures.append(_png_image(document.part.related_parts[rid].blob))
                blocks.append(('\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows), False, pictures))
    texts, pictures, words = [], [], 0
    for text, heading, imgs in blocks:
        count = len(text.split())
        if texts and (heading or words + count > 400):
            yield '\n\n'.join(texts), pictures, bool(pictures)
            texts, pictures, words = [], [], 0
        if text.strip():
            texts.append(text)
        pictures.extend(imgs)
        words += count
    if texts or pictures:
        yield '\n\n'.join(texts), pictures, bool(pictures)


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
                yield page.get_text().strip(), [page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')], has_figures
    elif suffix == '.pptx':
        from pptx import Presentation
        presentation = Presentation(real)
        sw = getattr(presentation, 'slide_width', None)
        sh = getattr(presentation, 'slide_height', None)
        with _quicklook_slides(real, len(presentation.slides)) as render:
            for i, slide in enumerate(presentation.slides):
                text, _ = _slide_content(slide)
                if render:
                    pictures = [render(i)]
                else:
                    pictures = _filter_slide_images(slide, sw, sh)
                yield text, pictures, bool(pictures)
    else:
        with open(real, 'rb') as stream:
            yield '', [_png_image(stream.read())], True


def _extract_text(real):
    suffix = os.path.splitext(real)[1].lower()
    if suffix in ('.docx', '.txt', '.md'):
        yield from _document_pages(real)
    elif suffix == '.pdf':
        import pymupdf as fitz
        with fitz.open(real) as document:
            for page in document:
                yield page.get_text().strip(), [], False
    elif suffix == '.pptx':
        from pptx import Presentation
        for slide in Presentation(real).slides:
            yield _slide_content(slide)[0], [], False
    else:
        yield '', [], False


def _extract_images(real, previous):
    """Upgrade di una cache testuale: conserva il testo, rende le sole immagini mancanti."""
    if real.lower().endswith('.pdf'):
        import pymupdf as fitz
        from rt.core.material_page_filter import pdf_pages_have_figures
        with fitz.open(real) as document:
            figures = pdf_pages_have_figures(document)
            for i, page in enumerate(document):
                old = previous[i] if i < len(previous) else {}
                yield old.get('testo', ''), [page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')], figures[i]
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
            ctx.progress('prepare', message=f"Lettura di {name}: finita in {_elapsed(stats['seconds'])} "
                         f"(Vision {calls} chiamate, media {mean:.1f} s)")
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
    extracted = []
    # I PNG si liberano a ogni iterazione, senza accumulare l'intero PDF in RAM.
    with fs.materialize(path) as real:
        from rt.core.archive import read_json
        previous = read_json(os.path.join(folder, 'pages.json'), {}).get('pages', [])
        extraction = (_extract_images(real, previous) if upgrading and previous else _extract(real)) if extract != 'testo' else _extract_text(real)
        crops = (load_meta(source.impronta) or {}).get('ritagli', {})
        for number, (text, images, has_figures) in enumerate(extraction, 1):
            if ctx:
                ctx.check_cancelled()
            filenames = []
            with lesson_lock(lesson_dir):
                for index, data in enumerate(images, 1):
                    relative = f'page-{number}-{index}.png'
                    if str(number) not in crops or not fs.isfile(os.path.join(folder, relative)):
                        with fs.open(os.path.join(folder, relative) + '.tmp', 'wb') as stream:
                            stream.write(data)
                        fs.replace(os.path.join(folder, relative) + '.tmp', os.path.join(folder, relative))
                    filenames.append(relative)
            extracted.append((text, filenames, has_figures))
    if not extracted:
        raise ValueError('Il materiale non ha pagine')
    cleaned = cleaned_page_texts([text for text, _, _ in extracted])
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

    for number, (text, filenames, has_figures) in enumerate(extracted, 1):
        entry_path = os.path.join(folder, f'page-{number}.json')
        if not refresh and fs.isfile(entry_path):
            with fs.open(entry_path, encoding='utf-8') as stream:
                saved = json.load(stream)
            if 'has_figures' in saved and not saved.get('vision_pending'):
                if upgrading:
                    saved['immagini'] = filenames
                    saved['has_figures'] = has_figures
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
        texts, seconds = [], 0.0
        try:
            from rt.core.archive import read_json, write_json, archive_lock
            reusable = read_json(os.path.join(folder, 'descrizione.json')) if file_type(source.file) == 'immagine' else None
            if reusable and not refresh:
                described = '\n'.join(str(reusable.get(key) or '') for key in ('slide_title', 'ocr_text', 'visual_elements'))
                return save(dict(entry, testo=described, mapping_text=described)), 0, 0.0
            for relative in entry['immagini']:
                if stopped.is_set():
                    raise RunCancelled('Lettura dei materiali interrotta')
                if ctx:
                    ctx.check_cancelled()
                with fs.open(os.path.join(folder, relative), 'rb') as stream:
                    data = stream.read()
                before = time.monotonic()
                texts.append(_describe(data, lesson_dir, mock))
                seconds += time.monotonic() - before
            described = '\n'.join(texts)
            if file_type(source.file) == 'immagine':
                with archive_lock(source.impronta):
                    write_json(os.path.join(folder, 'descrizione.json'), {'ocr_text': described})
            entry = dict(entry, testo='\n'.join(filter(None, [entry['testo'], described])), mapping_text=described)
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
