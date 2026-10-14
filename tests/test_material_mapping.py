import pytest

from rt.core.models import Outline, OutlineMacro, OutlineUnit, Segment, SegmentsData
from rt.pipeline.material_mapping import (
    ITALIAN_STOPWORDS,
    build_subunit_corpus,
    find_candidate_subunits_for_page,
    stem_italian,
    tokenize_text,
)


def test_stem_italian_reduces_forms():
    assert stem_italian("coagulazione") == "coagul"
    assert stem_italian("coagulare") == "coagul"
    assert stem_italian("coagulano") == "coagul"
    assert stem_italian("trombomodulina") == "trombomodulin"
    assert stem_italian("trombomoduline") == "trombomodulin"
    assert stem_italian("paziente") == "pazient"
    assert stem_italian("pazienti") == "pazient"


def test_tokenize_text_filters_stopwords_and_fillers():
    text = "Quindi diciamo cioè la trombomodulina è fondamentale per il paziente"
    tokens = tokenize_text(text)
    # Speech fillers and stopwords must be filtered out
    assert "quindi" not in tokens
    assert "diciamo" not in tokens
    assert "cioe" not in tokens and "cioè" not in tokens
    assert "la" not in tokens and "il" not in tokens and "per" not in tokens
    # Content words remain stemmed
    assert "trombomodulin" in tokens
    assert "fondamental" in tokens
    assert "pazient" in tokens


def test_candidates_selection_tfidf_ranking():
    # Setup an outline with 3 units
    outline = Outline(
        lesson_title="Ematologia",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Emostasi",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Cascata della coagulazione",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000002",
                    ),
                    OutlineUnit(
                        id="1.2",
                        title="Piastrine e vasi",
                        start_segment_id="seg_000003",
                        end_segment_id="seg_000004",
                    ),
                    OutlineUnit(
                        id="1.3",
                        title="Fibrinolisi e anticoagulanti",
                        start_segment_id="seg_000005",
                        end_segment_id="seg_000006",
                    ),
                ],
            )
        ],
    )
    segments = [
        Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=10, start_formatted="00:00", end_formatted="00:10", text_raw="La trombomodulina si lega alla trombina attivando la proteina C."),
        Segment(id="seg_000002", index=2, start_seconds=10, end_seconds=20, start_formatted="00:10", end_formatted="00:20", text_raw="La coagulazione prosegue con la fibrina nel paziente."),
        Segment(id="seg_000003", index=3, start_seconds=20, end_seconds=30, start_formatted="00:20", end_formatted="00:30", text_raw="Le piastrine formano il tappo emostatico primario nel paziente."),
        Segment(id="seg_000004", index=4, start_seconds=30, end_seconds=40, start_formatted="00:30", end_formatted="00:40", text_raw="L'endotelio vascolare rilascia ossido nitrico nel paziente."),
        Segment(id="seg_000005", index=5, start_seconds=40, end_seconds=50, start_formatted="00:40", end_formatted="00:50", text_raw="La plasmina degrada il reticolo di fibrina anticoagulante nel paziente."),
        Segment(id="seg_000006", index=6, start_seconds=50, end_seconds=60, start_formatted="00:50", end_formatted="01:00", text_raw="T-PA converte il plasminogeno in plasmina attiva."),
    ]
    segments_data = SegmentsData(segments=segments)

    corpus, idf = build_subunit_corpus(outline, segments_data)
    assert len(corpus) == 3

    # 'paziente' appears in all 3 units -> lower IDF
    # 'trombomodulina' appears in only unit 1.1 -> higher IDF
    stem_paziente = stem_italian("paziente")
    stem_trombo = stem_italian("trombomodulina")
    assert idf[stem_trombo] > idf[stem_paziente]

    # Page discussing specifically trombomodulina and protein C
    page_text = "Slide 5: Il ruolo della trombomodulina e attivazione della proteina C nella via anticoagulante naturale."
    candidates = find_candidate_subunits_for_page(page_text, corpus, idf)

    assert len(candidates) >= 1
    assert candidates[0].unit_id == "1.1"


def test_candidates_empty_for_useless_text_or_stopwords():
    outline = Outline(
        lesson_title="Test",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="M1",
                units=[
                    OutlineUnit(id="1.1", title="U1", start_segment_id="seg_000001", end_segment_id="seg_000001")
                ],
            )
        ],
    )
    segments = [Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=1, start_formatted="00:00", end_formatted="00:01", text_raw="Contenuto didattico utile.")]
    corpus, idf = build_subunit_corpus(outline, SegmentsData(segments=segments))

    # Empty text
    assert find_candidate_subunits_for_page("", corpus, idf) == []
    # Only numbers / punctuation
    assert find_candidate_subunits_for_page("12345 67890 !?", corpus, idf) == []
    # Only speech fillers / stopwords
    assert find_candidate_subunits_for_page("Quindi diciamo cioè allora insomma.", corpus, idf) == []
    # Unrelated foreign text with zero overlap
    assert find_candidate_subunits_for_page("Quantum chromodynamics gluon plasma hadronization", corpus, idf) == []


def test_candidates_cap_at_five_and_half_max_threshold():
    # Create 8 units, where several match with varying degrees
    units = [
        OutlineUnit(id=f"1.{i}", title=f"Sezione {i}", start_segment_id=f"seg_00000{i}", end_segment_id=f"seg_00000{i}")
        for i in range(1, 9)
    ]
    outline = Outline(
        lesson_title="Test",
        macro_sections=[OutlineMacro(id="1", title="Macro", units=units)],
    )
    # Unit 1.1 has 5 occurrences of keyword, 1.2 has 4, 1.3 has 3, etc.
    segments = [
        Segment(id=f"seg_00000{i}", index=i, start_seconds=i, end_seconds=i+1,
                start_formatted=f"00:0{i}", end_formatted=f"00:0{i+1}",
                text_raw=" ".join(["mitocondrio"] * max(1, 8 - i) + [f"extra_{i}"]))
        for i in range(1, 9)
    ]
    corpus, idf = build_subunit_corpus(outline, SegmentsData(segments=segments))

    page_text = "Struttura e funzione del mitocondrio nella respirazione cellulare."
    candidates = find_candidate_subunits_for_page(page_text, corpus, idf)

    # Must be at most 5
    assert len(candidates) <= 5
    # Best score is unit 1.1
    assert candidates[0].unit_id == "1.1"
    # All candidate scores must be >= 0.5 * best_score
    best_score = candidates[0].score
    for c in candidates:
        assert c.score >= 0.5 * best_score
