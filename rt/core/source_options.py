"""Opzioni delle fonti: intervalli inclusivi, estrazione e ruolo."""
import re


def parse_pages(value, total=None):
    if value is None or value == '':
        return None
    if isinstance(value, list):
        if any(type(n) is not int for n in value):
            raise ValueError('Pagine non valide')
        pages = sorted(set(value))
    elif isinstance(value, str):
        pages = set()
        for part in value.replace('–', '-').split(','):
            match = re.fullmatch(r'\s*(\d+)\s*(?:-\s*(\d+)\s*)?', part)
            if not match:
                raise ValueError('Intervallo di pagine non valido')
            start, end = int(match[1]), int(match[2] or match[1])
            if start < 1 or end < start or end > (total or 100000):
                raise ValueError('Pagine fuori intervallo')
            pages.update(range(start, end + 1))
        pages = sorted(pages)
    else:
        raise ValueError('Pagine non valide')
    if not pages or min(pages) < 1 or (total is not None and max(pages) > total):
        raise ValueError('Pagine fuori intervallo')
    return pages


def default_extraction(filename):
    return 'testo' if filename.lower().endswith(('.docx', '.txt')) else 'immagini'
