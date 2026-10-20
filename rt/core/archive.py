"""Archivio condiviso delle fonti e dei risultati indipendenti dalla lezione."""
import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone

from rt.core.filelock import file_lock
from rt.core.idempotency import compute_file_sha256
from rt.core.paths import sub_dir
from rt.storage import fs


def archive_dir():
    return sub_dir('archivio', create=True)


def entry_dir(sha):
    if not re.fullmatch(r'[a-f0-9]{64}', sha):
        raise ValueError('Impronta non valida')
    return os.path.join(archive_dir(), sha)


@contextmanager
def archive_lock(key='indice'):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', key):
        raise ValueError('Lock non valido')
    with file_lock(os.path.join(sub_dir('locks', create=True), f'archive-{key}.lock'), retries=100):
        yield


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def write_json(path, data):
    import tempfile
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_meta(sha):
    return read_json(os.path.join(entry_dir(sha), 'meta.json'))


def save_meta(sha, meta):
    with archive_lock(sha):
        write_json(os.path.join(entry_dir(sha), 'meta.json'), {**(load_meta(sha) or {}), **meta})


def find(sha):
    meta = load_meta(sha)
    if meta:
        return meta
    target = read_json(os.path.join(archive_dir(), 'alias.json'), {}).get(sha)
    return load_meta(target) if target else None


def original_path(sha):
    meta = find(sha)
    if not meta:
        raise FileNotFoundError(sha)
    return os.path.join(entry_dir(meta['impronta']), 'originale' + meta['estensione'])


def file_type(path, tipo=None):
    ext = os.path.splitext(path)[1].lower()
    if tipo == 'audio':
        return 'audio'
    if ext in ('.docx', '.txt'):
        return 'testo'
    return 'slide' if ext in ('.pdf', '.pptx') else 'immagine'


def register_file(path, *, nome, tipo, sha=None, alias=None):
    sha = sha or compute_file_sha256(path)
    if tipo == 'audio' and os.path.splitext(path)[1].lower() != '.m4a':
        previous = find(sha)
        if previous and os.path.isfile(original_path(previous['impronta'])):
            return previous
        import tempfile
        from rt.pipeline.setup import transcode_audio_for_storage
        with tempfile.TemporaryDirectory(prefix='rt-archive-audio-') as temp:
            converted = os.path.join(temp, 'originale.m4a')
            with fs.materialize(path) as real:
                converted_ok = transcode_audio_for_storage(real, converted)
            if converted_ok:
                return register_file(converted, nome=nome, tipo=tipo, alias=list(set([sha, *(alias or [])])))
        # La fonte privata resta disponibile se ffmpeg rifiuta il file.
        return {'impronta': sha, 'estensione': os.path.splitext(path)[1].lower()}
    folder = entry_dir(sha)
    with archive_lock(sha):
        os.makedirs(folder, exist_ok=True)
        meta = load_meta(sha) or dict(impronta=sha, nome=nome, tipo=tipo,
            estensione=os.path.splitext(path)[1].lower(), dimensione=fs.getsize(path),
            aggiunto_il=datetime.now(timezone.utc).isoformat(), estrai='testo',
            alias=[], pagine_totali=1 if tipo == 'immagine' else None, durata_s=None,
            ignorate=[], eliminate=[], ritagli={})
        target = os.path.join(folder, 'originale' + meta['estensione'])
        if not os.path.exists(target):
            with fs.materialize(path) as real:
                try:
                    os.link(real, target)
                except OSError:
                    shutil.copyfile(real, target)
        meta['alias'] = sorted(set(meta.get('alias', []) + (alias or [])) - {sha})
        write_json(os.path.join(folder, 'meta.json'), meta)
    if alias:
        with archive_lock():
            index_path = os.path.join(archive_dir(), 'alias.json')
            index = read_json(index_path, {})
            index.update({item: sha for item in alias if item != sha})
            write_json(index_path, index)
    return meta


def page_image_path(sha, name):
    meta = find(sha)
    # Accetta anche i vecchi riferimenti materials/<sha>/page-N-K.png.
    base = os.path.basename(name)
    if not re.fullmatch(r'page-\d+-\d+\.png', base):
        raise ValueError('Nome di pagina non valido')
    return os.path.join(entry_dir(meta['impronta'] if meta else sha), base)


def import_material_cache(lesson_dir, source):
    folder = entry_dir(source.impronta)
    old = os.path.join(lesson_dir, 'materials', source.impronta)
    target = os.path.join(folder, 'pages.json')
    if os.path.isfile(target) or not fs.isfile(os.path.join(old, 'pages.json')):
        return
    with archive_lock(source.impronta):
        if os.path.isfile(target):
            return
        os.makedirs(folder, exist_ok=True)
        for name in fs.listdir(old):
            if re.fullmatch(r'page-\d+(?:-\d+)?\.(?:png|json)|pages\.json', name):
                with fs.materialize(os.path.join(old, name)) as real:
                    shutil.copyfile(real, os.path.join(folder, name))
        data = read_json(target)
        for page in data['pages']:
            page['immagini'] = [os.path.basename(p) for p in page.get('immagini', [])]
        write_json(target, data)
        meta = load_meta(source.impronta)
        if meta:
            write_json(os.path.join(folder, 'meta.json'), {**meta, 'pagine_totali': len(data['pages']),
                'estrai': 'immagini' if any(p.get('immagini') for p in data['pages']) else 'testo'})


def pages_for_use(sha, pagine=None):
    meta = find(sha) or {}
    data = read_json(os.path.join(entry_dir(meta.get('impronta', sha)), 'pages.json'), {})
    excluded = set(meta.get('ignorate', [])) | set(meta.get('eliminate', []))
    return [p for p in data.get('pages', []) if p['numero'] not in excluded
            and (pagine is None or p['numero'] in pagine)]


def cached_transcript(sha, motore):
    meta = find(sha)
    if not meta:
        return None
    return read_json(os.path.join(entry_dir(meta['impronta']), f'trascrizione-{_engine_key(motore)}.json'))


def _engine_key(motore):
    import hashlib
    return motore if re.fullmatch(r'[\w-]+', motore) else hashlib.sha256(motore.encode()).hexdigest()


def transcript_engine(mock=False):
    from rt.core.config import load_config
    stt = load_config().transcription
    return 'mock' if mock else (f'custom-{stt.model}-{stt.base_url}' if stt.engine == 'custom' else stt.engine)


def store_transcript(sha, motore, data):
    meta = find(sha)
    if meta:
        with archive_lock(meta['impronta']):
            write_json(os.path.join(entry_dir(meta['impronta']), f'trascrizione-{_engine_key(motore)}.json'), data)
            write_json(os.path.join(entry_dir(meta['impronta']), 'meta.json'),
                       {**meta, 'durata_s': data.get('duration')})


def register_image(path, description=None):
    meta = register_file(path, nome=os.path.basename(path), tipo='immagine')
    sha = meta['impronta']
    if description:
        with archive_lock(sha):
            write_json(os.path.join(entry_dir(sha), 'descrizione.json'), description)
    # Le immagini mantengono l'originale; la miniatura è una PNG indipendente.
    target = page_image_path(sha, 'page-1-1.png')
    if not os.path.exists(target):
        from rt.core.materials import _png_image
        try:
            with fs.open(path, 'rb') as stream:
                data = _png_image(stream.read())
            with open(target, 'wb') as output:
                output.write(data)
        except (OSError, ValueError):
            return meta
    pages_path = os.path.join(entry_dir(sha), 'pages.json')
    with archive_lock(sha):
        data = read_json(pages_path)
        meaningful = description and any(description.get(k) for k in ('ocr_text', 'slide_title', 'visual_elements'))
        if data is None or (meaningful and not all('mapping_text' in p for p in data.get('pages', []))):
            text = '\n'.join(str(description.get(k) or '') for k in ('slide_title', 'ocr_text', 'visual_elements')) if meaningful else ''
            page = {'numero': 1, 'testo': text, 'immagini': ['page-1-1.png']}
            if meaningful:
                page.update(has_figures=True, mapping_text=text, mapping_skip=False)
                current = load_meta(sha)
                write_json(os.path.join(entry_dir(sha), 'meta.json'), {**current, 'estrai': 'immagini'})
            write_json(pages_path, {'impronta': sha, 'pages': [page]})
    return meta
