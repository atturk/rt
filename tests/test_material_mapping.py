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


def test_classify_material_page_mock_and_macro_aggregation(tmp_path, monkeypatch):
    from rt.core.sources import Source
    from rt.pipeline.material_mapping import (
        CandidateSubunit,
        classify_material_page,
        material_context_for_unit,
        _write_json,
        STATE_FILE,
    )

    lesson_dir = str(tmp_path)
    source = Source(id="src_mat1", tipo="materiale", file="sources/src_mat1/doc.pdf",
                    impronta="abc123hash", aggiunta_il="2026-10-14T00:00:00Z", ordine=1)
    page = {"numero": 3, "testo": "Contenuto pagina 3", "immagini": []}

    candidates = [
        CandidateSubunit(unit_id="1.1", macro_id="1", title="Titolo 1.1", transcript="testo", score=0.8),
        CandidateSubunit(unit_id="1.2", macro_id="1", title="Titolo 1.2", transcript="testo", score=0.7),
        CandidateSubunit(unit_id="1.3", macro_id="1", title="Titolo 1.3", transcript="testo", score=0.6),
        CandidateSubunit(unit_id="2.1", macro_id="2", title="Titolo 2.1", transcript="testo", score=0.5),
    ]

    # 1. Deterministic mock: first candidate gets 0.9, others 0.1
    units, macros = classify_material_page(page, candidates, source, lesson_dir, {}, mock=True)
    assert units == ["1.1"]
    assert macros == []

    # 2. Macro aggregation when >= 3 subunits of same macro pass
    cached_3_passed = {
        f"{source.id}:{page['numero']}": {
            "key": "some_key",
            "probabilities": {
                "didactic_content": 0.95,
                "unit_1_1": 0.85,
                "unit_1_2": 0.90,
                "unit_1_3": 0.82,
                "unit_2_1": 0.20,
            }
        }
    }
    # When 3 pass in macro 1: aggregates to macro "1"
    monkeypatch.setattr("rt.services.enrichment_service.digest", lambda *a: "some_key")
    units, macros = classify_material_page(page, candidates, source, lesson_dir, cached_3_passed, mock=False)
    assert units == []
    assert macros == ["1"]

    # AR4e: con due approvate vince una sola sottounità, quella più probabile.
    cached_2_passed = {
        f"{source.id}:{page['numero']}": {
            "key": "some_key",
            "probabilities": {
                "didactic_content": 0.95,
                "unit_1_1": 0.85,
                "unit_1_2": 0.90,
                "unit_1_3": 0.50,
                "unit_2_1": 0.85,
            }
        }
    }
    units, macros = classify_material_page(page, candidates, source, lesson_dir, cached_2_passed, mock=False)
    assert units == ["1.2"]
    assert macros == []


def test_classify_material_page_classifier_off_or_error(tmp_path, monkeypatch):
    from rt.core.sources import Source
    from rt.pipeline.material_mapping import CandidateSubunit, classify_material_page

    lesson_dir = str(tmp_path)
    source = Source(id="src_mat1", tipo="materiale", file="sources/src_mat1/doc.pdf",
                    impronta="abc123hash", aggiunta_il="2026-10-14T00:00:00Z", ordine=1)
    page = {"numero": 1, "testo": "Testo", "immagini": []}
    candidates = [CandidateSubunit(unit_id="1.1", macro_id="1", title="Titolo", transcript="testo", score=0.8)]

    # When classifier is off
    from rt.core.config import ClassifierJob
    monkeypatch.setattr("rt.core.config.classifier_job",
                        lambda cfg, name: ClassifierJob(mode="off", model="m", credential="c", timeout_seconds=10))
    units, macros = classify_material_page(page, candidates, source, lesson_dir, {})
    assert units == []
    assert macros == []

    # When classifier call fails with an error: graceful fallback, no error thrown
    monkeypatch.setattr("rt.core.config.classifier_job",
                        lambda cfg, name: ClassifierJob(mode="manual", model="m", credential="c", timeout_seconds=10))
    def mock_decision_error(*args, **kwargs):
        raise RuntimeError("Network timeout or LLM failure")
    monkeypatch.setattr("rt.services.enrichment_service.decision", mock_decision_error)
    units, macros = classify_material_page(page, candidates, source, lesson_dir, {})
    assert units == []
    assert macros == []


def test_material_context_for_unit(tmp_path):
    from rt.pipeline.material_mapping import material_context_for_unit, _write_json, STATE_FILE
    lesson_dir = str(tmp_path)

    state = {
        "pages_by_unit": {
            "1.1": [
                {"source_id": "src_1", "source_file": "slide.pdf", "page": 4, "text": "Testo pagina 4"}
            ]
        },
        "pages_by_macro": {
            "1": [
                {"source_id": "src_1", "source_file": "slide.pdf", "page": 1, "text": "Testo panoramico pagina 1"}
            ]
        }
    }
    _write_json(lesson_dir, STATE_FILE, state)

    # Unit 1.1 under macro 1 gets both macro 1 and unit 1.1 pages
    context_1_1 = material_context_for_unit(lesson_dir, "1.1", "1")
    assert "pagina 1" in context_1_1
    assert "pagina 4" in context_1_1
    assert "Testo panoramico pagina 1" in context_1_1
    assert "Testo pagina 4" in context_1_1

    # Unit 1.2 under macro 1 gets macro 1 page, but NOT unit 1.1 page
    context_1_2 = material_context_for_unit(lesson_dir, "1.2", "1")
    assert "pagina 1" in context_1_2
    assert "pagina 4" not in context_1_2

    # Unit 2.1 under macro 2 gets neither
    assert material_context_for_unit(lesson_dir, "2.1", "2") == ""


# 4.3.4b2: pagine delle fonti lette come descrizione (default) o come immagine.

def _image_reader(monkeypatch, reader="image", images_mode=None):
    import rt.core.config
    base = rt.core.config.load_config()
    classifier = base.classifier.model_copy(update={"material_pages_reader": reader})
    if images_mode:
        jobs = dict(classifier.jobs)
        jobs["images"] = jobs["images"].model_copy(update={"mode": images_mode})
        classifier = classifier.model_copy(update={"jobs": jobs})
    cfg = base.model_copy(update={"classifier": classifier})
    monkeypatch.setattr(rt.core.config, "load_config", lambda config_path=None: cfg)


def _material_lesson(tmp_path, monkeypatch, pages):
    """Una lezione con una fonte di contesto (né guida né Integra) e le pagine date."""
    from rt.core.sources import Source
    lesson = tmp_path / "lezione"
    lesson.mkdir()
    (lesson / "info.yaml").write_text("titolo: Prova\n", encoding="utf-8")
    image = tmp_path / "pagina.png"
    image.write_bytes(b"\x89PNG pagina con figure")
    source = Source(id="src1", tipo="materiale", file="slide.pdf", impronta="abc", aggiunta_il="2026-10-01",
                    ordine=1, estrai="immagini", uso="contesto")
    monkeypatch.setattr("rt.core.sources.load_sources", lambda lesson_dir, *a, **k: [source])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda lesson_dir: {})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: pages)
    monkeypatch.setattr("rt.pipeline.material_mapping.page_image_path", lambda impronta, rel: str(image))
    calls = {"text": []}

    def by_text(page, *a, **k):
        calls["text"].append(page["numero"])
        return ["1.2"], []
    monkeypatch.setattr("rt.pipeline.material_mapping.place_page_in_outline", by_text)
    outline = Outline(lesson_title="Prova", macro_sections=[OutlineMacro(id="1", title="Uno", units=[
        OutlineUnit(id="1.1", title="Uno uno", start_segment_id="seg_000001", end_segment_id="seg_000001"),
        OutlineUnit(id="1.2", title="Uno due", start_segment_id="seg_000001", end_segment_id="seg_000001")])])
    return str(lesson), outline, calls, image.read_bytes()


def _page(numero=1, figures=True):
    return {"numero": numero, "testo": f"Testo pagina {numero}\nDescrizione della figura",
            "mapping_text": "Descrizione della figura", "has_figures": figures,
            "immagini": [f"p{numero}.png"], "mapping_skip": False}


def _decide(monkeypatch, result=None, error=None):
    seen = []

    def fake(lesson_dir, outline, h, data, page_text, cached, *, mock=False, ctx=None, lesson_units=None):
        seen.append((data, page_text))
        if error:
            raise error
        return result
    monkeypatch.setattr("rt.pipeline.image_decision.decide_image", fake)
    return seen


def test_material_pages_default_reads_description(tmp_path, monkeypatch):
    from rt.pipeline.material_mapping import assign_material_pages
    lesson, outline, calls, _ = _material_lesson(tmp_path, monkeypatch, [_page()])
    seen = _decide(monkeypatch, (["1.1"], [], "contenuto"))
    state = assign_material_pages(lesson, outline, mock=True)
    assert calls["text"] == [1] and seen == []
    assert [p["page"] for p in state["pages_by_unit"]["1.2"]] == [1]


def test_material_pages_image_reader_uses_decision_model(tmp_path, monkeypatch):
    from rt.pipeline.add_images import load_image_descriptions
    from rt.pipeline.image_decision import uses_image_for_material_pages
    from rt.pipeline.material_mapping import assign_material_pages
    _image_reader(monkeypatch)
    assert uses_image_for_material_pages()
    lesson, outline, calls, data = _material_lesson(tmp_path, monkeypatch, [_page()])
    seen = _decide(monkeypatch, (["1.1"], [], "contenuto"))
    state = assign_material_pages(lesson, outline, mock=True)
    assert seen == [(data, "Testo pagina 1\nDescrizione della figura")]
    assert calls["text"] == []
    assert [p["page"] for p in state["pages_by_unit"]["1.1"]] == [1]
    assert "1.2" not in state["pages_by_unit"]
    assert len(state["units"]["1.1"]) == 1
    assert [d["ruolo"] for d in load_image_descriptions(lesson).values()] == ["contenuto"]


def test_material_pages_image_reader_off_when_images_job_off(monkeypatch):
    from rt.pipeline.image_decision import uses_image_for_material_pages
    _image_reader(monkeypatch, images_mode="off")
    assert not uses_image_for_material_pages()


def test_material_pages_image_reader_not_content_is_not_placed(tmp_path, monkeypatch):
    from rt.pipeline.material_mapping import assign_material_pages
    _image_reader(monkeypatch)
    lesson, outline, calls, _ = _material_lesson(tmp_path, monkeypatch, [_page()])
    _decide(monkeypatch, (["1.1"], [], "introduttiva"))
    state = assign_material_pages(lesson, outline, mock=True)
    assert calls["text"] == []
    assert state["pages_by_unit"] == {} and state["pages_by_macro"] == {}
    assert state["units"] == {}


def test_material_pages_image_reader_error_falls_back_to_text(tmp_path, monkeypatch):
    from rt.pipeline.material_mapping import assign_material_pages
    _image_reader(monkeypatch)
    lesson, outline, calls, _ = _material_lesson(tmp_path, monkeypatch, [_page()])
    seen = _decide(monkeypatch, error=RuntimeError("modello giù"))
    state = assign_material_pages(lesson, outline, mock=True)
    assert len(seen) == 1 and calls["text"] == [1]
    assert [p["page"] for p in state["pages_by_unit"]["1.2"]] == [1]


def test_material_pages_without_figures_always_use_text(tmp_path, monkeypatch):
    from rt.pipeline.material_mapping import assign_material_pages
    _image_reader(monkeypatch)
    lesson, outline, calls, _ = _material_lesson(tmp_path, monkeypatch, [_page(1, figures=False), _page(2)])
    seen = _decide(monkeypatch, (["1.1"], [], "contenuto"))
    state = assign_material_pages(lesson, outline, mock=True)
    assert calls["text"] == [1] and len(seen) == 1
    assert [p["page"] for p in state["pages_by_unit"]["1.2"]] == [1]
    assert [p["page"] for p in state["pages_by_unit"]["1.1"]] == [2]


def _setup_cached_classification(monkeypatch, source, page_probs):
    from types import SimpleNamespace
    from rt.core.config import ClassifierJob
    from rt.llm.jev_client import JevNoulAnswer

    monkeypatch.setattr(
        "rt.core.config.classifier_job",
        lambda cfg, name: ClassifierJob(mode="manual", model="m", credential="c", timeout_seconds=10, threshold=0.7),
    )
    monkeypatch.setattr("rt.llm.client.LLMClient", lambda **k: SimpleNamespace(force_mock=False))

    def fake_decision(state, questions, **kwargs):
        unit_id = kwargs.get("unit_id", "")
        page_num = int(unit_id.rsplit(":", 1)[-1]) if ":" in unit_id else 1
        probs = page_probs[page_num]
        return SimpleNamespace(answers={k: JevNoulAnswer(noul=probs.get(k, 0.0)) for k in questions})

    monkeypatch.setattr("rt.services.enrichment_service.decision", fake_decision)


def test_classify_thresholds_didactic_off_topic_and_logging(tmp_path, monkeypatch, capsys):
    from rt.core.sources import Source
    from rt.pipeline.material_mapping import CandidateSubunit, classify_material_page

    lesson_dir = str(tmp_path)
    source = Source(
        id="src1", tipo="materiale", file="sources/src1/patologia.pdf",
        impronta="h1", aggiunta_il="2026-11-16T00:00:00Z", ordine=1,
    )
    candidates = [
        CandidateSubunit(unit_id="1.1", macro_id="1", title="Ipossia", transcript="ipossia cellulare", score=0.9),
        CandidateSubunit(unit_id="1.2", macro_id="1", title="Necrosi", transcript="necrosi tissutale", score=0.7),
        CandidateSubunit(unit_id="1.3", macro_id="1", title="Apoptosi", transcript="apoptosi programmata", score=0.6),
        CandidateSubunit(unit_id="2.1", macro_id="2", title="Infiammazione", transcript="infiammazione acuta", score=0.5),
    ]
    _setup_cached_classification(monkeypatch, source, {
        # 1. didactic_content < 0.85 (0.78) -> introduttiva
        1: {"didactic_content": 0.78, "unit_1_1": 0.85, "unit_1_2": 0.1, "unit_1_3": 0.1, "unit_2_1": 0.1},
        # 2. didactic_content >= 0.85, migliore < 0.2 -> fuori tema
        2: {"didactic_content": 0.92, "unit_1_1": 0.19, "unit_1_2": 0.1, "unit_1_3": 0.05, "unit_2_1": 0.03},
        # 3. didactic_content >= 0.85, migliore = 0.2 (>= 0.2, < 0.7) -> non collocata sotto macro 1
        3: {"didactic_content": 0.85, "unit_1_1": 0.20, "unit_1_2": 0.1, "unit_1_3": 0.1, "unit_2_1": 0.1},
        # 4. collocata in sottounità 1.1
        4: {"didactic_content": 0.95, "unit_1_1": 0.75, "unit_1_2": 0.2, "unit_1_3": 0.1, "unit_2_1": 0.1},
        # 5. collocata in macro 1 (>= 3 sottounità della stessa macro)
        5: {"didactic_content": 0.95, "unit_1_1": 0.80, "unit_1_2": 0.85, "unit_1_3": 0.72, "unit_2_1": 0.1},
    })

    p1 = {"numero": 1, "testo": "Indice della lezione", "immagini": []}
    assert classify_material_page(p1, candidates, source, lesson_dir, {}) == ([], [])
    assert not p1.get("unplaced") and not p1.get("off_topic")

    p2 = {"numero": 2, "testo": "Misurazione della pressione arteriosa", "immagini": []}
    assert classify_material_page(p2, candidates, source, lesson_dir, {}) == ([], [])
    assert not p2.get("unplaced") and p2.get("off_topic") is True

    p3 = {"numero": 3, "testo": "Area a rischio miocardica", "immagini": []}
    assert classify_material_page(p3, candidates, source, lesson_dir, {}) == ([], ["1"])
    assert p3.get("unplaced") is True and not p3.get("off_topic")

    p4 = {"numero": 4, "testo": "Ipossia cellulare", "immagini": []}
    assert classify_material_page(p4, candidates, source, lesson_dir, {}) == (["1.1"], [])
    assert not p4.get("unplaced") and not p4.get("off_topic")

    p5 = {"numero": 5, "testo": "Danno cellulare irreversibile", "immagini": []}
    assert classify_material_page(p5, candidates, source, lesson_dir, {}) == ([], ["1"])
    assert not p5.get("unplaced") and not p5.get("off_topic")

    out_lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("📎 Materiale")]
    assert len(out_lines) == 5
    assert "patologia.pdf p.1: candidate ['1.1', '1.2', '1.3', '2.1'] probabilità" in out_lines[0]
    assert out_lines[0].endswith("→ introduttiva")
    assert out_lines[1].endswith("→ fuori tema")
    assert out_lines[2].endswith("→ non collocata")
    assert out_lines[3].endswith("→ sottounità 1.1")
    assert out_lines[4].endswith("→ macro 1")


def test_assign_material_pages_off_topic_and_unplaced_text_saved(tmp_path, monkeypatch):
    import json
    from rt.core.sources import Source
    from rt.pipeline.add_images import load_image_descriptions
    from rt.pipeline.image_placement import load_image_placement
    from rt.pipeline.material_mapping import STATE_FILE, assign_material_pages

    lesson = tmp_path / "lezione"
    lesson.mkdir()
    (lesson / "info.yaml").write_text("titolo: Patologia\n", encoding="utf-8")

    img_off = tmp_path / "off.png"
    img_off.write_bytes(b"\x89PNG-off-topic")
    img_unp = tmp_path / "unp.png"
    img_unp.write_bytes(b"\x89PNG-unplaced")

    source = Source(
        id="src1", tipo="materiale", file="slide.pdf", impronta="imp1",
        aggiunta_il="2026-11-16", ordine=1, estrai="immagini", uso="contesto",
    )
    pages = [
        {"numero": 1, "testo": "Pressione arteriosa sfigmomanometro pressione cardiaca", "immagini": ["p1.png"]},
        {"numero": 2, "testo": "Danno mitocondriale ipossico calcio", "immagini": ["p2.png"]},
    ]
    segments = SegmentsData(segments=[
        Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=10,
                start_formatted="00:00", end_formatted="00:10",
                text_raw="Danno mitocondriale ipossia calcio ischemia cardiaca."),
    ])
    (lesson / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    outline = Outline(lesson_title="Patologia", macro_sections=[
        OutlineMacro(id="1", title="Danno cellulare", units=[
            OutlineUnit(id="1.1", title="Ipossia e mitocondri",
                        start_segment_id="seg_000001", end_segment_id="seg_000001"),
        ]),
    ])

    monkeypatch.setattr("rt.core.sources.load_sources", lambda lesson_dir, *a, **k: [source])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda lesson_dir: {})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: pages)
    monkeypatch.setattr(
        "rt.pipeline.material_mapping.page_image_path",
        lambda impronta, rel: str(img_off if rel == "p1.png" else img_unp),
    )
    _image_reader(monkeypatch, reader="description")
    _setup_cached_classification(monkeypatch, source, {
        1: {"didactic_content": 0.90, "unit_1_1": 0.08},
        2: {"didactic_content": 0.92, "unit_1_1": 0.55},
    })

    state = assign_material_pages(str(lesson), outline, mock=False)
    persisted = json.loads((lesson / STATE_FILE).read_text(encoding="utf-8"))
    assert persisted == state

    # Fuori tema: né sotto una sezione né in unplaced, e la sua immagine non entra nella lezione
    assert state["pages_by_unit"] == {}
    assert state["off_topic"] == [{
        "source_id": "src1",
        "source_file": "slide.pdf",
        "page": 1,
        "text": "Pressione arteriosa sfigmomanometro pressione cardiaca",
        "macro_id": None,
        "immagini": ["p1.png"],
    }]
    # Non collocata: salvata in state["unplaced"] con il suo testo
    assert state["unplaced"] == [{
        "source_id": "src1",
        "source_file": "slide.pdf",
        "page": 2,
        "text": "Danno mitocondriale ipossico calcio",
        "macro_id": "1",
        "immagini": ["p2.png"],
    }]

    descriptions = load_image_descriptions(str(lesson))
    assert len(descriptions) == 1
    only_desc = next(iter(descriptions.values()))
    assert only_desc.get("unplaced") is True
    assert only_desc.get("source") == "material:src1:2"

    placement = load_image_placement(str(lesson))
    assert len(placement["macros"].get("1", [])) == 1
    assert placement["units"] == {}


def test_duplicate_pages_share_highest_probability_placement(tmp_path, monkeypatch):
    from rt.core.sources import Source
    from rt.pipeline.material_mapping import assign_material_pages

    lesson = tmp_path / "lezione"
    lesson.mkdir()
    (lesson / "info.yaml").write_text("titolo: Patologia\n", encoding="utf-8")

    img1 = tmp_path / "p1.png"
    img1.write_bytes(b"\x89PNG-foto-1")
    img2 = tmp_path / "p2.png"
    img2.write_bytes(b"\x89PNG-foto-2")
    img3 = tmp_path / "p3.png"
    img3.write_bytes(b"\x89PNG-foto-3")

    source = Source(
        id="src1", tipo="materiale", file="slide.pdf", impronta="imp1",
        aggiunta_il="2026-11-16", ordine=1, estrai="immagini", uso="contesto",
    )
    # p.1 (0.63) e p.2 (0.70): stesso titolo e Jaccard >= 0.8 (la migliore viene dopo, per verificare indipendenza dall'ordine)
    # p.3: stesso titolo ma testo diverso (Jaccard < 0.8) -> resta non collocata
    pages = [
        {
            "numero": 1,
            "testo": "Dalla carenza di O2\nRiduzione produzione ATP cellulare pompa sodio potassio edema",
            "immagini": ["p1.png"],
        },
        {
            "numero": 2,
            "testo": "Dalla carenza di O2\nRiduzione produzione ATP cellulare pompa sodio potassio edema cellulare",
            "immagini": ["p2.png"],
        },
        {
            "numero": 3,
            "testo": "Dalla carenza di O2\nGlicolisi anaerobia acido lattico riduzione pH intracellulare cromatina",
            "immagini": ["p3.png"],
        },
    ]
    segments = SegmentsData(segments=[
        Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=10,
                start_formatted="00:00", end_formatted="00:10",
                text_raw="Carenza di ossigeno ATP pompa sodio potassio edema glicolisi acido lattico."),
    ])
    (lesson / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    outline = Outline(lesson_title="Patologia", macro_sections=[
        OutlineMacro(id="3", title="Danno ischemico", units=[
            OutlineUnit(id="3.1", title="Deplezione di ATP",
                        start_segment_id="seg_000001", end_segment_id="seg_000001"),
        ]),
    ])

    monkeypatch.setattr("rt.core.sources.load_sources", lambda lesson_dir, *a, **k: [source])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda lesson_dir: {})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: pages)
    img_map = {"p1.png": img1, "p2.png": img2, "p3.png": img3}
    monkeypatch.setattr("rt.pipeline.material_mapping.page_image_path", lambda impronta, rel: str(img_map[rel]))
    _image_reader(monkeypatch, reader="description")
    _setup_cached_classification(monkeypatch, source, {
        1: {"didactic_content": 0.91, "unit_3_1": 0.63},
        2: {"didactic_content": 0.92, "unit_3_1": 0.70},
        3: {"didactic_content": 0.90, "unit_3_1": 0.58},
    })

    state = assign_material_pages(str(lesson), outline, mock=False)
    assert [p["page"] for p in state["pages_by_unit"]["3.1"]] == [1, 2]
    assert [p["page"] for p in state["unplaced"]] == [3]
    assert state["off_topic"] == []
    assert len(state["units"]["3.1"]) == 2
    assert len(state["macros"].get("3", [])) == 1


def test_duplicate_pages_different_titles_do_not_merge_and_didactic_beats_intro(tmp_path, monkeypatch):
    from rt.core.sources import Source
    from rt.pipeline.material_mapping import assign_material_pages

    lesson = tmp_path / "lezione"
    lesson.mkdir()
    (lesson / "info.yaml").write_text("titolo: Patologia\n", encoding="utf-8")

    source = Source(
        id="src1", tipo="materiale", file="slide.pdf", impronta="imp1",
        aggiunta_il="2026-11-16", ordine=1, estrai="testo", uso="contesto",
    )
    pages = [
        {
            "numero": 1,
            "testo": "Dalla carenza di O2\nRiduzione produzione ATP cellulare pompa sodio potassio edema",
            "immagini": [],
        },
        {
            "numero": 2,
            "testo": "Dalla carenza di O2\nRiduzione produzione ATP cellulare pompa sodio potassio edema",
            "immagini": [],
        },
        {
            "numero": 3,
            "testo": "Titolo diverso\nRiduzione produzione ATP cellulare pompa sodio potassio edema",
            "immagini": [],
        },
    ]
    segments = SegmentsData(segments=[
        Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=10,
                start_formatted="00:00", end_formatted="00:10",
                text_raw="Carenza di ossigeno ATP pompa sodio potassio edema."),
    ])
    (lesson / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    outline = Outline(lesson_title="Patologia", macro_sections=[
        OutlineMacro(id="3", title="Danno ischemico", units=[
            OutlineUnit(id="3.1", title="Deplezione di ATP",
                        start_segment_id="seg_000001", end_segment_id="seg_000001"),
        ]),
    ])

    monkeypatch.setattr("rt.core.sources.load_sources", lambda lesson_dir, *a, **k: [source])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda lesson_dir: {})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: pages)
    _image_reader(monkeypatch, reader="description")
    # p.1 introduttiva con unit_3_1=0.95 (rumorosa), p.2 didattica con unit_3_1=0.75 -> p.2 vince per p.1+p.2;
    # p.3 ha titolo diverso -> non viene fusa con p.2 e resta non collocata.
    _setup_cached_classification(monkeypatch, source, {
        1: {"didactic_content": 0.60, "unit_3_1": 0.95},
        2: {"didactic_content": 0.92, "unit_3_1": 0.75},
        3: {"didactic_content": 0.92, "unit_3_1": 0.50},
    })

    state = assign_material_pages(str(lesson), outline, mock=False)
    assert [p["page"] for p in state["pages_by_unit"]["3.1"]] == [1, 2]
    assert [p["page"] for p in state["unplaced"]] == [3]


def test_reuses_material_decisions_cache_with_new_thresholds(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from rt.core.sources import Source
    from rt.llm.jev_client import JevNoulAnswer
    from rt.pipeline.material_mapping import CACHE_FILE, CandidateSubunit, classify_material_page

    lesson_dir = str(tmp_path)
    source = Source(
        id="src1", tipo="materiale", file="slide.pdf", impronta="imp1",
        aggiunta_il="2026-11-16", ordine=1,
    )
    page = {"numero": 1, "testo": "Indice lezione\nArgomenti trattati oggi", "immagini": []}
    candidates = [CandidateSubunit(unit_id="1.1", macro_id="1", title="Ipossia", transcript="Ipossia cellulare.", score=0.9)]

    calls = 0

    def fake_decision(state, questions, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(answers={
            "didactic_content": JevNoulAnswer(noul=0.78),
            "unit_1_1": JevNoulAnswer(noul=0.80),
        })

    monkeypatch.setattr("rt.llm.client.LLMClient", lambda **k: SimpleNamespace(force_mock=False))
    monkeypatch.setattr("rt.services.enrichment_service.decision", fake_decision)

    cached = {}
    assert classify_material_page(page, candidates, source, lesson_dir, cached, mock=False) == ([], [])
    assert calls == 1

    # Rilegge da disco (come alla ricostruzione della lezione) senza nuove chiamate a decision
    reloaded = json.loads((tmp_path / CACHE_FILE).read_text(encoding="utf-8"))
    monkeypatch.setattr("rt.services.enrichment_service.decision", lambda *a, **k: pytest.fail("cache miss"))
    assert classify_material_page(page, candidates, source, lesson_dir, reloaded, mock=False) == ([], [])
    assert not page.get("unplaced") and not page.get("off_topic")



