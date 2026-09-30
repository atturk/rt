"""Markdown → HTML sicuro per documento, anteprima e modifica, con le formule lasciate intatte.

Senza protezione CommonMark rovina il LaTeX prima che la SPA lo veda: `$a_1 * b_2$` diventa
corsivo e `\\(x\\)` perde le barre (sono escape). La regola inline qui sotto riconosce le
formule delimitate e le passa come testo semplice (escapato dal renderer), così la SPA le
trova integre in un unico nodo di testo.
"""

from markdown_it import MarkdownIt

_PAIRS = (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"))


def _dollar_end(src: str, start: int) -> int:
    """Fine (esclusa) di una formula `$...$` che apre in start, o -1. Regole come Pandoc:
    dopo il `$` di apertura niente spazio, prima di quello di chiusura niente spazio e dopo
    niente cifra; così "costa 5$ e 10$" o "$5 e $10" restano testo."""
    if start + 1 >= len(src) or src[start + 1].isspace() or src[start + 1] == "$":
        return -1
    pos = start + 1
    while True:
        pos = src.find("$", pos)
        if pos < 0 or "\n" in src[start:pos]:
            return -1
        before = src[pos - 1]
        after = src[pos + 1] if pos + 1 < len(src) else ""
        if not before.isspace() and before != "\\" and not after.isdigit():
            return pos + 1
        pos += 1


def _math_inline(state, silent: bool) -> bool:
    src, pos = state.src, state.pos
    end = -1
    for opening, closing in _PAIRS:
        if src.startswith(opening, pos):
            found = src.find(closing, pos + len(opening))
            if found > pos + len(opening):
                end = found + len(closing)
            break
    else:
        if src[pos] == "$":
            end = _dollar_end(src, pos)
    if end < 0:
        return False
    if not silent:
        token = state.push("text", "", 0)
        token.content = src[pos:end]
    state.pos = end
    return True


def markdown_parser() -> MarkdownIt:
    # html=False: l'HTML grezzo del Markdown viene escapato, quindi l'output è sicuro.
    md = MarkdownIt("commonmark", {"html": False})
    md.inline.ruler.before("escape", "rt_math", _math_inline)
    return md


def render_markdown(markdown: str) -> str:
    return markdown_parser().render(markdown)
