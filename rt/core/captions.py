"""Helper unico per didascalie e alt_text delle pagine dei materiali."""
import os
import re
from typing import Any, Dict, Optional

ALT_SEPARATOR = " — "
MAX_CAPTION_LENGTH = 90
_LEGACY_PAGE_SUFFIX = re.compile(r",\s*(?:pagina|pag\.|p\.)\s*\d+\s*$", re.IGNORECASE)


def clean_caption(text: Optional[str]) -> Optional[str]:
    """Pulisce il titolo di una slide/immagine per usarlo nell'alt Markdown."""
    if text is None:
        return None
    cleaned = str(text)
    cleaned = cleaned.replace("[", "").replace("]", "").replace("\\", " ")
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s*—\s*", " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or cleaned.casefold() == "n/a":
        return None
    if len(cleaned) > MAX_CAPTION_LENGTH:
        cleaned = cleaned[: MAX_CAPTION_LENGTH - 1].rstrip() + "…"
    return cleaned


def page_alt(
    source_file: str,
    page_number: int,
    titolo: Optional[str] = None,
    single_page: bool = False,
) -> str:
    """Costruisce l'alt Markdown canonico: '<titolo> — <file>, pagina N' (o senza pagina per foto singole)."""
    name = os.path.basename(str(source_file or ""))
    ref = name if single_page else f"{name}, pagina {page_number}"
    caption = clean_caption(titolo)
    if caption:
        return f"{caption}{ALT_SEPARATOR}{ref}"
    return ref


def caption_from_description(desc: Optional[Dict[str, Any]]) -> Optional[str]:
    """Estrae una didascalia pulita da un dizionario di descrizione immagine, se presente."""
    if not desc:
        return None
    title = clean_caption(desc.get("slide_title"))
    if title:
        return title
    alt = str(desc.get("alt_text") or "")
    if ALT_SEPARATOR in alt:
        return clean_caption(alt.rsplit(ALT_SEPARATOR, 1)[0])
    if _LEGACY_PAGE_SUFFIX.search(alt):
        return None
    return clean_caption(alt)
