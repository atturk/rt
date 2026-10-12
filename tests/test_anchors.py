import pytest
from rt.core.models import Anchor
from rt.pipeline.anchors import make_anchor, locate, find_quote, FUZZY_THRESHOLD


def test_repeated_quote_uses_context_before_distance():
    text = 'Primo: valore 7.4.\nSecondo: valore 7.4.'
    start = text.rindex('valore')
    anchor = make_anchor(text, start, start+len('valore 7.4'))
    moved = 'Secondo: valore 7.4.\nPrimo: valore 7.4.'
    result = locate(anchor, moved)
    assert result and moved[result.start:result.end] == 'valore 7.4'
    assert result.start == moved.index('valore')
    assert result.exact


def test_repeated_quote_ties_use_distance():
    anchor = Anchor(quote='7.4', start=8, end=11)
    assert locate(anchor, '7.4     7.4').start == 8


def test_decimal_span_does_not_expand():
    result = find_quote('Il pH è 7.4 e resta stabile.', '7.4')
    assert (result.start, result.end, result.exact) == (8, 11, True)


def test_moved_text():
    text = 'Il valore è stabile. Altra frase.'
    anchor = make_anchor(text, 0, 19)
    result = locate(anchor, 'Introduzione. '+text)
    assert result.start == len('Introduzione. ')
    assert result.end == result.start+19


def test_whitespace_mapping():
    text = 'Prima. Il valore\n  è\t7.4. Dopo.'
    result = find_quote(text, 'Il valore è 7.4')
    assert text[result.start:result.end] == 'Il valore\n  è\t7.4'
    assert not result.exact
    anchor = make_anchor('Prima. Il valore è 7.4. Dopo.', 7, 22)
    assert locate(anchor, text) == result


def test_partially_rewritten_with_context():
    text = 'Prima. Il valore normale è stabile. Dopo.'
    anchor = make_anchor(text, 7, text.index('. Dopo.'))
    updated = text.replace('normale', 'normali')
    result = locate(anchor, updated)
    assert result and not result.exact
    assert updated[result.start:result.end] == 'Il valore normali è stabile'


def test_disappeared_and_below_threshold():
    text = 'Prima. Il valore normale è stabile. Dopo.'
    anchor = make_anchor(text, 7, text.index('. Dopo.'))
    assert FUZZY_THRESHOLD == 0.82
    assert locate(anchor, 'Prima. Una cosa completamente diversa. Dopo.') is None
    assert locate(anchor, 'Prima. Dopo.') is None
    assert locate(anchor, '') is None
    assert find_quote(text, '') is None


@pytest.mark.parametrize('start,end', [(-1, 2), (1, 1), (1, 5), (2, 1)])
def test_invalid_span(start, end):
    with pytest.raises(ValueError):
        make_anchor('abc', start, end)


def test_fuzzy_threshold_and_unit_boundary():
    quote = 'Il pH normale del sangue è 7.4 e resta stabile.'
    anchor = make_anchor(quote, 0, len(quote))
    updated = quote.replace('normale', 'medio')
    result = locate(anchor, updated)
    assert result and (result.start, result.end) == (0, len(updated))
    assert not result.exact
    assert locate(anchor, 'Una spiegazione totalmente diversa.') is None


def test_fuzzy_moved_between_contexts():
    quote = 'Il pH normale del sangue è 7.4 e resta stabile'
    text = 'Contesto prima. ' + quote + '. Contesto dopo.'
    anchor = make_anchor(text, 16, 16+len(quote))
    updated = 'Nuova introduzione. ' + text.replace('normale', 'medio')
    result = locate(anchor, updated)
    assert result and updated[result.start:result.end] == quote.replace('normale', 'medio')
