"""Ritrovamento deterministico di citazioni, sempre nel solo testo passato."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from rt.core.models import Anchor

CONTEXT_SIZE = 40
FUZZY_THRESHOLD = 0.82


@dataclass(frozen=True)
class Located:
    start: int
    end: int
    exact: bool


def make_anchor(text: str, start: int, end: int) -> Anchor:
    if not 0 <= start < end <= len(text):
        raise ValueError("Tratto vuoto o fuori dal testo")
    return Anchor(quote=text[start:end], prefix=text[max(0, start-CONTEXT_SIZE):start],
                  suffix=text[end:end+CONTEXT_SIZE], start=start, end=end)


def _occurrences(text: str, quote: str):
    if quote:
        start = text.find(quote)
        while start >= 0:
            yield start, start + len(quote)
            start = text.find(quote, start + 1)


def _normalized(text: str):
    """Normalizza gli spazi conservando i limiti di ciascun carattere originale."""
    chars, starts, ends = [], [], []
    for match in re.finditer(r"\s+|\S", text):
        chars.append(" " if match.group().isspace() else match.group())
        starts.append(match.start())
        ends.append(match.end())
    return "".join(chars), starts, ends


def _spaced(text: str, quote: str):
    normalized, starts, ends = _normalized(text)
    needle = _normalized(quote)[0].strip()
    for start, end in _occurrences(normalized, needle):
        yield starts[start], ends[end-1]


def find_quote(text: str, quote: str) -> Located | None:
    for start, end in _occurrences(text, quote):
        return Located(start, end, True)
    for start, end in _spaced(text, quote):
        return Located(start, end, False)
    return None


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _context(anchor: Anchor, text: str, start: int, end: int) -> float:
    scores = []
    if anchor.prefix:
        near = _similar(anchor.prefix[-12:], text[max(0, start-min(12, len(anchor.prefix))):start])
        whole = _similar(anchor.prefix, text[max(0, start-len(anchor.prefix)):start])
        scores.append((2 * near + whole) / 3)
    if anchor.suffix:
        near = _similar(anchor.suffix[:12], text[end:end+min(12, len(anchor.suffix))])
        whole = _similar(anchor.suffix, text[end:end+len(anchor.suffix)])
        scores.append((2 * near + whole) / 3)
    return sum(scores) / len(scores) if scores else 0.0


def _best(anchor: Anchor, text: str, spans, exact: bool):
    spans = list(spans)
    if not spans:
        return None
    start, end = max(spans, key=lambda span: (
        _context(anchor, text, *span), -abs(span[0]-anchor.start), -span[0]))
    return Located(start, end, exact)


def locate(anchor: Anchor, text: str) -> Located | None:
    if not anchor.quote:
        return None
    found = _best(anchor, text, _occurrences(text, anchor.quote), True)
    if found:
        return found
    found = _best(anchor, text, _spaced(text, anchor.quote), False)
    if found:
        return found

    # La finestra è delimitata dal contesto, anche se il passaggio si è spostato.
    # Senza almeno un contesto ritrovato non si indovina una sostituzione.
    prefixes = list(_occurrences(text, anchor.prefix)) if anchor.prefix else []
    suffixes = list(_occurrences(text, anchor.suffix)) if anchor.suffix else []
    candidates = set()
    size = len(anchor.quote)
    if not anchor.prefix and not anchor.suffix and text:
        candidates.add((0, len(text)))
    for _, start in prefixes:
        for end, _ in suffixes:
            if start < end and size * 0.5 <= end-start <= size * 1.5:
                candidates.add((start, end))
        if not anchor.suffix and size * 0.5 <= len(text)-start <= size * 1.5:
            candidates.add((start, len(text)))
    if not anchor.prefix:
        for end, _ in suffixes:
            if size * 0.5 <= end <= size * 1.5:
                candidates.add((0, end))
    candidates = [span for span in candidates
                  if _similar(anchor.quote, text[span[0]:span[1]]) >= FUZZY_THRESHOLD]
    return _best(anchor, text, candidates, False)
