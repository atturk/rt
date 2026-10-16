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


def pdf_page_has_figures(page):
    if page.get_image_info():
        return True
    # Un piccolo logo o una riga decorativa non è un disegno esteso.
    area = page.rect.get_area()
    return any(drawing["rect"].get_area() >= area * MIN_VECTOR_AREA_FRACTION
               for drawing in page.get_drawings()) if area else False
