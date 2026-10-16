"""Controlli locali sulle pagine, condivisi da import e Arricchimento."""
import math
import re
from collections import Counter

REPEATED_LINE_FRACTION = 0.60
REPEATED_LINE_MIN_PAGES = 4
MIN_SIGNIFICANT_WORDS = 12
MIN_VECTOR_AREA_FRACTION = 0.08


def cleaned_page_texts(texts):
    """Conta ogni riga una sola volta per pagina; lascia intatti gli originali."""
    def normalize(line):
        return re.sub(r"\s+", " ", line).strip().casefold()
    counts = Counter(line for text in texts for line in {normalize(s) for s in text.splitlines()} if line)
    repeated = {line for line, count in counts.items()
                if len(texts) >= REPEATED_LINE_MIN_PAGES
                and count >= math.ceil(len(texts) * REPEATED_LINE_FRACTION)}
    return ["\n".join(line for line in text.splitlines() if normalize(line) not in repeated).strip()
            for text in texts]


def few_words(text):
    from rt.pipeline.material_mapping import tokenize_text
    return len(tokenize_text(text)) < MIN_SIGNIFICANT_WORDS


MIN_IMAGE_AREA_FRACTION = 0.05
BACKGROUND_AREA_FRACTION = 0.90


def _figure_keys(page):
    """Immagini e disegni estesi della pagina, con una chiave per riconoscere quelli ripetuti."""
    area = page.rect.get_area()
    if not area:
        return []
    keys = []
    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox")
        rect_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) if bbox else 0
        if rect_area >= area * MIN_IMAGE_AREA_FRACTION:
            keys.append(("img", info.get("xref") or info.get("digest") or tuple(round(v) for v in bbox)))
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        # Un logo o una riga decorativa non è un disegno esteso; uno sfondo a tutta pagina nemmeno.
        if area * MIN_VECTOR_AREA_FRACTION <= rect.get_area() < area * BACKGROUND_AREA_FRACTION:
            keys.append(("draw", tuple(round(v) for v in rect)))
    return keys


def pdf_pages_have_figures(document):
    """Per ogni pagina, se ha una figura vera. Come per le righe ripetute, loghi, sfondi e
    cornici che tornano su quasi tutte le pagine non contano (es. esportazioni di slide)."""
    per_page = [_figure_keys(page) for page in document]
    counts = Counter(key for keys in per_page for key in set(keys))
    total = len(per_page)
    repeated = {key for key, count in counts.items()
                if total >= REPEATED_LINE_MIN_PAGES and count >= math.ceil(total * REPEATED_LINE_FRACTION)}
    return [any(key not in repeated for key in keys) for keys in per_page]
