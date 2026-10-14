import os
import json
import pytest

from rt.core.models import Outline, OutlineMacro, OutlineUnit, Draft, DraftUnit
from rt.core.segments import SegmentsData, Segment
from rt.pipeline.build import render_rielaborato_md
from rt.pipeline.image_placement import (
    load_image_placement,
    save_image_placement,
    images_for_document,
    sort_images_document_order,
)
from rt.services.document_edit_service import save_document_edit
from tests.test_document_edit import _synthetic_lesson, _preview


@pytest.fixture
def lessons_root(tmp_path):
    d = tmp_path / "lessons"
    d.mkdir()
    return str(d)


def test_render_rielaborato_md_subunit_images_and_spacing():
    outline = Outline(
        schema_version="1.0",
        lesson_title="Test Lesson",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Macro One",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Subunit One",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000002",
                    )
                ],
            )
        ],
    )
    draft = Draft(
        schema_version="1.0",
        lesson_id="test",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Subunit One",
                content="Contenuto della prima sottounità.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000002",
                source_segment_ids=["seg_000001", "seg_000002"],
            )
        ],
    )
    segments_data = SegmentsData(
        segments=[
            Segment(
                id="seg_000001",
                index=1,
                start_seconds=10.0,
                end_seconds=20.0,
                start_formatted="00:10",
                end_formatted="00:20",
                text_raw="segment one",
            ),
            Segment(
                id="seg_000002",
                index=2,
                start_seconds=20.0,
                end_seconds=30.0,
                start_formatted="00:20",
                end_formatted="00:30",
                text_raw="segment two",
            ),
        ]
    )

    images_by_macro = {
        "1": [
            {"filename": "assets/images/m1.png", "alt_text": "Macro Image 1"},
            {"filename": "assets/images/m2.png", "alt_text": "Macro Image 2"},
        ]
    }
    images_by_unit = {
        "1.1": [
            {"filename": "assets/images/u1.png", "alt_text": "Unit Image 1"},
            {"filename": "assets/images/u2.png", "alt_text": "Unit Image 2"},
        ]
    }

    md = render_rielaborato_md(
        outline=outline,
        draft=draft,
        segments_data=segments_data,
        date="2026-10-14",
        subject="TEST",
        topics="Topics",
        images_by_macro=images_by_macro,
        images_by_unit=images_by_unit,
    )

    # Verifica IM1a: immagini della macro sotto ## 1.
    assert "## 1. Macro One\n\n![Macro Image 1](assets/images/m1.png)\n\n![Macro Image 2](assets/images/m2.png)" in md

    # Verifica IM1a: immagini della sottounità subito dopo il timestamp sotto ### 1.1
    assert "### 1.1 Subunit One\n00:10\n\n![Unit Image 1](assets/images/u1.png)\n\n![Unit Image 2](assets/images/u2.png)" in md

    # Verifica IM1b: un link immagine per riga, separati da una riga vuota
    assert "![Unit Image 1](assets/images/u1.png)\n\n![Unit Image 2](assets/images/u2.png)" in md


def test_document_edit_service_accepts_unit_images(lessons_root):
    from rt.pipeline.add_images import save_image_descriptions
    lesson_dir = _synthetic_lesson(lessons_root)
    # Registra descrizioni immagini fittizie
    save_image_descriptions(lesson_dir, {
        "hash_u1": {"filename": "assets/images/hash_u1.png", "alt_text": "Image U1", "source": "material:src_1:1"},
        "hash_u2": {"filename": "assets/images/hash_u2.png", "alt_text": "Image U2", "source": "material:src_1:2"},
        "hash_m1": {"filename": "assets/images/hash_m1.png", "alt_text": "Image M1", "source": "material:src_1:0"},
    })

    preview = _preview(lesson_dir)

    # Inserisci un'immagine sotto la macro e due immagini sotto l'unità 1.1 dopo il timecode
    modified = preview.replace(
        "## 1. Struttura\n",
        "## 1. Struttura\n\n![Image M1](assets/images/hash_m1.png)\n",
    )
    modified = modified.replace(
        "### 1.1 Acidi grassi\n00:00\n",
        "### 1.1 Acidi grassi\n00:00\n\n![Image U1](assets/images/hash_u1.png)\n\n![Image U2](assets/images/hash_u2.png)\n",
    )

    res = save_document_edit(lesson_dir, modified)
    assert res["changed"] is True

    placement = load_image_placement(lesson_dir)
    assert placement is not None
    assert placement["macros"].get("1") == ["hash_m1"]
    assert placement["units"].get("1.1") == ["hash_u1", "hash_u2"]


def test_sort_images_document_order(tmp_path):
    from rt.core.sources import add_source
    from tests.test_materials import pdf_bytes
    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("materia: Test\ndata: 2026-10-14\nfile_audio: ''\n")

    s1 = add_source(lesson_dir, "materiale", "doc1.pdf", pdf_bytes("DOC 1"))
    s2 = add_source(lesson_dir, "materiale", "doc2.pdf", pdf_bytes("DOC 2"))

    images = [
        {"filename": "web.png", "source": "web"},
        {"filename": "s2_p1.png", "source": f"material:{s2.id}:1"},
        {"filename": "s1_p5.png", "source": f"material:{s1.id}:5"},
        {"filename": "s1_p2.png", "source": f"material:{s1.id}:2"},
        {"filename": "manual.png", "source": "manual"},
    ]

    sorted_imgs = sort_images_document_order(lesson_dir, images)
    sorted_files = [img["filename"] for img in sorted_imgs]

    # Ordine atteso:
    # 1. Fonti nell'ordine delle fonti (s1 prima di s2)
    # 2. Numero di pagina (s1_p2 prima di s1_p5)
    # 3. s2_p1
    # 4. Immagini web/manuali nel loro ordine originale alla fine
    assert sorted_files == ["s1_p2.png", "s1_p5.png", "s2_p1.png", "web.png", "manual.png"]
