"""
rt.telegram.lesson_query
Parsing e risoluzione delle query di ricerca lezioni (/recall <query>).
"""
from typing import List, Tuple
from rt.core.lesson_index import LessonEntry, filter_by_date, filter_by_keyword
from rt.pipeline.setup import parse_flexible_date

MAX_INLINE_DISAMBIGUATION = 4


def resolve_recall_query(entries: List[LessonEntry], raw_query: str) -> Tuple[str, List[LessonEntry]]:
    """Ritorna (mode, matches). mode in {'date_and_keyword', 'date', 'keyword'}."""
    raw_query = raw_query.strip()
    if " - " in raw_query:
        date_part, _, keyword_part = raw_query.partition(" - ")
        date_part = date_part.strip()
        if date_part:
            try:
                iso_date = parse_flexible_date(date_part)
                matches = filter_by_keyword(filter_by_date(entries, iso_date), keyword_part)
                return "date_and_keyword", matches
            except ValueError:
                pass
        return "keyword", filter_by_keyword(entries, raw_query)

    try:
        iso_date = parse_flexible_date(raw_query)
        return "date", filter_by_date(entries, iso_date)
    except ValueError:
        return "keyword", filter_by_keyword(entries, raw_query)
