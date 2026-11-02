import pytest
from rt.core.models import Outline, OutlineMacro, OutlineUnit, Segment, SegmentsData, Draft, DraftUnit
from rt.core.sources import Source
from rt.pipeline.material_mapping import (
    CandidateSubunit,
    classify_material_page,
    assign_material_pages,
    STATE_FILE,
)
from rt.pipeline.build import render_rielaborato_md
from rt.services.sources_view import sources_view


def test_didactic_page_low_unit_probs_assigned_to_macro_and_unplaced(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    source = Source(id="src_mat1", tipo="materiale", file="sources/src_mat1/doc.pdf",
                    impronta="hash123", aggiunta_il="2026-10-14T00:00:00Z", ordine=1)
    page = {"numero": 2, "testo": "Testo didattico", "immagini": []}
    candidates = [
        CandidateSubunit(unit_id="1.1", macro_id="1", title="Titolo 1.1", transcript="testo", score=0.8),
        CandidateSubunit(unit_id="2.1", macro_id="2", title="Titolo 2.1", transcript="testo", score=0.6),
    ]

    cached = {
        f"{source.id}:{page['numero']}": {
            "key": "test_key",
            "probabilities": {
                "didactic_content": 0.85,
                "unit_1_1": 0.40,
                "unit_2_1": 0.30,
            }
        }
    }
    monkeypatch.setattr("rt.services.enrichment_service.digest", lambda *a: "test_key")

    units, macros = classify_material_page(page, candidates, source, lesson_dir, cached, mock=False)
    assert units == []
    # Best candidate is unit 1.1 with prob 0.40 -> macro "1"
    assert macros == ["1"]
    assert page.get("unplaced") is True


def test_non_didactic_page_discarded(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    source = Source(id="src_mat1", tipo="materiale", file="sources/src_mat1/doc.pdf",
                    impronta="hash123", aggiunta_il="2026-10-14T00:00:00Z", ordine=1)
    page = {"numero": 1, "testo": "Indice e copertina", "immagini": []}
    candidates = [
        CandidateSubunit(unit_id="1.1", macro_id="1", title="Titolo 1.1", transcript="testo", score=0.8),
    ]

    cached = {
        f"{source.id}:{page['numero']}": {
            "key": "test_key",
            "probabilities": {
                "didactic_content": 0.20,
                "unit_1_1": 0.50,
            }
        }
    }
    monkeypatch.setattr("rt.services.enrichment_service.digest", lambda *a: "test_key")

    units, macros = classify_material_page(page, candidates, source, lesson_dir, cached, mock=False)
    assert units == []
    assert macros == []
    assert not page.get("unplaced")


def test_didactic_page_no_candidates_unplaced_without_macro(tmp_path, monkeypatch):
    lesson_dir = str(tmp_path)
    source = Source(id="src_mat1", tipo="materiale", file="sources/src_mat1/doc.pdf",
                    impronta="hash123", aggiunta_il="2026-10-14T00:00:00Z", ordine=1)
    page = {"numero": 3, "testo": "Testo didattico specialistico senza match", "immagini": []}
    candidates = []

    cached = {
        f"{source.id}:{page['numero']}": {
            "key": "test_key",
            "probabilities": {
                "didactic_content": 0.88,
            }
        }
    }
    monkeypatch.setattr("rt.services.enrichment_service.digest", lambda *a: "test_key")

    units, macros = classify_material_page(page, candidates, source, lesson_dir, cached, mock=False)
    assert units == []
    assert macros == []
    assert page.get("unplaced") is True


def test_render_rielaborato_md_unplaced_images_at_end_of_macro():
    outline = Outline(
        lesson_title="Lezione di Prova",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Prima Sezione",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Unità Uno",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000001",
                    )
                ],
            )
        ],
    )
    draft = Draft(
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Unità Uno",
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
                content="Contenuto dell'unità 1.1",
            )
        ]
    )
    segments_data = SegmentsData(segments=[
        Segment(
            id="seg_000001",
            index=1,
            start_seconds=0,
            end_seconds=10,
            start_formatted="00:00",
            end_formatted="00:10",
            text_raw="Trascritto",
        )
    ])

    images_by_macro = {
        "1": [
            {"filename": "assets/images/top.png", "alt_text": "Figura Iniziale", "unplaced": False},
            {"filename": "assets/images/bottom.png", "alt_text": "Materiale non collocato", "unplaced": True},
        ]
    }

    md = render_rielaborato_md(
        outline=outline,
        draft=draft,
        segments_data=segments_data,
        date="2026-11-02",
        subject="Fisica",
        topics="Termodinamica",
        images_by_macro=images_by_macro,
    )

    # top.png must appear before unit 1.1
    # bottom.png must appear after unit 1.1 content
    pos_top = md.find("![Figura Iniziale](assets/images/top.png)")
    pos_unit = md.find("### 1.1 Unità Uno")
    pos_content = md.find("Contenuto dell'unità 1.1")
    pos_bottom = md.find("![Materiale non collocato](assets/images/bottom.png)")

    assert pos_top != -1
    assert pos_unit != -1
    assert pos_content != -1
    assert pos_bottom != -1
    assert pos_top < pos_unit < pos_content < pos_bottom


def test_sources_view_returns_unplaced(tmp_path):
    import json
    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("titolo: Test\n", encoding="utf-8")
    (tmp_path / "sources.json").write_text("[]", encoding="utf-8")

    unplaced_data = [
        {
            "source_id": "src_mat1",
            "source_file": "slide.pdf",
            "page": 4,
            "text": "Slide non collocata",
            "macro_id": "2",
            "immagini": [],
        }
    ]
    (tmp_path / STATE_FILE).write_text(json.dumps({"unplaced": unplaced_data}), encoding="utf-8")

    res = sources_view(lesson_dir)
    assert res.get("unplaced") == unplaced_data
