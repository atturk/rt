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


def test_render_rielaborato_md_excludes_unplaced_images():
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

    assert "![Figura Iniziale](assets/images/top.png)" in md
    assert "bottom.png" not in md
    assert "Materiale non collocato" not in md


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


def test_unplaced_not_in_markdown_but_manual_placement_clears_unplaced_and_appears_on_build(tmp_path, monkeypatch):
    import io
    import json
    from PIL import Image
    from rt.core.sources import Source, _save
    from rt.core.config import ClassifierJob
    from rt.core.idempotency import PhaseStatus
    from rt.pipeline.add_images import load_image_descriptions, compute_image_hash
    from rt.pipeline.outline import save_outline
    from rt.pipeline.rewrite import save_draft
    from rt.pipeline.build import render_lesson_documents
    from rt.services.editor_media_service import _copy_material_page
    from rt.services.document_edit_service import save_document_edit
    from rt.core.archive import entry_dir, write_json

    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("titolo: Prova\nmateria: TEST\ndata: '2026-11-26'\n", encoding="utf-8")

    # Crea una pagina materiale in archivio
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "red").save(buf, format="PNG")
    img_bytes = buf.getvalue()
    impronta = "a" * 64
    source = Source(id="src_mat1", tipo="materiale", file="slides.pdf", impronta=impronta, aggiunta_il="2026-11-26", ordine=1, estrai="immagini")
    _save(lesson_dir, [source])

    folder = entry_dir(impronta)
    import os
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "page-1-1.png"), "wb") as f:
        f.write(img_bytes)
    write_json(os.path.join(folder, "pages.json"), {
        "impronta": impronta,
        "pages": [{"numero": 1, "testo": "Diagramma cellulare", "immagini": ["page-1-1.png"], "has_figures": True}],
    })

    segments = SegmentsData(segments=[
        Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=60,
                start_formatted="00:00", end_formatted="01:00", text_raw="Introduzione cellulare."),
    ])
    (tmp_path / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    outline = Outline(lesson_title="Lezione", macro_sections=[
        OutlineMacro(id="1", title="Sezione Uno", units=[
            OutlineUnit(id="1.1", title="Unità Uno", start_segment_id="seg_000001", end_segment_id="seg_000001"),
        ]),
    ])
    save_outline(outline, lesson_dir)
    save_draft(Draft(units=[
        DraftUnit(unit_id="1.1", title="Unità Uno", start_segment_id="seg_000001", end_segment_id="seg_000001",
                  source_segment_ids=["seg_000001"], content="Contenuto dell'unità 1.1"),
    ]), lesson_dir)

    monkeypatch.setattr("rt.core.idempotency.check_phase_status", lambda *a, **k: (PhaseStatus.VALID, "ok"))
    monkeypatch.setattr("rt.core.source_selection.selection", lambda *a, **k: {})
    monkeypatch.setattr("rt.pipeline.image_decision.uses_image_for_material_pages", lambda *a, **k: False)
    monkeypatch.setattr("rt.core.config.classifier_job",
                        lambda cfg, name: ClassifierJob(mode="manual", model="m", credential="c", timeout_seconds=10, threshold=0.7))
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: [
        {"numero": 1, "testo": "Diagramma cellulare membrana cellulare", "immagini": ["page-1-1.png"], "has_figures": True}
    ])
    monkeypatch.setattr("rt.pipeline.material_mapping.page_image_path", lambda imp, rel: os.path.join(folder, "page-1-1.png"))
    monkeypatch.setattr("rt.llm.client.LLMClient", lambda **k: type("C", (), {"force_mock": False})())
    monkeypatch.setattr("rt.services.enrichment_service.digest", lambda *a: "k1")
    from rt.llm.jev_client import JevNoulAnswer
    monkeypatch.setattr("rt.services.enrichment_service.decision", lambda *a, **k: type("R", (), {
        "answers": {"didactic_content": JevNoulAnswer(noul=0.95), "unit_1_1": JevNoulAnswer(noul=0.40)}
    })())

    state = assign_material_pages(lesson_dir, outline, mock=False)
    assert len(state["unplaced"]) == 1
    descs = load_image_descriptions(lesson_dir)
    h = compute_image_hash(img_bytes)
    assert descs[h].get("unplaced") is True

    # 1. Non compare nel markdown prima di essere collocata a mano
    docs_before = render_lesson_documents(lesson_dir)
    assert h[:16] not in docs_before["rielaborato"]

    # 2. Trascinata in un'unità (copia materiale + save_document_edit nella sezione dell'unità 1.1)
    _copy_material_page(lesson_dir, "src_mat1", 1)
    descs_after_copy = load_image_descriptions(lesson_dir)
    assert not descs_after_copy[h].get("unplaced")
    rel_file = descs_after_copy[h]["filename"]
    new_md = (
        "## 1. Sezione Uno\n\n"
        "### 1.1 Unità Uno\n"
        "00:00\n\n"
        f"![slides.pdf, pagina 1]({rel_file})\n\n"
        "Contenuto dell'unità 1.1\n"
    )
    save_document_edit(lesson_dir, new_md)

    docs_after = render_lesson_documents(lesson_dir)
    assert rel_file in docs_after["rielaborato"]
    assert json.loads((tmp_path / STATE_FILE).read_text(encoding="utf-8"))["unplaced"] == []


def test_photo_placed_by_timestamp_and_skips_classifier(tmp_path, monkeypatch, capsys):
    from rt.core.sources import Source
    from rt.pipeline.image_placement import load_image_placement

    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("titolo: Lezione\n", encoding="utf-8")
    (tmp_path / "foto.png").write_bytes(b"\x89PNG-foto-orario")

    audio = Source(
        id="src_aud", tipo="audio", file="sources/src_aud/audio_2026-11-26_14-27-18.ogg",
        impronta="aud1", aggiunta_il="2026-11-26", ordine=1,
    )
    photo = Source(
        id="src_img", tipo="materiale", file="sources/src_img/photo_2026-11-26_14-29-33.jpg",
        impronta="img1", aggiunta_il="2026-11-26", ordine=2, estrai="immagini",
    )
    segments = SegmentsData(
        audio_duration_seconds=3840.0,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=1200.0,
                    start_formatted="00:00", end_formatted="20:00", text_raw="Prima unità spiegata dal prof."),
            Segment(id="seg_000002", index=2, start_seconds=1210.0, end_seconds=3840.0,
                    start_formatted="20:10", end_formatted="1:04:00", text_raw="Seconda unità."),
        ],
    )
    (tmp_path / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    (tmp_path / "source_update.json").write_text(
        '{"next_segment": 3, "sources": {"src_aud": {"segments": [], "duration": 3840.0}}}',
        encoding="utf-8",
    )
    outline = Outline(lesson_title="Lezione", macro_sections=[
        OutlineMacro(id="1", title="Macro 1", units=[
            OutlineUnit(id="1.1", title="Prima Unità", start_segment_id="seg_000001", end_segment_id="seg_000001"),
            OutlineUnit(id="1.2", title="Seconda Unità", start_segment_id="seg_000002", end_segment_id="seg_000002"),
        ]),
    ])

    monkeypatch.setattr("rt.core.sources.load_sources", lambda *a, **k: [audio, photo])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda *a, **k: {"principale": "src_aud"})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: [
        {"numero": 1, "testo": "Testo della foto", "immagini": ["page-1-1.png"], "has_figures": True}
    ])
    monkeypatch.setattr("rt.pipeline.material_mapping.page_image_path", lambda *a: str(tmp_path / "foto.png"))
    monkeypatch.setattr("rt.pipeline.material_mapping.place_page_in_outline",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Il classificatore non deve essere chiamato")))

    state = assign_material_pages(lesson_dir, outline, mock=False)
    assert list(state["units"]) == ["1.1"]
    assert len(state["units"]["1.1"]) == 1
    assert state["unplaced"] == []
    placement = load_image_placement(lesson_dir)
    assert list(placement["units"]) == ["1.1"]

    out = capsys.readouterr().out
    assert "foto photo_2026-11-26_14-29-33.jpg scattata 14:29:33 → offset 02:15 → unità 1.1 (per orario)" in out


def test_photo_outside_window_or_without_time_uses_classifier(tmp_path, monkeypatch):
    from rt.core.sources import Source

    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("titolo: Lezione\n", encoding="utf-8")
    (tmp_path / "f1.png").write_bytes(b"\x89PNG-f1")
    (tmp_path / "f2.png").write_bytes(b"\x89PNG-f2")

    audio = Source(
        id="src_aud", tipo="audio", file="sources/src_aud/audio_2026-11-26_14-00-00.ogg",
        impronta="aud1", aggiunta_il="2026-11-26", ordine=1,
    )
    # Fuori finestra: 14:40 su audio di 10 min (600s + 120s = 720s, qui offset = 2400s)
    photo_late = Source(
        id="src_img1", tipo="materiale", file="sources/src_img1/photo_2026-11-26_14-40-00.jpg",
        impronta="img1", aggiunta_il="2026-11-26", ordine=2, estrai="immagini",
    )
    # Senza orario nel nome né EXIF
    photo_notime = Source(
        id="src_img2", tipo="materiale", file="sources/src_img2/lavagna.jpg",
        impronta="img2", aggiunta_il="2026-11-26", ordine=3, estrai="immagini",
    )
    segments = SegmentsData(
        audio_duration_seconds=600.0,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=600.0,
                    start_formatted="00:00", end_formatted="10:00", text_raw="Contenuto unico."),
        ],
    )
    (tmp_path / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    (tmp_path / "source_update.json").write_text(
        '{"next_segment": 2, "sources": {"src_aud": {"segments": [], "duration": 600.0}}}',
        encoding="utf-8",
    )
    outline = Outline(lesson_title="Lezione", macro_sections=[
        OutlineMacro(id="1", title="Macro 1", units=[
            OutlineUnit(id="1.1", title="Unità 1", start_segment_id="seg_000001", end_segment_id="seg_000001"),
        ]),
    ])

    classifier_calls = []

    def fake_place(page, corpus, idf, source, *a, **k):
        classifier_calls.append(source.id)
        page["unplaced"] = False
        page["off_topic"] = False
        return ["1.1"], []

    monkeypatch.setattr("rt.core.sources.load_sources", lambda *a, **k: [audio, photo_late, photo_notime])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda *a, **k: {"principale": "src_aud"})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda _d, s, **k: [
        {"numero": 1, "testo": "Testo", "immagini": [f"{s.id}.png"], "has_figures": True}
    ])
    monkeypatch.setattr("rt.pipeline.material_mapping.page_image_path",
                        lambda _imp, rel: str(tmp_path / ("f1.png" if rel == "src_img1.png" else "f2.png")))
    monkeypatch.setattr("rt.pipeline.material_mapping.place_page_in_outline", fake_place)

    assign_material_pages(lesson_dir, outline, mock=False)
    assert classifier_calls == ["src_img1", "src_img2"]


def test_photo_offset_with_two_audio_parts_and_gap(tmp_path, monkeypatch):
    from rt.core.sources import Source

    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("titolo: Lezione\n", encoding="utf-8")
    (tmp_path / "foto.png").write_bytes(b"\x89PNG-part2")

    # Parte 1: 14:00:00, durata 1800s (timeline 0..1800)
    # Parte 2: 14:35:00 (pausa di 5 min!), durata 1800s (timeline 1800..3600)
    aud1 = Source(
        id="src_aud1", tipo="audio", file="sources/src_aud1/audio_2026-11-26_14-00-00.ogg",
        impronta="a1", aggiunta_il="2026-11-26", ordine=1,
    )
    aud2 = Source(
        id="src_aud2", tipo="audio", file="sources/src_aud2/audio_2026-11-26_14-35-00.ogg",
        impronta="a2", aggiunta_il="2026-11-26", ordine=2,
    )
    # Foto scattata alle 14:40:00 -> 5 min (300s) dentro la parte 2 -> offset timeline = 1800 + 300 = 2100s
    photo = Source(
        id="src_img", tipo="materiale", file="sources/src_img/PXL_20261126_144000123.jpg",
        impronta="img1", aggiunta_il="2026-11-26", ordine=3, estrai="immagini",
    )
    segments = SegmentsData(
        audio_duration_seconds=3600.0,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=1800.0,
                    start_formatted="00:00", end_formatted="30:00", text_raw="Parte 1."),
            Segment(id="seg_000002", index=2, start_seconds=1800.0, end_seconds=2050.0,
                    start_formatted="30:00", end_formatted="34:10", text_raw="Inizio parte 2."),
            # Gap fra 2050 e 2150 -> offset 2100 cade tra 2.1 e 2.2 -> va in 2.1 (quella che inizia prima)
            Segment(id="seg_000003", index=3, start_seconds=2150.0, end_seconds=3600.0,
                    start_formatted="35:50", end_formatted="1:00:00", text_raw="Fine parte 2."),
        ],
    )
    (tmp_path / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    (tmp_path / "source_update.json").write_text(
        '{"next_segment": 4, "sources": {"src_aud1": {"segments": [], "duration": 1800.0}, "src_aud2": {"segments": [], "duration": 1800.0}}}',
        encoding="utf-8",
    )
    outline = Outline(lesson_title="Lezione", macro_sections=[
        OutlineMacro(id="1", title="Macro 1", units=[
            OutlineUnit(id="1.1", title="U1", start_segment_id="seg_000001", end_segment_id="seg_000001"),
            OutlineUnit(id="2.1", title="U2.1", start_segment_id="seg_000002", end_segment_id="seg_000002"),
            OutlineUnit(id="2.2", title="U2.2", start_segment_id="seg_000003", end_segment_id="seg_000003"),
        ]),
    ])

    monkeypatch.setattr("rt.core.sources.load_sources", lambda *a, **k: [aud1, aud2, photo])
    monkeypatch.setattr("rt.core.source_selection.selection", lambda *a, **k: {"principale": "src_aud1"})
    monkeypatch.setattr("rt.core.materials.material_pages", lambda *a, **k: [
        {"numero": 1, "testo": "", "immagini": ["page-1-1.png"], "has_figures": True}
    ])
    monkeypatch.setattr("rt.pipeline.material_mapping.page_image_path", lambda *a: str(tmp_path / "foto.png"))
    monkeypatch.setattr("rt.pipeline.material_mapping.place_page_in_outline",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Classificatore non atteso")))

    state = assign_material_pages(lesson_dir, outline, mock=False)
    assert list(state["units"]) == ["2.1"]
