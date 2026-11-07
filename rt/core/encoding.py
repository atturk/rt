"""
rt.core.encoding
Gestione centralizzata e deterministica dell'encoding UTF-8 e riparazione del mojibake.
Previene e risana automaticamente qualsiasi disallineamento di codifica (es. UTF-8 decodificato
come ISO-8859-1 / Windows-1252 da endpoint HTTP o proxy come OpenRouter).
"""

import re
from typing import Any, Union


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


# Nel JSON dell'LLM "\frac" o "\beta" con una sola barra diventano i caratteri di controllo
# \f e \b seguiti da "rac", "eta". Form feed e backspace non compaiono mai in un testo vero.
_CONTROL_ESCAPES = {"\x0c": "\\f", "\x08": "\\b"}
# Tab, a capo e ritorno carrello invece sono legittimi fuori dalle formule: si riparano solo
# davanti al resto di un comando LaTeX noto.
_LATEX_AFTER_ESCAPE = re.compile(
    r"\t(?=(?:heta|au|imes|ext[a-z]*|anh?|ilde|riangle[a-z]*|frac)(?![A-Za-z]))"
    r"|\r(?=(?:ho|ight|angle|ceil|floor)(?![a-zA-Z])|m\{)"
    r"|\n(?=(?:abla|eq|otin|ot|eg|ewline|leq|geq|mid|exists|parallel|subseteq|cong|sim)(?![a-zA-Z]))"
)

MATH_REGEX = re.compile(
    r"(\$\$[\s\S]*?\$\$"
    r"|\\\[[\s\S]*?\\\]"
    r"|\\\([\s\S]*?\\\)"
    r"|(?<![\$\\\d])\$(?!\$)(?! )(?:\\.|[^\$\n])+?(?<![ \\])\$(?!\d))"
)

_CONTROL_IN_MATH = re.compile(r"([\t\x08\x0c])(?=[a-zA-Z])")
_ESC_MAP = {
    "\t": "\\t",
    "\x08": "\\b",
    "\x0c": "\\f",
}

_REPAIR_N_IN_MATH = re.compile(
    r"\n(?=(?:abla|eq|otin|ot|eg|ewline|leq|geq|mid|exists|parallel|subseteq|cong|sim)(?![a-zA-Z]))"
)
_REPAIR_R_IN_MATH = re.compile(
    r"\r(?=(?:ho|ight|angle|ceil|floor)(?![a-zA-Z])|m\{)"
)

_INVALID_MATH_COMMANDS = re.compile(r"\\(?:trm|rm|textrm)\s*\{")
_MATH_PREFIX_REPAIR = re.compile(r"(?<![a-zA-Z\\])ath(rm|bf|it|cal|bb|sf)\{")


def _repair_inside_math(content: str, is_display: bool) -> str:
    # 1. Caratteri di controllo seguiti da lettera -> con la barra
    content = _CONTROL_IN_MATH.sub(lambda m: _ESC_MAP[m.group(1)], content)
    content = _REPAIR_N_IN_MATH.sub(r"\\n", content)
    content = _REPAIR_R_IN_MATH.sub(r"\\r", content)
    # 2. Comandi non validi più comuni: \trm{, \rm{ e \textrm{ dentro una formula diventano \mathrm{
    content = _INVALID_MATH_COMMANDS.sub(r"\\mathrm{", content)
    # 3. Rimette \m davanti a athrm{, athbf{, athit{, athcal{, athbb{, athsf{ non preceduti da lettera o barra
    content = _MATH_PREFIX_REPAIR.sub(r"\\m\g<0>", content)
    # 4. Ultimo controllo: togli eventuali caratteri di controllo rimasti dentro la formula
    if is_display:
        content = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]", "", content)
    else:
        content = re.sub(r"[\x00-\x1f\x7f]", "", content)
    return content


def _repair_formula(match_str: str) -> str:
    if match_str.startswith("$$") and match_str.endswith("$$"):
        return "$$" + _repair_inside_math(match_str[2:-2], is_display=True) + "$$"
    elif match_str.startswith("\\[") and match_str.endswith("\\]"):
        return "\\[" + _repair_inside_math(match_str[2:-2], is_display=True) + "\\]"
    elif match_str.startswith("\\(") and match_str.endswith("\\)"):
        return "\\(" + _repair_inside_math(match_str[2:-2], is_display=False) + "\\)"
    elif match_str.startswith("$") and match_str.endswith("$"):
        return "$" + _repair_inside_math(match_str[1:-1], is_display=False) + "$"
    return match_str


def _repair_outside_math(text: str) -> str:
    if "\x0c" in text or "\x08" in text:
        for char, escape in _CONTROL_ESCAPES.items():
            text = text.replace(char, escape)
    if "\t" in text or "\r" in text or "\n" in text:
        text = _LATEX_AFTER_ESCAPE.sub(lambda m: {"\t": "\\t", "\r": "\\r", "\n": "\\n"}[m.group(0)], text)
    return text


def repair_latex_escapes(text: str) -> str:
    """Rimette la barra ai comandi LaTeX mangiati dagli escape JSON (\\frac, \\beta, \\theta...)."""
    if not text:
        return text
    parts = []
    last_end = 0
    for match in MATH_REGEX.finditer(text):
        start, end = match.span()
        if start > last_end:
            parts.append(_repair_outside_math(text[last_end:start]))
        parts.append(_repair_formula(match.group(0)))
        last_end = end
    if last_end < len(text):
        parts.append(_repair_outside_math(text[last_end:]))
    return "".join(parts)


def sanitize_object_encoding(obj: Any, *, repair_latex: bool = False) -> Any:
    """
    Sanitizza ricorsivamente stringhe in dizionari, liste o oggetti arbitrari.
    Particolarmente utile prima o dopo il caricamento di JSON.
    """
    if isinstance(obj, str):
        text = fix_mojibake(obj)
        if repair_latex:
            text = repair_latex_escapes(text)
        return text
    elif isinstance(obj, list):
        return [sanitize_object_encoding(x, repair_latex=repair_latex) for x in obj]
    elif isinstance(obj, dict):
        return {k: sanitize_object_encoding(v, repair_latex=repair_latex) for k, v in obj.items()}
    return obj


def sanitize_llm_output(obj: Any) -> Any:
    """Sanitizza l'output proveniente dal modello LLM (mojibake + repair_latex_escapes)."""
    return sanitize_object_encoding(obj, repair_latex=True)
