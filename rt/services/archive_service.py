"""Consultazione dell'archivio e delle lezioni che ne usano i file."""
import os

from rt.core import archive
from rt.core.sources import load_sources


def usage_index():
    """Costruisce un indice {impronta: [usage, ...]} in un solo passaggio sulle lezioni."""
    from rt.services.archive_backfill import lesson_directories
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.core.state import read_info_yaml
    from rt.core.lesson_paths import lesson_path
    from rt.pipeline.add_images import load_image_descriptions
    from rt.storage import fs

    alias_map = archive.read_json(os.path.join(archive.archive_dir(), 'alias.json'), {})
    index = {}

    for directory in lesson_directories():
        info = read_info_yaml(lesson_path(directory, 'info.yaml'))
        titolo = info.get('titolo') or info.get('argomenti') or os.path.basename(directory)
        data = str(info.get('data') or '')
        materia = info.get('materia') or ''

        sources_by_sha = {}
        for s in load_sources(directory):
            if s.impronta:
                canonical = alias_map.get(s.impronta, s.impronta)
                sources_by_sha.setdefault(canonical, []).append(s)

        descriptions = load_image_descriptions(directory)
        images_by_sha = set()
        for h, desc in descriptions.items():
            if h not in sources_by_sha:
                fn = desc.get('filename', '')
                if fn and fs.isfile(os.path.join(directory, fn)):
                    images_by_sha.add(h)

        all_shas = set(sources_by_sha.keys()) | images_by_sha
        if not all_shas:
            continue

        try:
            lid = lesson_id_for_dir(directory)
        except Exception:
            lid = None
        for sha in all_shas:
            if sha in sources_by_sha:
                srcs = sources_by_sha[sha]
                pages = None if any(s.pagine is None for s in srcs) else sorted({n for s in srcs for n in s.pagine})
            else:
                pages = None
            index.setdefault(sha, []).append({
                'lezione_id': lid,
                'titolo': titolo,
                'data': data,
                'pagine': pages,
                'materia': materia,
            })

    for sha, usages in index.items():
        usages.sort(key=lambda u: (u['data'], u['lezione_id'] or 0))

    return index


def archive_usages(sha, index=None):
    if index is not None:
        return index.get(sha, [])
    return usage_index().get(sha, [])


def continuation(meta, usages):
    total = meta.get('pagine_totali')
    if meta['tipo'] != 'slide' or not total or not usages or any(u['pagine'] is None for u in usages):
        return None
    last = max((n for u in usages for n in u['pagine']), default=0)
    return f'{last + 1}–{total}' if 0 < last < total else None


def lookup(hashes, index=None):
    index = usage_index() if index is None else index
    results = {}
    for sha in hashes:
        meta = archive.find(sha)
        if meta is None:
            results[sha] = None
            continue
        usages = index.get(meta['impronta'], [])
        results[sha] = {'impronta': meta['impronta'], 'pagine_totali': meta.get('pagine_totali'),
            'usate': usages, 'da_continuare': continuation(meta, usages)}
    return results


def require_entry(sha):
    from rt.services.errors import NotFound
    try:
        meta = archive.find(sha)
    except ValueError:
        meta = None
    if meta is None:
        raise NotFound('archive_not_found', 'File non trovato.')
    return meta


def row(meta, usages=None, index=None):
    if usages is None:
        usages = index.get(meta['impronta'], []) if index is not None else archive_usages(meta['impronta'])
    return {**{key: meta.get(key) for key in ('impronta', 'nome', 'tipo', 'pagine_totali', 'durata_s', 'dimensione')},
        'materie': sorted({u['materia'] for u in usages if u['materia']}),
        'usi': len(usages), 'da_continuare': continuation(meta, usages)}


def list_entries(materia=None, tipo=None, q=None, index=None):
    index = usage_index() if index is None else index
    entries = []
    arch_dir = archive.archive_dir()
    if os.path.isdir(arch_dir):
        for sha in os.listdir(arch_dir):
            if len(sha) != 64:
                continue
            meta = archive.load_meta(sha)
            if not meta or (tipo and meta['tipo'] != tipo) or (q and q.casefold() not in meta['nome'].casefold()):
                continue
            item = row(meta, index=index)
            if materia and materia not in item['materie']:
                continue
            entries.append((meta['aggiunto_il'], item))
    return [item for _, item in sorted(entries, key=lambda e: e[0], reverse=True)]


def summary(materia=None, index=None):
    if materia:
        entries = list_entries(materia=materia, index=index)
        return {'file': len(entries), 'da_continuare': sum(bool(e['da_continuare']) for e in entries)}
    index = usage_index() if index is None else index
    arch_dir = archive.archive_dir()
    count = 0
    to_continue = 0
    if os.path.isdir(arch_dir):
        for sha in os.listdir(arch_dir):
            if len(sha) != 64:
                continue
            meta = archive.load_meta(sha)
            if not meta:
                continue
            count += 1
            usages = index.get(meta['impronta'], [])
            if continuation(meta, usages):
                to_continue += 1
    return {'file': count, 'da_continuare': to_continue}


def detail(sha, index=None):
    from pathlib import Path
    meta = require_entry(sha)
    sha = meta['impronta']
    usages = index.get(sha, []) if index is not None else archive_usages(sha)
    pages = archive.read_json(os.path.join(archive.entry_dir(sha), 'pages.json'), {}).get('pages', [])
    by_page = []
    for page in pages:
        n = page['numero']
        if n in meta.get('eliminate', []):
            continue
        used = [u for u in usages if u['pagine'] is None or n in u['pagine']]
        by_page.append({'numero': n, 'ignorata': n in meta.get('ignorate', []),
                        'lezione_id': used[-1]['lezione_id'] if used else None})
    transcript = ''
    if meta['tipo'] == 'audio':
        for path in sorted(Path(archive.entry_dir(sha)).glob('trascrizione-*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            data = archive.read_json(str(path), {})
            transcript = '\n'.join(s.get('text_raw', s.get('text', '')) for s in data.get('segments', [])[:5])
            if transcript:
                break
    return {**row(meta, usages=usages), 'pagine': by_page,
        'lezioni': [{'id': u['lezione_id'], 'titolo': u['titolo'], 'data': u['data'], 'pagine': u['pagine']} for u in usages],
        'trascrizione_inizio': transcript}


def image_path(sha, n):
    from rt.services.errors import NotFound
    meta = require_entry(sha)
    if n in meta.get('eliminate', []):
        raise NotFound('page_not_found', 'Pagina non trovata.')
    pages = archive.read_json(os.path.join(archive.entry_dir(meta['impronta']), 'pages.json'), {}).get('pages', [])
    page = next((p for p in pages if p['numero'] == n), None)
    images = (page or {}).get('immagini', [])
    path = archive.page_image_path(meta['impronta'], images[0]) if images else None
    if not path or not os.path.isfile(path):
        raise NotFound('page_not_found', 'Immagine della pagina non disponibile.')
    return path



def page_bytes(sha, n):
    """Anteprima su richiesta: il modo testo non crea una cache di immagini."""
    from rt.services.errors import NotFound
    meta = require_entry(sha)
    try:
        with open(image_path(sha, n), 'rb') as stream:
            return stream.read()
    except NotFound:
        data = archive.read_json(os.path.join(archive.entry_dir(meta['impronta']), 'pages.json'), {})
        page = next((p for p in data.get('pages', []) if p['numero'] == n), None)
        if not page or n in meta.get('eliminate', []):
            raise
    if meta['estensione'] == '.pdf':
        import fitz
        with fitz.open(archive.original_path(sha)) as document:
            return document[n - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).tobytes('png')
    import io
    import textwrap
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (900, 1200), 'white')
    draw = ImageDraw.Draw(image)
    text = '\n'.join(textwrap.fill(line, width=70) for line in page.get('testo', '').splitlines())
    draw.multiline_text((45, 45), text[:5000], fill='#26313b', font=ImageFont.load_default(size=20), spacing=6)
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()

def validate_pages(sha, pages):
    from rt.services.errors import Invalid
    meta = require_entry(sha)
    data = archive.read_json(os.path.join(archive.entry_dir(meta['impronta']), 'pages.json'), {})
    numbers = {p['numero'] for p in data.get('pages', []) if p['numero'] not in meta.get('eliminate', [])}
    if not pages or not set(pages) <= numbers:
        raise Invalid('pages_invalid', 'Pagine fuori intervallo.')


def set_ignored(sha, pages, ignored):
    meta = require_entry(sha)
    sha = meta['impronta']
    with archive.archive_lock(sha + '-extract'), archive.archive_lock(sha):
        validate_pages(sha, pages)
        meta = require_entry(sha)
        previous = set(meta.get('ignorate', []))
        meta['ignorate'] = sorted(previous | set(pages) if ignored else previous - set(pages))
        archive.write_json(os.path.join(archive.entry_dir(sha), 'meta.json'), meta)
    return detail(sha)


def delete_pages(sha, pages):
    meta = require_entry(sha)
    sha = meta['impronta']
    with archive.archive_lock(sha + '-extract'), archive.archive_lock(sha):
        validate_pages(sha, pages)
        meta = require_entry(sha)
        meta['eliminate'] = sorted(set(meta.get('eliminate', [])) | set(pages))
        folder = archive.entry_dir(sha)
        data = archive.read_json(os.path.join(folder, 'pages.json'), {})
        for page in data.get('pages', []):
            if page['numero'] in pages:
                for name in page.get('immagini', []):
                    path = archive.page_image_path(sha, name)
                    if os.path.isfile(path):
                        os.unlink(path)
                path = os.path.join(folder, f"page-{page['numero']}.json")
                if os.path.isfile(path):
                    os.unlink(path)
        archive.write_json(os.path.join(folder, 'meta.json'), meta)
    return detail(sha)


def crop(sha, n, rect, replace=False):
    import io
    import tempfile
    from PIL import Image
    from rt.services.errors import Invalid
    meta = require_entry(sha)
    sha = meta['impronta']
    left, top, width, height = rect
    if width <= 0 or height <= 0 or left + width > 1.000001 or top + height > 1.000001:
        raise Invalid('crop_invalid', 'Ritaglio non valido.')
    with archive.archive_lock(sha + '-extract'), archive.archive_lock(sha):
        data = page_bytes(sha, n)
        path = archive.page_image_path(sha, f'page-{n}-1.png')
        with Image.open(io.BytesIO(data)) as image:
            w, h = image.size
            box = (int(left * w), int(top * h), max(int(left * w) + 1, round((left + width) * w)),
                   max(int(top * h) + 1, round((top + height) * h)))
            output = io.BytesIO()
            image.crop(box).save(output, 'PNG')
        if replace:
            # os.replace evita di modificare un eventuale hardlink all'originale.
            fd, temp = tempfile.mkstemp(dir=archive.entry_dir(sha), suffix='.png.tmp')
            with os.fdopen(fd, 'wb') as stream:
                stream.write(output.getvalue())
            os.replace(temp, path)
            pages_path = os.path.join(archive.entry_dir(sha), 'pages.json')
            pages_data = archive.read_json(pages_path)
            for page in pages_data['pages']:
                if page['numero'] == n:
                    page['immagini'] = [os.path.basename(path)]
            archive.write_json(pages_path, pages_data)
            meta['ritagli'] = {**meta.get('ritagli', {}), str(n): rect}
            archive.write_json(os.path.join(archive.entry_dir(sha), 'meta.json'), meta)
            return row(meta)
    # delete=False: su Windows un file temporaneo aperto non si riapre per leggerlo.
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp:
        temp.write(output.getvalue())
    try:
        result = archive.register_image(temp.name)
    finally:
        os.unlink(temp.name)
    archive.save_meta(result['impronta'], {'nome': f"{meta['nome']} · pag. {n}", 'ritaglio_di': {'sha': sha, 'pagina': n}})
    return row(require_entry(result['impronta']))


def delete_entry(sha, index=None):
    import shutil
    from rt.services.errors import Conflict
    meta = require_entry(sha)
    sha = meta['impronta']
    with archive.archive_lock(sha + '-mutation'):
        usages = index.get(sha, []) if index is not None else archive_usages(sha)
        if usages:
            raise Conflict('archive_in_use', 'File usato da una lezione.', {'lezioni': usages})
        with archive.archive_lock(sha + '-extract'), archive.archive_lock(sha):
            entry_p = archive.entry_dir(sha)
            if os.path.exists(entry_p):
                shutil.rmtree(entry_p)
        with archive.archive_lock():
            index_path = os.path.join(archive.archive_dir(), 'alias.json')
            aliases = archive.read_json(index_path, {})
            archive.write_json(index_path, {k: v for k, v in aliases.items() if v != sha})


def add_to_lesson(sha, lesson_id, uso, pages, estrai):
    from rt.services.source_mutation import source_mutation
    from rt.core.sources import add_source
    meta = require_entry(sha)
    directory = resolve_lesson(lesson_id)
    with archive.archive_lock(meta['impronta'] + '-mutation'), source_mutation(lesson_id, directory):
        if pages is not None:
            validate_pages(sha, pages)
        return add_source(directory, 'audio' if meta['tipo'] == 'audio' else 'materiale',
            meta['nome'], None, source_path=archive.original_path(sha), pagine=pages, estrai=estrai, uso=uso)


def add_to_media(sha, lesson_id, pages):
    from rt.services.editor_media_service import _guard, _editor_image
    from rt.services.lesson_service import _require_db
    from rt.core.process_lock import lesson_work_lock, LessonBusy
    from rt.db.session import session_scope
    from rt.services.errors import Conflict
    from rt.pipeline.add_images import compute_image_hash, save_raw_image, load_image_descriptions, save_image_descriptions
    meta = require_entry(sha)
    directory = resolve_lesson(lesson_id)
    results = []
    try:
        with lesson_work_lock(directory):
            with session_scope(_require_db()) as session:
                _guard(session, lesson_id, directory, None, document=False)
            validate_pages(sha, pages)
            # Controlla tutte le immagini prima di iniziare la copia.
            contents = [(n, page_bytes(sha, n)) for n in pages]
            descriptions = load_image_descriptions(directory)
            for n, data in contents:
                image_hash = compute_image_hash(data)
                relative = save_raw_image(directory, data, image_hash)
                description = archive.read_json(os.path.join(archive.entry_dir(image_hash), 'descrizione.json'), {})
                page = next((p for p in archive.read_json(os.path.join(archive.entry_dir(meta['impronta']), 'pages.json'), {}).get('pages', []) if p['numero'] == n), {})
                description = {**description, 'ocr_text': description.get('ocr_text') or page.get('testo', ''), 'filename': relative, 'source': f'archive:{meta["impronta"]}:{n}',
                    'alt_text': f'{meta["nome"]}, pagina {n}'}
                descriptions.setdefault(image_hash, description)
                results.append(_editor_image(lesson_id, descriptions[image_hash]))
            save_image_descriptions(directory, descriptions)
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None
    return results


def resolve_lesson(lesson_id):
    from rt.services.lesson_service import resolve_lesson_dir, LessonNotFound
    from rt.services.errors import NotFound
    try:
        return resolve_lesson_dir(lesson_id)
    except LessonNotFound as exc:
        raise NotFound('lesson_not_found', str(exc)) from None
