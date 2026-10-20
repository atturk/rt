"""Consultazione dell'archivio e delle lezioni che ne usano i file."""
import os

from rt.core import archive
from rt.core.sources import load_sources


def archive_usages(sha):
    from rt.services.archive_backfill import lesson_directories
    from rt.services.lesson_service import lesson_id_for_dir
    from rt.core.state import read_info_yaml
    from rt.core.lesson_paths import lesson_path
    usages = []
    for directory in lesson_directories():
        sources = [s for s in load_sources(directory) if s.impronta == sha]
        if not sources:
            continue
        info = read_info_yaml(lesson_path(directory, 'info.yaml'))
        pages = None if any(s.pagine is None for s in sources) else sorted({n for s in sources for n in s.pagine})
        usages.append({'lezione_id': lesson_id_for_dir(directory), 'titolo': info.get('titolo') or info.get('argomenti') or os.path.basename(directory),
            'data': str(info.get('data') or ''), 'pagine': pages, 'materia': info.get('materia') or ''})
    return sorted(usages, key=lambda u: (u['data'], u['lezione_id'] or 0))


def continuation(meta, usages):
    total = meta.get('pagine_totali')
    if meta['tipo'] != 'slide' or not total or not usages or any(u['pagine'] is None for u in usages):
        return None
    last = max((n for u in usages for n in u['pagine']), default=0)
    return f'{last + 1}–{total}' if 0 < last < total else None


def lookup(hashes):
    results = {}
    for sha in hashes:
        meta = archive.find(sha)
        if meta is None:
            results[sha] = None
            continue
        usages = archive_usages(meta['impronta'])
        results[sha] = {'impronta': meta['impronta'], 'pagine_totali': meta.get('pagine_totali'),
            'usate': usages, 'da_continuare': continuation(meta, usages)}
    return results
