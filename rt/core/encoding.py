"""
rt.core.encoding
Gestione centralizzata e deterministica dell'encoding UTF-8 e riparazione del mojibake.
Previene e risana automaticamente qualsiasi disallineamento di codifica (es. UTF-8 decodificato
come ISO-8859-1 / Windows-1252 da endpoint HTTP o proxy come OpenRouter).
"""

import re
from typing import Any, Dict, List, Union


# Sequenze UTF-8 tipiche a 2 byte (U+00C2-U+00DF seguito da continuation byte U+0080-U+00BF)
# e a 3 byte (U+00E0-U+00EF seguito da due continuation byte U+0080-U+00BF)
MOJIBAKE_REGEX = re.compile(
    r"(?:[\u00C2-\u00DF][\u0080-\u00BF]|[\u00E0-\u00EF][\u0080-\u00BF]{2})"
)

# Mappatura esplicita per simboli frequenti Windows-1252 mojibake
CP1252_COMMON_FIXES = {
    "â€™": "’",
    "â€˜": "‘",
    "â€œ": "“",
    "â€": "”",
    "â€“": "–",
    "â€”": "—",
    "â€¦": "…",
    "Â ": " ",
    "Â": "",
}


def fix_mojibake(text: str) -> str:
    """
    Rileva e corregge sequenze UTF-8 decodificate erroneamente come ISO-8859-1 o Windows-1252.
    Esempi:
      "piÃ¹" -> "più"
      "Ã¨"   -> "è"
      "attivitÃ\xa0" -> "attività"
    Non altera testo già correttamente codificato né emoji/simboli matematici.
    """
    if not text or not isinstance(text, str):
        return text

    # Se non sono presenti caratteri sentinella tipici del mojibake UTF-8 -> Latin-1 / Cp1252, ritorna subito
    if not any(c in text for c in ("Ã", "â", "Â")):
        return text

    # Correzioni preliminari per sequenze CP1252 note
    for bad, good in CP1252_COMMON_FIXES.items():
        if bad in text:
            text = text.replace(bad, good)

    if not any(c in text for c in ("Ã", "â", "Â")):
        return text

    # Tentativo 1: l'intera stringa è mojibake puro (es. latin-1 -> utf-8)
    try:
        candidate = text.encode("latin-1").decode("utf-8")
        return candidate
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # Tentativo 2: sostituzione selettiva tramite regex per testo misto
    def _replace_chunk(match: re.Match) -> str:
        chunk = match.group(0)
        try:
            return chunk.encode("latin-1").decode("utf-8")
        except Exception:
            return chunk

    return MOJIBAKE_REGEX.sub(_replace_chunk, text)


def sanitize_text(text: Union[str, None]) -> str:
    """Restituisce una stringa garantita senza mojibake, gestendo i None in sicurezza."""
    if text is None:
        return ""
    return fix_mojibake(str(text))


def sanitize_object_encoding(obj: Any) -> Any:
    """
    Sanitizza ricorsivamente stringhe in dizionari, liste o oggetti arbitrari.
    Particolarmente utile prima o dopo il caricamento di JSON dall'LLM.
    """
    if isinstance(obj, str):
        return fix_mojibake(obj)
    elif isinstance(obj, list):
        return [sanitize_object_encoding(x) for x in obj]
    elif isinstance(obj, dict):
        return {k: sanitize_object_encoding(v) for k, v in obj.items()}
    return obj
