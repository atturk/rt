"""Le formule arrivano alla SPA intatte: niente corsivo dentro $...$ e barre di \\( \\) conservate."""
import pytest

from rt.core.markdown_render import render_markdown


@pytest.mark.parametrize("source, expected", [
    ("$a_1 * b_2 * c$", "<p>$a_1 * b_2 * c$</p>"),
    (r"\(x_1 * y_2\)", r"<p>\(x_1 * y_2\)</p>"),
    (r"\[a_b * c_d\]", r"<p>\[a_b * c_d\]</p>"),
    ("$$\\frac{a_1}{b_2} * c$$", "<p>$$\\frac{a_1}{b_2} * c$$</p>"),
    ("$x<y$", "<p>$x&lt;y$</p>"),
])
def test_math_is_left_untouched(source, expected):
    assert render_markdown(source).strip() == expected


@pytest.mark.parametrize("source, expected", [
    ("costa 5$ e _10$_", "<p>costa 5$ e <em>10$</em></p>"),
    ("da $5 a $10 *circa*", "<p>da $5 a $10 <em>circa</em></p>"),
    (r"prezzo \$3", "<p>prezzo $3</p>"),
])
def test_prices_are_not_math_and_markdown_still_works(source, expected):
    assert render_markdown(source).strip() == expected


def test_raw_html_stays_escaped():
    assert "<script>" not in render_markdown("<script>alert(1)</script> $x$")
