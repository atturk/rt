"""Immagini inserite a mano: media della lezione, senza descrizione o collocazione LLM."""
import io
import os
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
