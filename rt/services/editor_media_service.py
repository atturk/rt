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


def copy_material_page_to_assets(lesson_id: int, lesson_dir: str, source_id: str,
                                 page_number: int, lease_token: str | None = None) -> dict:
    """Copia una pagina dei materiali in assets/images, registrandola in descriptions.json
    con source 'material:<id>:<pagina>'. Rispetta il lock della lezione e il lease dell'editor."""
    from rt.core.sources import load_sources
    from rt.core.materials import cached_pages, material_pages

    sources = load_sources(lesson_dir)
    source = next((s for s in sources if s.id == source_id or s.impronta == source_id), None)
    if not source:
        raise NotFound('source_not_found', f'Fonte {source_id} non trovata.')

    pages = cached_pages(lesson_dir, source)
    if not pages:
        try:
            pages = material_pages(lesson_dir, source, mock=True)
        except Exception:
            pages = None

    img_rel = None
    page_text = ""
    if pages:
        page = next((p for p in pages if int(p.get('numero', 0)) == page_number), None)
        if page:
            page_text = page.get('testo', '')
            imgs = page.get('immagini', [])
            if imgs:
                img_rel = imgs[0]

    if not img_rel:
        candidate = os.path.join('materials', source.impronta, f'page-{page_number}-1.png')
        if fs.isfile(os.path.join(lesson_dir, candidate)):
            img_rel = candidate

    if not img_rel or not fs.isfile(os.path.join(lesson_dir, img_rel)):
        raise NotFound('page_not_found', f'Pagina {page_number} del materiale non trovata.')

    with fs.open(os.path.join(lesson_dir, img_rel), 'rb') as f:
        content = f.read()

    src_name = os.path.basename(source.file)
    alt = f"{src_name}, pagina {page_number}"
    source_tag = f"material:{source.id}:{page_number}"
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
            relative = save_raw_image(lesson_dir, content, image_hash, ext='.png')
            if existing:
                relative = existing['filename']
                alt = existing.get('alt_text') or alt
            else:
                descriptions[image_hash] = {
                    'filename': relative,
                    'source': source_tag,
                    'slide_title': '',
                    'ocr_text': page_text,
                    'visual_elements': [],
                    'summary_keywords': [],
                    'alt_text': alt,
                }
                save_image_descriptions(lesson_dir, descriptions)
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None

    return {
        'path': relative,
        'name': os.path.basename(relative),
        'alt_text': alt,
        'url': f'/api/v1/lessons/{lesson_id}/assets/images/{os.path.basename(relative)}',
    }


def remove_images_from_lesson(
    lesson_id: int,
    lesson_dir: str,
    image_names: list[str],
    lease_token: str | None = None,
) -> dict:
    """Toglie dal documento e da placement.json i riferimenti alle immagini indicate.

    Non toglie le immagini da descriptions.json né da assets/images/ (restano nei media
    come 'non usata'). Non tocca mai history/. Rispetta il lock e il lease della lezione.
    """
    if not image_names:
        return {'removed': []}

    try:
        with lesson_work_lock(lesson_dir):
            with session_scope(_require_db()) as session:
                lesson = session.get(Lesson, lesson_id)
                if lesson is None or os.path.realpath(lesson_dir) != lesson.path:
                    raise NotFound('lesson_not_found', 'Lezione non trovata.')
                busy = session.scalar(
                    select(Job.id).where(
                        Job.lesson_path == lesson.path,
                        Job.state.in_(['queued', 'running']),
                        Job.type != 'documents',
                    ).limit(1)
                )
                if busy:
                    raise Conflict('lesson_busy', 'Un job sta lavorando sulla lezione.', {'job_id': busy})
                lease = session.get(Setting, _key(lesson_id))
                if lease and _active(lease.value) and lease.value.get('token') != lease_token:
                    raise DocumentBeingEdited()
                if lease_token and (not lease or not _active(lease.value) or lease.value.get('token') != lease_token):
                    raise Conflict('document_edit_invalid', 'Sessione di modifica scaduta.')

            # 1. Rimuovi da placement.json
            from rt.pipeline.image_placement import load_image_placement, save_image_placement

            placement = load_image_placement(lesson_dir)
            strip_hashes = {
                os.path.splitext(os.path.basename(n))[0] for n in image_names
            }
            strip_names = {os.path.basename(n) for n in image_names}

            if placement:
                macros = {
                    k: [h for h in v if h not in strip_names and h not in strip_hashes]
                    for k, v in placement.get('macros', {}).items()
                }
                units = {
                    k: [h for h in v if h not in strip_names and h not in strip_hashes]
                    for k, v in placement.get('units', {}).items()
                }
                save_image_placement(
                    lesson_dir,
                    macros,
                    placement.get('carousel', False),
                    units=units,
                )

            # 2. Rimuovi dal documento markdown (senza toccare history/*/)
            doc_path = os.path.join(lesson_dir, 'document.md')
            if fs.isfile(doc_path):
                with fs.open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                lines = content.splitlines()
                new_lines = []
                for line in lines:
                    match = re.search(r'!\[.*?\]\((?:assets/images/)?(.*?)\)', line)
                    if match:
                        target = os.path.basename(match.group(1))
                        target_hash = os.path.splitext(target)[0]
                        if target in strip_names or target in strip_hashes or target_hash in strip_hashes:
                            continue
                    new_lines.append(line)
                new_content = '\n'.join(new_lines)
                new_content = re.sub(r'\n{3,}', '\n\n', new_content).strip() + '\n'
                tmp_path = doc_path + '.tmp'
                with fs.open(tmp_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                fs.replace(tmp_path, doc_path)

        return {'removed': image_names}
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None


def crop_image(
    lesson_id: int,
    lesson_dir: str,
    image_name: str,
    rect: list[float],
    replace: bool = False,
    lease_token: str | None = None,
) -> dict:
    """Ritaglia un'immagine con Pillow (coordinate relative 0-1 [left, top, width, height]).
    Se replace=False: salva come nuova immagine con nome 'Pag. N · ritaglio K'.
    Se replace=True: sostituisce i riferimenti nel documento e in placement.json con 'Pag. N (ritagliata)'.
    Il file originale resta sempre su disco per preservare le versioni in history/."""
    from PIL import Image
    import io
    from rt.core.sources import load_sources

    # 1. Clamp delle coordinate tra 0 e 1
    left = max(0.0, min(1.0, float(rect[0])))
    top = max(0.0, min(1.0, float(rect[1])))
    width = max(0.001, min(1.0 - left, float(rect[2])))
    height = max(0.001, min(1.0 - top, float(rect[3])))

    # 2. Trova l'immagine sorgente
    descriptions = load_image_descriptions(lesson_dir)
    orig_hash = None
    orig_desc = None

    if image_name in descriptions:
        orig_hash = image_name
        orig_desc = descriptions[image_name]
    else:
        for h, d in descriptions.items():
            fn = d.get('filename', '')
            if fn == image_name or os.path.basename(fn) == os.path.basename(image_name):
                orig_hash = h
                orig_desc = d
                break

    file_path = None
    page_number = 1
    src_name = "immagine"

    if orig_desc and orig_hash:
        file_path = os.path.join(lesson_dir, orig_desc['filename'])
        alt_str = orig_desc.get('alt_text', '')
        src_str = orig_desc.get('source', '')
        m = re.search(r'pagina\s+(\d+)', alt_str, re.IGNORECASE) or re.search(r':(\d+)$', src_str)
        if m:
            page_number = int(m.group(1))
        src_name = alt_str.split(',')[0] if ',' in alt_str else os.path.basename(src_str)
    else:
        sources = load_sources(lesson_dir)
        mat_match = None
        for s in sources:
            if s.impronta in image_name or s.id in image_name:
                mat_match = s
                break
        if mat_match is None and sources:
            for s in sources:
                cand = os.path.join(lesson_dir, 'materials', s.impronta, os.path.basename(image_name))
                if fs.isfile(cand):
                    mat_match = s
                    break
        if mat_match:
            src_name = os.path.basename(mat_match.file)
            m = re.search(r'page-(\d+)', image_name) or re.search(r':(\d+)$', image_name)
            page_number = int(m.group(1)) if m else 1
            cand = os.path.join('materials', mat_match.impronta, f'page-{page_number}-1.png')
            if fs.isfile(os.path.join(lesson_dir, cand)):
                file_path = os.path.join(lesson_dir, cand)
                with fs.open(file_path, 'rb') as f:
                    orig_content = f.read()
                orig_hash = compute_image_hash(orig_content)
                orig_rel = save_raw_image(lesson_dir, orig_content, orig_hash, ext='.png')
                if orig_hash not in descriptions:
                    descriptions[orig_hash] = {
                        'filename': orig_rel,
                        'source': f'material:{mat_match.id}:{page_number}',
                        'alt_text': f'{src_name}, pagina {page_number}',
                        'ocr_text': '',
                    }
                    save_image_descriptions(lesson_dir, descriptions)
                orig_desc = descriptions[orig_hash]
                file_path = os.path.join(lesson_dir, orig_rel)

    if not file_path or not fs.isfile(file_path):
        raise NotFound('image_not_found', f"Immagine {image_name} non trovata.")

    # 3. Ritaglio con Pillow
    with fs.open(file_path, 'rb') as f:
        img = Image.open(f)
        img.load()
    w, h = img.size
    x0 = int(round(left * w))
    y0 = int(round(top * h))
    crop_w = max(1, int(round(width * w)))
    crop_h = max(1, int(round(height * h)))
    x1 = min(w, x0 + crop_w)
    y1 = min(h, y0 + crop_h)
    cropped = img.crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    cropped.save(buf, format='PNG')
    crop_bytes = buf.getvalue()

    # 4. Salvataggio immagine ritagliata
    crop_hash = compute_image_hash(crop_bytes)
    crop_rel = save_raw_image(lesson_dir, crop_bytes, crop_hash, ext='.png')
    crop_filename = os.path.basename(crop_rel)

    # 5. Nome e indice di ritaglio
    descriptions = load_image_descriptions(lesson_dir)
    orig_filename = os.path.basename(orig_desc['filename']) if orig_desc else os.path.basename(file_path)

    if replace:
        alt_text = f"Pag. {page_number} (ritagliata)"
        k = 0
    else:
        existing_k = [
            d.get('crop_index', 0)
            for d in descriptions.values()
            if d.get('crop_of') == orig_hash
        ]
        k = max(existing_k or [0]) + 1
        alt_text = f"Pag. {page_number} · ritaglio {k}"

    descriptions[crop_hash] = {
        'filename': crop_rel,
        'source': orig_desc.get('source', '') if orig_desc else '',
        'crop_of': orig_hash,
        'crop_index': k,
        'is_crop': True,
        'alt_text': alt_text,
        'ocr_text': orig_desc.get('ocr_text', '') if orig_desc else '',
    }
    save_image_descriptions(lesson_dir, descriptions)

    # 6. Se replace=True: sostituzione nel documento e in placement.json
    if replace:
        try:
            with lesson_work_lock(lesson_dir):
                db = _require_db()
                if db is not None:
                    with session_scope(db) as session:
                        lesson = session.get(Lesson, lesson_id)
                        if lesson is None or os.path.realpath(lesson_dir) != lesson.path:
                            raise NotFound('lesson_not_found', 'Lezione non trovata.')
                        busy = session.scalar(
                            select(Job.id).where(
                                Job.lesson_path == lesson.path,
                                Job.state.in_(['queued', 'running']),
                                Job.type != 'documents',
                            ).limit(1)
                        )
                        if busy:
                            raise Conflict('lesson_busy', 'Un job sta lavorando sulla lezione.', {'job_id': busy})
                        lease = session.get(Setting, _key(lesson_id))
                        if lease and _active(lease.value) and lease.value.get('token') != lease_token:
                            raise DocumentBeingEdited()
                        if lease_token and (not lease or not _active(lease.value) or lease.value.get('token') != lease_token):
                            raise Conflict('document_edit_invalid', 'Sessione di modifica scaduta.')

                # Sostituzione in placement.json (fuori da session_scope)
                from rt.pipeline.image_placement import load_image_placement, save_image_placement
                placement = load_image_placement(lesson_dir)
                if placement:
                    macros = {
                        sec: [crop_hash if h == orig_hash else h for h in hashes]
                        for sec, hashes in placement.get('macros', {}).items()
                    }
                    units = {
                        sec: [crop_hash if h == orig_hash else h for h in hashes]
                        for sec, hashes in placement.get('units', {}).items()
                    }
                    save_image_placement(
                        lesson_dir,
                        macros,
                        placement.get('carousel', False),
                        units=units,
                    )

                # Sostituzione nel documento markdown
                doc_path = os.path.join(lesson_dir, 'document.md')
                if fs.isfile(doc_path):
                    with fs.open(doc_path, 'r', encoding='utf-8') as f:
                        doc_text = f.read()
                    pattern = rf'(!\[.*?\]\()(?:assets/images/)?{re.escape(orig_filename)}(\))'
                    new_doc = re.sub(pattern, rf'\g<1>assets/images/{crop_filename}\g<2>', doc_text)
                    if new_doc != doc_text:
                        tmp_doc = doc_path + '.tmp'
                        with fs.open(tmp_doc, 'w', encoding='utf-8') as f:
                            f.write(new_doc)
                        fs.replace(tmp_doc, doc_path)
        except LessonBusy:
            raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None

    return {
        'name': crop_filename,
        'path': crop_rel,
        'alt_text': alt_text,
        'url': f'/api/v1/lessons/{lesson_id}/assets/images/{crop_filename}',
    }


