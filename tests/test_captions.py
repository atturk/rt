"""Test unitari per didascalie delle slide, estrazione titoli e alt Markdown."""
import io
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pymupdf as fitz

from rt.core import archive
from rt.core.captions import clean_caption, page_alt
from rt.core.materials import material_pages
from rt.core.models import Draft, DraftUnit, Outline, OutlineMacro, OutlineUnit, Segment, SegmentsData
from rt.core.sources import Source, add_source, _save as save_sources
from rt.llm.prompts import ImageDescription
from rt.pipeline.add_images import compute_image_hash, save_image_descriptions, save_raw_image, _mock_png
from rt.pipeline.build import render_lesson_documents
from rt.pipeline.image_placement import save_image_placement
from rt.pipeline.outline import save_outline
from rt.pipeline.rewrite import save_draft


def test_clean_caption_and_page_alt():
    assert clean_caption(None) is None
    assert clean_caption("") is None
    assert clean_caption("  N/A  ") is None
    assert clean_caption("n/a") is None
    assert clean_caption("[Titolo] \\ con\na capo — e   spazi") == "Titolo con a capo - e spazi"

    long_title = "A" * 95
    cleaned = clean_caption(long_title)
    assert cleaned is not None
    assert len(cleaned) == 90
    assert cleaned.endswith("…")

    assert page_alt("dir/Lez1.pdf", 3, "Ipossia cellulare") == "Ipossia cellulare — Lez1.pdf, pagina 3"
    assert page_alt("dir/Lez1.pdf", 3, "N/A") == "Lez1.pdf, pagina 3"
    assert page_alt("dir/Lez1.pdf", 3, None) == "Lez1.pdf, pagina 3"
    assert page_alt("PHOTO-2026.jpg", 1, "Schema sinapsi", single_page=True) == "Schema sinapsi — PHOTO-2026.jpg"
    assert page_alt("PHOTO-2026.jpg", 1, None, single_page=True) == "PHOTO-2026.jpg"


def _make_lesson(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    (path / "info.yaml").write_text("titolo: Prova\n", encoding="utf-8")
    return str(path)


def test_pdf_title_extraction_via_pymupdf(tmp_path):
    lesson = _make_lesson(tmp_path / "lezione")
    pdf_path = tmp_path / "slides.pdf"

    with fitz.open() as doc:
        # Pagina 1: numero solo cifre grande in alto, titolo grande nel 40% alto, corpo piu' piccolo, testo enorme in basso (> 40%)
        p1 = doc.new_page(width=600, height=800)
        p1.insert_text((40, 40), "12", fontsize=36)
        p1.insert_text((40, 120), "Meccanismi di danno cellulare", fontsize=24)
        p1.insert_text((40, 220), "Deplezione di ATP e danno mitocondriale nella cellula ischemica", fontsize=12)
        p1.insert_text((40, 600), "TESTO ENORME IN BASSO", fontsize=40)

        # Pagina 2: solo testo uniforme lungo senza titolo (> 120 caratteri non vale come titolo)
        p2 = doc.new_page(width=2000, height=800)
        p2.insert_text((40, 60), "Riga molto lunga " + ("a " * 60), fontsize=22)
        p2.insert_text((40, 140), "Paragrafo di corpo normale sulla necrosi coagulativa", fontsize=11)
        p2.insert_text((40, 170), "Altra riga di corpo normale sullo stesso argomento", fontsize=11)
        p2.insert_text((40, 200), "Terza riga di corpo normale del documento di prova", fontsize=11)

        doc.save(pdf_path)

    source = add_source(lesson, "materiale", "slides.pdf", pdf_path.read_bytes(), estrai="testo")
    pages = material_pages(lesson, source, mock=True)
    assert len(pages) == 2
    assert pages[0]["titolo"] == "Meccanismi di danno cellulare"
    assert "titolo" not in pages[1]


def test_pptx_docx_and_markdown_titles(tmp_path):
    from docx import Document
    from pptx import Presentation

    lesson = _make_lesson(tmp_path / "lezione")

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Ciclo di Krebs"
    slide.placeholders[1].text = "Ossidazione dell'acetil-CoA nel mitocondrio."
    pptx_buf = io.BytesIO()
    prs.save(pptx_buf)
    src_pptx = add_source(lesson, "materiale", "bio.pptx", pptx_buf.getvalue(), estrai="testo")
    assert material_pages(lesson, src_pptx, mock=True)[0]["titolo"] == "Ciclo di Krebs"

    docx_doc = Document()
    docx_doc.add_heading("Fosforilazione ossidativa", level=1)
    docx_doc.add_paragraph("La catena di trasporto degli elettroni genera un gradiente protonico.")
    docx_buf = io.BytesIO()
    docx_doc.save(docx_buf)
    src_docx = add_source(lesson, "materiale", "appunti.docx", docx_buf.getvalue(), estrai="testo")
    assert material_pages(lesson, src_docx, mock=True)[0]["titolo"] == "Fosforilazione ossidativa"

    src_md = add_source(lesson, "materiale", "note.md", b"# Glicolisi\n\nVia metabolica citosolica.", estrai="testo")
    assert material_pages(lesson, src_md, mock=True)[0]["titolo"] == "Glicolisi"


def test_vision_description_saves_and_reuses_title_and_legacy_image_cache(tmp_path, monkeypatch):
    from rt.llm.client import LLMClient

    lesson_a = _make_lesson(tmp_path / "a")
    lesson_b = _make_lesson(tmp_path / "b")

    # 1. slide_title valido -> salvato in descrizione.json e su pagina
    monkeypatch.setattr(
        LLMClient,
        "call_structured",
        lambda self, **k: ImageDescription(
            slide_title="Potenziale del potassio",
            ocr_text="Equazione di Nernst K+",
            alt_text="Grafico potenziale di membrana",
        ),
    )
    img1 = _mock_png("slide-k")
    src_a = add_source(lesson_a, "materiale", "foto_k.png", img1, estrai="immagini")
    pages_a = material_pages(lesson_a, src_a)
    assert pages_a[0]["titolo"] == "Potenziale del potassio"
    desc_json = archive.read_json(os.path.join(archive.entry_dir(src_a.impronta), "descrizione.json"))
    assert desc_json["slide_title"] == "Potenziale del potassio"
    assert desc_json["alt_text"] == "Grafico potenziale di membrana"

    # 2. slide_title == 'N/A' -> ripiega su alt_text
    monkeypatch.setattr(
        LLMClient,
        "call_structured",
        lambda self, **k: ImageDescription(
            slide_title="N/A",
            ocr_text="Solo immagine microscopica",
            alt_text="Sezione istologica di tessuto epatico",
        ),
    )
    img2 = _mock_png("slide-na")
    src_b = add_source(lesson_b, "materiale", "foto_na.png", img2, estrai="immagini")
    pages_b = material_pages(lesson_b, src_b)
    assert pages_b[0]["titolo"] == "Sezione istologica di tessuto epatico"

    # 3. Cache vecchia senza 'titolo' per immagine: usa prima riga di testo se non è 'N/A'
    img3 = _mock_png("legacy-img")
    src_leg = add_source(lesson_a, "materiale", "legacy.png", img3, estrai="immagini")
    folder = archive.entry_dir(src_leg.impronta)
    os.makedirs(folder, exist_ok=True)
    archive.write_json(
        os.path.join(folder, "pages.json"),
        {
            "impronta": src_leg.impronta,
            "pages": [
                {
                    "numero": 1,
                    "testo": "Titolo storico\nTesto OCR",
                    "immagini": ["page-1-1.png"],
                    "mapping_text": "Titolo storico\nTesto OCR",
                    "has_figures": True,
                    "mapping_skip": False,
                }
            ],
        },
    )
    archive.save_meta(src_leg.impronta, {"pagine_totali": 1, "estrai": "immagini"})
    monkeypatch.setattr("rt.core.materials._describe", Mock(side_effect=AssertionError("no vision")))
    assert material_pages(lesson_a, src_leg)[0]["titolo"] == "Titolo storico"


def test_crop_uses_title_as_label_when_available(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from rt.services import editor_media_service

    lesson = _make_lesson(tmp_path / "lezione")
    img_data = _mock_png("crop-src")
    h = compute_image_hash(img_data)
    rel = save_raw_image(lesson, img_data, h)
    save_image_descriptions(
        lesson,
        {
            h: {
                "filename": rel,
                "source": "material:src1:3",
                "slide_title": "Sinapsi chimica",
                "alt_text": "Sinapsi chimica — slides.pdf, pagina 3",
            }
        },
    )

    @contextmanager
    def dummy_scope(_db):
        yield None

    monkeypatch.setattr(editor_media_service, "_require_db", lambda: None)
    monkeypatch.setattr(editor_media_service, "session_scope", dummy_scope)
    monkeypatch.setattr(editor_media_service, "_guard", lambda *a, **k: None)

    cropped = editor_media_service.crop_image(
        1, lesson, os.path.basename(rel), (0.0, 0.0, 0.5, 0.5), replace=False
    )
    assert cropped["alt_text"] == "Sinapsi chimica · ritaglio 1"



def test_build_upgrades_legacy_material_alt_without_separator(tmp_path):
    lesson = tmp_path / "lezione"
    lesson.mkdir()
    (lesson / "info.yaml").write_text("titolo: Prova\ndata: 2026-11-16\nmateria: Patologia\n", encoding="utf-8")

    pdf_path = tmp_path / "slide_vecchie.pdf"
    with fitz.open() as doc:
        p = doc.new_page(width=500, height=400)
        p.insert_text((30, 50), "Area a rischio ischemica", fontsize=22)
        p.insert_text((30, 120), "Zona miocardica perfusa dall'arteria occlusa.", fontsize=11)
        doc.save(pdf_path)

    src = add_source(str(lesson), "materiale", "slide_vecchie.pdf", pdf_path.read_bytes(), estrai="immagini")
    # Simula cache vecchia con titolo in pages.json ma alt_text vecchio in descriptions.json
    folder = archive.entry_dir(src.impronta)
    os.makedirs(folder, exist_ok=True)
    archive.write_json(
        os.path.join(folder, "pages.json"),
        {
            "impronta": src.impronta,
            "pages": [{"numero": 1, "testo": "Testo", "titolo": "Area a rischio ischemica", "immagini": ["page-1-1.png"]}],
        },
    )

    outline = Outline(
        lesson_title="Prova",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Ischemia",
                units=[OutlineUnit(id="1.1", title="Area a rischio", start_segment_id="seg_000001", end_segment_id="seg_000001")],
            )
        ],
    )
    save_outline(outline, str(lesson))
    segments = SegmentsData(
        segments=[
            Segment(
                id="seg_000001", index=1, start_seconds=0, end_seconds=10,
                start_formatted="00:00", end_formatted="00:10", text_raw="Testo lezione.",
            )
        ]
    )
    (lesson / "segments.json").write_text(segments.model_dump_json(), encoding="utf-8")
    save_draft(
        Draft(units=[DraftUnit(unit_id="1.1", title="Area a rischio", start_segment_id="seg_000001", end_segment_id="seg_000001", source_segment_ids=["seg_000001"], content="Contenuto.")]),
        str(lesson),
    )

    img_data = _mock_png("img-1")
    h = compute_image_hash(img_data)
    rel = save_raw_image(str(lesson), img_data, h)
    save_image_descriptions(
        str(lesson),
        {
            h: {
                "filename": rel,
                "source": f"material:{src.id}:1",
                "alt_text": "slide_vecchie.pdf, pagina 1",
            }
        },
    )
    save_image_placement(str(lesson), macros={}, carousel=False, units={"1.1": [h]})

    docs = render_lesson_documents(str(lesson))
    assert f"![Area a rischio ischemica — slide_vecchie.pdf, pagina 1]({rel})" in docs["rielaborato"]
