"""Immagini inserite a mano: media della lezione, senza descrizione o collocazione LLM."""
import io
import os
import re
import warnings

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from rt.core.process_lock import LessonBusy, lesson_work_lock
from rt.db.models import Job, Lesson, Setting
from rt.db.session import session_scope
from rt.pipeline.add_images import compute_image_hash, load_image_descriptions, save_image_descriptions, save_raw_image
from rt.services.document_edit_lease import _active, _key, DocumentBeingEdited
from rt.services.errors import Conflict, Invalid, NotFound, TooLarge
from rt.services.lesson_service import _require_db
from rt.storage import fs

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'GIF': '.gif'}


def upload_image(lesson_id: int, lesson_dir: str, content: bytes, filename: str,
                 lease_token: str | None = None) -> dict:
    """Conserva i byte originali, comprese le animazioni GIF; deduplica con SHA-256."""
    if len(content) > MAX_IMAGE_BYTES:
        raise TooLarge('image_too_large', 'Immagine troppo grande: massimo 10 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                extension = _FORMATS.get(image.format)
                if extension is None:
                    raise Invalid('image_format_invalid', 'Usa immagini PNG, JPEG o GIF.')
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Invalid('image_invalid', 'Immagine non valida.') from None
    # Il nome è una didascalia, mai un percorso di destinazione né markup.
    name = os.path.basename(filename.replace('\\', '/'))
    alt = ' '.join(os.path.splitext(name)[0].replace('[', '').replace(']', '').split())[:200] or 'Immagine'
    image_hash = compute_image_hash(content)
    try:
        with lesson_work_lock(lesson_dir), session_scope(_require_db()) as session:
            lesson = session.get(Lesson, lesson_id)
            if lesson is None or os.path.realpath(lesson_dir) != lesson.path:
                raise NotFound('lesson_not_found', 'Lezione non trovata.')
            busy = session.scalar(select(Job.id).where(Job.lesson_path == lesson.path,
                Job.state.in_(['queued', 'running']), Job.type != 'documents').limit(1))
            if busy:
                raise Conflict('lesson_busy', 'Un job sta lavorando sulla lezione.', {'job_id': busy})
            lease = session.get(Setting, _key(lesson_id))
            if lease and _active(lease.value) and lease.value.get('token') != lease_token:
                raise DocumentBeingEdited()
            if lease_token and (not lease or not _active(lease.value) or lease.value.get('token') != lease_token):
                raise Conflict('document_edit_invalid', 'Sessione di modifica scaduta.')
            descriptions = load_image_descriptions(lesson_dir)
            existing = descriptions.get(image_hash)
            relative = save_raw_image(lesson_dir, content, image_hash, ext=os.path.splitext(existing['filename'])[1] if existing else extension)
            if existing:
                relative = existing['filename']
                alt = existing.get('alt_text') or alt
            else:
                descriptions[image_hash] = {'filename': relative, 'source': f'editor:{name}',
                    'slide_title': '', 'ocr_text': '', 'visual_elements': [],
                    'summary_keywords': [], 'alt_text': alt}
                save_image_descriptions(lesson_dir, descriptions)
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None
    return {'path': relative, 'name': os.path.basename(relative), 'alt_text': alt,
            'url': f'/api/v1/lessons/{lesson_id}/assets/images/{os.path.basename(relative)}'}


def _guard(session, lesson_id: int, lesson_dir: str, lease_token: str | None, *, document: bool) -> None:
    """Stessi controlli di upload_image: lezione giusta, nessun job; il lease solo se si tocca il testo."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or os.path.realpath(lesson_dir) != lesson.path:
        raise NotFound('lesson_not_found', 'Lezione non trovata.')
    busy = session.scalar(select(Job.id).where(Job.lesson_path == lesson.path,
        Job.state.in_(['queued', 'running']), Job.type != 'documents').limit(1))
    if busy:
        raise Conflict('lesson_busy', 'Un job sta lavorando sulla lezione.', {'job_id': busy})
    if not document:
        return
    lease = session.get(Setting, _key(lesson_id))
    if lease and _active(lease.value) and lease.value.get('token') != lease_token:
        raise DocumentBeingEdited()
    if lease_token and (not lease or not _active(lease.value) or lease.value.get('token') != lease_token):
        raise Conflict('document_edit_invalid', 'Sessione di modifica scaduta.')


_MATERIAL_TAG = re.compile(r'^material:([^:]+):(\d+)$')


def _material_source(lesson_dir: str, source_id: str):
    from rt.core.sources import load_sources
    source = next((s for s in load_sources(lesson_dir)
                   if (s.id == source_id or s.impronta == source_id) and not s.rimossa_il), None)
    if source is None:
        raise NotFound('source_not_found', 'Fonte non trovata.')
    return source


def _copy_material_page(lesson_dir: str, source_id: str, page_number: int) -> tuple[str, dict]:
    """Copia la pagina in assets e la registra; va chiamata con il lock della lezione già preso.
    Usa solo le pagine già lette all'import: mai estrazioni o modelli dentro una richiesta."""
    from rt.core.materials import cached_pages
    source = _material_source(lesson_dir, source_id)
    page = next((p for p in cached_pages(lesson_dir, source) or [] if int(p.get('numero', 0)) == page_number), None)
    images = (page or {}).get('immagini') or []
    img_rel = images[0] if images else None
    if not img_rel or not fs.isfile(os.path.join(lesson_dir, img_rel)):
        raise NotFound('page_not_found', f'Pagina {page_number} del materiale non trovata.')
    with fs.open(os.path.join(lesson_dir, img_rel), 'rb') as f:
        content = f.read()
    image_hash = compute_image_hash(content)
    descriptions = load_image_descriptions(lesson_dir)
    if image_hash not in descriptions:
        relative = save_raw_image(lesson_dir, content, image_hash, ext='.png')
        descriptions[image_hash] = {
            'filename': relative, 'source': f'material:{source.id}:{page_number}',
            'slide_title': '', 'ocr_text': page.get('testo', '') or '', 'visual_elements': [],
            'summary_keywords': [], 'alt_text': f'{os.path.basename(source.file)}, pagina {page_number}',
        }
        save_image_descriptions(lesson_dir, descriptions)
    return image_hash, descriptions[image_hash]


def _editor_image(lesson_id: int, entry: dict) -> dict:
    relative = entry['filename']
    name = os.path.basename(relative)
    return {'path': relative, 'name': name, 'alt_text': entry.get('alt_text') or name,
            'url': f'/api/v1/lessons/{lesson_id}/assets/images/{name}'}


def copy_material_page_to_assets(lesson_id: int, lesson_dir: str, source_id: str,
                                 page_number: int, lease_token: str | None = None) -> dict:
    """Copia una pagina dei materiali in assets/images (source 'material:<id>:<pagina>').
    Non tocca il testo: niente lease, così l'editor aperto può inserirla al cursore."""
    try:
        with lesson_work_lock(lesson_dir), session_scope(_require_db()) as session:
            _guard(session, lesson_id, lesson_dir, lease_token, document=False)
            _hash, entry = _copy_material_page(lesson_dir, source_id, page_number)
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None
    return _editor_image(lesson_id, entry)


_IMAGE_LINE = re.compile(r'!\[[^\]]*\]\((?:assets/images/)?([^)\s]+)\)')


def _rewrite_document(lesson_dir: str, change) -> bool:
    """Applica `change(riga) -> riga | None` alle righe del documento mostrato e salva come fa
    l'editor (save_document_edit: bozza, posizionamento e fotografia della versione)."""
    from rt.services.document_edit_service import save_document_edit
    from rt.services.lesson_service import load_markdown_preview
    markdown = load_markdown_preview(lesson_dir)
    lines = []
    for line in markdown.split('\n'):
        updated = change(line)
        if updated is not None:
            lines.append(updated)
    new = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))
    if new == markdown:
        return False
    save_document_edit(lesson_dir, new)
    return True


def _hashes_for_names(descriptions: dict, names: set[str]) -> set[str]:
    return {h for h, d in descriptions.items() if os.path.basename(str(d.get('filename') or '')) in names}


def _strip_placement(lesson_dir: str, hashes: set[str], replacement: str | None = None) -> None:
    from rt.pipeline.image_placement import load_image_placement, save_image_placement
    placement = load_image_placement(lesson_dir)
    if not placement or not hashes:
        return

    def fix(values):
        out = []
        for h in values:
            h = replacement if (h in hashes and replacement) else h
            if h in hashes or h in out:
                continue
            out.append(h)
        return out
    macros = {k: fix(v) for k, v in placement.get('macros', {}).items()}
    units = {k: fix(v) for k, v in placement.get('units', {}).items()}
    if macros != placement.get('macros', {}) or units != placement.get('units', {}):
        save_image_placement(lesson_dir, macros, placement.get('carousel', False), units=units)


def remove_images_from_lesson(lesson_id: int, lesson_dir: str, image_names: list[str],
                              lease_token: str | None = None) -> dict:
    """Toglie dal testo e da placement.json le immagini indicate; restano nei media come
    'non usata'. Il testo si salva come dall'editor; history/ non si tocca."""
    names = {os.path.basename(n) for n in image_names if n}
    if not names:
        return {'removed': []}
    try:
        with lesson_work_lock(lesson_dir):
            with session_scope(_require_db()) as session:
                _guard(session, lesson_id, lesson_dir, lease_token, document=True)

            def drop(line):
                refs = _IMAGE_LINE.findall(line)
                if refs and all(os.path.basename(r) in names for r in refs) and not _IMAGE_LINE.sub('', line).strip():
                    return None
                return line
            _rewrite_document(lesson_dir, drop)
            _strip_placement(lesson_dir, _hashes_for_names(load_image_descriptions(lesson_dir), names))
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None
    return {'removed': sorted(names)}


def _open_checked(path: str):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with fs.open(path, 'rb') as f:
                image = Image.open(io.BytesIO(f.read()))
                image.load()
        return image
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Invalid('image_invalid', 'Immagine non valida.') from None


def crop_image(lesson_id: int, lesson_dir: str, image_name: str, rect: list[float],
               replace: bool = False, lease_token: str | None = None,
               update_document: bool = True) -> dict:
    """Ritaglia con Pillow (rect relativo [left, top, width, height]). Nuova immagine
    'Pag. N · ritaglio K' (K per pagina, mai riusato) oppure, con replace, 'Pag. N (ritagliata)'
    al posto dell'originale nel testo e in placement.json. L'originale resta su disco.
    Con update_document=False il testo lo cambia l'editor aperto (evento nel frontend)."""
    if len(rect) != 4:
        raise Invalid('crop_invalid', 'Ritaglio non valido.')
    left, top, width, height = (max(0.0, min(1.0, float(v))) for v in rect)
    if width < 0.005 or height < 0.005 or left >= 1 or top >= 1:
        raise Invalid('crop_invalid', 'Ritaglio troppo piccolo.')
    width, height = min(width, 1 - left), min(height, 1 - top)
    try:
        with lesson_work_lock(lesson_dir):
            with session_scope(_require_db()) as session:
                _guard(session, lesson_id, lesson_dir, lease_token, document=replace and update_document)

            descriptions = load_image_descriptions(lesson_dir)
            tag = _MATERIAL_TAG.match(image_name or '')
            if tag:
                orig_hash, orig = _copy_material_page(lesson_dir, tag.group(1), int(tag.group(2)))
                descriptions = load_image_descriptions(lesson_dir)
            else:
                matches = _hashes_for_names(descriptions, {os.path.basename(image_name or '')})
                if not matches:
                    raise NotFound('image_not_found', 'Immagine non trovata.')
                orig_hash = next(iter(matches))
                orig = descriptions[orig_hash]

            image = _open_checked(os.path.join(lesson_dir, orig['filename']))
            w, h = image.size
            box = (int(left * w), int(top * h), max(int(left * w) + 1, round((left + width) * w)),
                   max(int(top * h) + 1, round((top + height) * h)))
            buf = io.BytesIO()
            image.crop((box[0], box[1], min(w, box[2]), min(h, box[3]))).save(buf, format='PNG')
            crop_bytes = buf.getvalue()
            crop_hash = compute_image_hash(crop_bytes)

            # La pagina d'origine: il ritaglio di un ritaglio conta sulla stessa pagina.
            root = orig.get('crop_root') or orig.get('crop_of') or orig_hash
            root_entry = descriptions.get(root, orig)
            match = re.search(r':(\d+)$', str(root_entry.get('source') or '')) or \
                re.search(r'#(\d+)$', str(root_entry.get('source') or '')) or \
                re.search(r'pagina\s+(\d+)', str(root_entry.get('alt_text') or ''), re.IGNORECASE)
            label = f'Pag. {match.group(1)}' if match else (root_entry.get('alt_text') or 'Immagine')

            if crop_hash not in descriptions:
                if replace:
                    k, alt = 0, f'{label} (ritagliata)'
                else:
                    k = 1 + max([int(d.get('crop_index') or 0) for d in descriptions.values()
                                 if d.get('crop_root') == root] or [0])
                    alt = f'{label} · ritaglio {k}'
                descriptions[crop_hash] = {
                    'filename': save_raw_image(lesson_dir, crop_bytes, crop_hash, ext='.png'),
                    'source': orig.get('source', ''), 'crop_of': orig_hash, 'crop_root': root,
                    'crop_index': k, 'is_crop': True, 'alt_text': alt,
                    'ocr_text': orig.get('ocr_text', ''), 'slide_title': '', 'visual_elements': [],
                    'summary_keywords': [],
                }
                save_image_descriptions(lesson_dir, descriptions)
            entry = descriptions[crop_hash]

            if replace and update_document and crop_hash != orig_hash:
                old_name = os.path.basename(orig['filename'])
                new_rel = entry['filename']
                alt = entry.get('alt_text', '').replace('[', '').replace(']', '')

                def swap(line):
                    return re.sub(r'!\[[^\]]*\]\((?:assets/images/)?' + re.escape(old_name) + r'\)',
                                  lambda _m: f'![{alt}]({new_rel})', line)
                _rewrite_document(lesson_dir, swap)
                _strip_placement(lesson_dir, {orig_hash}, replacement=crop_hash)
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None
    return _editor_image(lesson_id, entry)
