"""Popolamento una tantum, riprendibile, senza elaborazione dei file."""
import logging
import os

from rt.core.archive import (archive_dir, archive_lock, read_json, write_json, register_file,
                             register_image, file_type, import_material_cache, save_meta, store_transcript)
from rt.storage import fs


def lesson_directories():
    from rt.core.config import load_config
    from rt.db.engine import get_database
    from rt.db.models import Lesson
    from rt.db.session import session_scope
    from sqlalchemy import select
    # Chiave canonica: su Windows lo stesso percorso arriva dal DB e dal disco in forme diverse
    # (nome breve RUNNER~1, maiuscole), e la lezione si conterebbe due volte.
    found = {}

    def add(path):
        found.setdefault(os.path.normcase(os.path.realpath(path)), path)

    db = get_database()
    if db:
        with session_scope(db) as session:
            for path in session.scalars(select(Lesson.path)):
                add(path)
    root = load_config().telegram.lessons_root
    if root and os.path.isdir(root):
        for top, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('history', 'sources', 'assets', 'materials', '_state')]
            if 'info.yaml' in files:
                add(top)
                dirs[:] = []
    return sorted(found.values())


def archive_backfill(directories=None, progress=None):
    from rt.core.sources import load_sources
    from rt.pipeline.add_images import load_image_descriptions
    from rt.pipeline.source_update import _read_state
    marker = os.path.join(archive_dir(), 'indice.json')
    with archive_lock('backfill'):
        if read_json(marker, {}).get('backfill_done'):
            return
        directories = lesson_directories() if directories is None else list(directories)
        for index, directory in enumerate(directories):
            if progress:
                progress(index, len(directories), os.path.basename(directory))
            try:
                state = _read_state(directory)
                for source in load_sources(directory):
                    path = os.path.join(directory, source.file)
                    if not fs.isfile(path) or source.tipo == 'appunti':
                        continue
                    if source.tipo == 'audio' and path.lower().endswith('.wav'):
                        from rt.core.archive import find
                        meta = find(source.impronta)
                        if meta is None:
                            import tempfile
                            from rt.pipeline.setup import transcode_audio_for_storage
                            with tempfile.TemporaryDirectory(prefix='rt-backfill-') as temp:
                                converted = os.path.join(temp, 'originale.m4a')
                                with fs.materialize(path) as real:
                                    converted_ok = transcode_audio_for_storage(real, converted)
                                if not converted_ok:
                                    logging.getLogger(__name__).warning('Audio non convertibile: %s', path)
                                    continue
                                meta = register_file(converted, nome=os.path.basename(source.file), tipo='audio', alias=[source.impronta])
                    else:
                        meta = register_file(path, nome=os.path.basename(source.file),
                            tipo=file_type(source.file, source.tipo), sha=source.impronta)
                    if source.tipo == 'materiale':
                        import_material_cache(directory, source)
                        from rt.core.archive import pages_for_use
                        pages = pages_for_use(source.impronta)
                        if pages:
                            save_meta(source.impronta, {'pagine_totali': len(pages),
                                'estrai': 'immagini' if any(p.get('immagini') for p in pages) else 'testo'})
                    transcript = state.get('sources', {}).get(source.id, {})
                    engine = transcript.get('motore')
                    if source.tipo == 'audio' and engine:
                        store_transcript(meta['impronta'], engine, transcript)
                    if source.id == 'src_000001' and not engine:
                        raw = os.path.join(directory, 'trascritto grezzo.json')
                        if fs.isfile(raw):
                            import json
                            with fs.open(raw, encoding='utf-8') as stream:
                                data = json.load(stream)
                            if data.get('motore'):
                                from rt.core.segments import parse_segments_from_json
                                segments = parse_segments_from_json(raw)
                                store_transcript(meta['impronta'], data['motore'],
                                    {'segments': [s.model_dump() for s in segments],
                                     'duration': max((s.end_seconds for s in segments), default=0)})
                descriptions = load_image_descriptions(directory)
                images = os.path.join(directory, 'assets', 'images')
                by_name = {d.get('filename'): d for d in descriptions.values()}
                if fs.isdir(images):
                    for name in fs.listdir(images):
                        if os.path.splitext(name)[1].lower() in ('.png', '.jpg', '.jpeg', '.gif', '.heic'):
                            register_image(os.path.join(images, name), by_name.get(f'assets/images/{name}'))
            except Exception:
                logging.getLogger(__name__).exception('Popolamento archivio: %s', directory)
        write_json(marker, {'backfill_done': True})


def start_backfill():
    """Accoda una sola migrazione; il worker usa gli stessi lock del comando diretto."""
    from rt.services.jobs import get_job_queue as queue
    if read_json(os.path.join(archive_dir(), 'indice.json'), {}).get('backfill_done'):
        return
    with archive_lock('enqueue'):
        pending = queue().list(state=['queued', 'running'], job_type='archive_backfill')
        if not pending:
            queue().enqueue('archive_backfill', None, {})
