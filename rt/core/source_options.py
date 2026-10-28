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


TEXT_DOCUMENTS = ('.docx', '.txt', '.md')


def landscape_pdf(path):
    """La prima pagina è orizzontale: di solito sono slide esportate in PDF."""
    try:
        import fitz
        from rt.storage import fs
        with fs.materialize(path) as real, fitz.open(real) as document:
            rect = document[0].rect if len(document) else None
        return bool(rect and rect.width > rect.height)
    except Exception:
        return True


def default_extraction(filename, path=None):
    """Testo per i documenti di testo e i PDF verticali; testo e immagini per slide, PDF
    orizzontali e immagini singole. Solo immagini non è mai un default."""
    name = filename.lower()
    if name.endswith(TEXT_DOCUMENTS):
        return 'testo'
    if name.endswith('.pdf') and path is not None:
        return 'immagini' if landscape_pdf(path) else 'testo'
    return 'immagini'


def text_only(filename):
    return filename.lower().endswith(TEXT_DOCUMENTS)
