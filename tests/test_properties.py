"""
tests/test_properties.py
Test a proprietà (Hypothesis) sulle parti deterministiche che reggono la pipeline: invece di
pochi esempi scritti a mano, ogni regola si prova su centinaia di input generati, e un errore
viene ridotto da Hypothesis all'esempio più piccolo che lo riproduce.
"""
import os

from hypothesis import assume, given, settings, strategies as st

from rt.core.segments import insert_source_segments, make_segment_id, parse_segments_from_markdown
from rt.core.timestamp import format_timestamp, parse_interval, parse_timestamp
from rt.pipeline.anchors import locate, make_anchor

# Fino a 99:59:59: oltre, il trascritto Markdown non riconosce più il marcatore delle ore.
SECONDS = st.integers(min_value=0, max_value=99 * 3600 + 59 * 60 + 59)
# Testo di una battuta del trascritto: lettere accentate, punteggiatura, simboli e formule.
WORDS = st.text(st.characters(categories=("L", "N", "P", "Sm", "Zs"), exclude_characters="*\n\r"),
                min_size=1, max_size=60)


@given(SECONDS, st.booleans())
def test_timestamp_round_trip(seconds, hours_always):
    assert parse_timestamp(format_timestamp(seconds, hours_always)) == seconds


@given(SECONDS, st.floats(min_value=0, max_value=0.999))
def test_format_timestamp_truncates_fractions(seconds, fraction):
    assert format_timestamp(seconds + fraction) == format_timestamp(seconds)


@given(SECONDS, st.integers(min_value=1, max_value=7200))
def test_interval_round_trip(start, length):
    end = min(start + length, 99 * 3600 + 59 * 60 + 59)
    assume(end > start)
    text = f"{format_timestamp(start)} - {format_timestamp(end)}"
    assert parse_interval(text) == (start, end)


@given(st.lists(st.tuples(st.integers(min_value=0, max_value=600), WORDS.filter(str.strip)),
                min_size=1, max_size=30))
@settings(max_examples=60)
def test_markdown_transcript_keeps_every_block(tmp_path_factory, blocks):
    """Un trascritto Markdown con timestamp crescenti torna con un segmento per blocco, nello
    stesso ordine, con il testo e l'inizio di ciascuno e una fine sempre dopo l'inizio."""
    starts, start = [], 0
    for step, _ in blocks:
        start += step
        starts.append(start)
    texts = [" ".join(text.split()) for _, text in blocks]
    body = "".join(f"*{format_timestamp(s)}*\n{t}\n\n" for s, t in zip(starts, texts))
    path = os.path.join(tmp_path_factory.mktemp("md"), "trascritto grezzo.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\nmateria: PROVA\n---\n\n" + body)
    segments = parse_segments_from_markdown(path)
    assert [s.start_seconds for s in segments] == starts
    assert [s.text_raw for s in segments] == texts
    assert [s.index for s in segments] == list(range(1, len(blocks) + 1))
    assert all(s.end_seconds > s.start_seconds for s in segments)


@st.composite
def text_and_span(draw):
    text = draw(st.text(min_size=1, max_size=400))
    start = draw(st.integers(min_value=0, max_value=len(text) - 1))
    end = draw(st.integers(min_value=start + 1, max_value=len(text)))
    return text, start, end


@given(text_and_span())
def test_anchor_finds_itself_in_unchanged_text(case):
    text, start, end = case
    found = locate(make_anchor(text, start, end), text)
    assert found is not None and (found.start, found.end, found.exact) == (start, end, True)


@given(text_and_span(), st.text(max_size=80), st.text(max_size=80))
def test_anchor_survives_edits_around_the_quote(case, before, after):
    """Testo aggiunto prima e dopo (modifiche in altri punti dell'unità): la citazione si
    ritrova ancora, identica."""
    text, start, end = case
    anchor = make_anchor(text, start, end)
    edited = before + text + after
    found = locate(anchor, edited)
    assert found is not None and found.exact
    assert edited[found.start:found.end] == anchor.quote


def _segments(count, first=1):
    from rt.core.models import Segment
    return [Segment(id=make_segment_id(first + i), index=i + 1, start_seconds=i * 10,
                    end_seconds=i * 10 + 5, start_formatted=format_timestamp(i * 10),
                    end_formatted=format_timestamp(i * 10 + 5), text_raw=f"battuta {i}")
            for i in range(count)]


@given(st.integers(min_value=0, max_value=20), st.integers(min_value=1, max_value=20),
       st.data())
def test_insert_source_keeps_ids_stable_and_unique(existing_count, incoming_count, data):
    existing = _segments(existing_count)
    position = data.draw(st.integers(min_value=0, max_value=existing_count))
    merged = insert_source_segments(existing, _segments(incoming_count), "fonte-2", position)
    assert len(merged) == existing_count + incoming_count
    assert len({s.id for s in merged}) == len(merged)
    assert [s.index for s in merged] == list(range(1, len(merged) + 1))
    # i segmenti già presenti tengono il loro ID, nell'ordine di prima
    assert [s.id for s in merged if s.source_file != "fonte-2"] == [s.id for s in existing]
    assert [s.id for s in merged[position:position + incoming_count]] == \
        [s.id for s in merged if s.source_file == "fonte-2"]
