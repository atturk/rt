import os
import json
import pytest
from dataclasses import dataclass
from typing import List
from rt.core.image_extract import ExtractedImage
from rt.pipeline.add_images import (
    get_images_dir,
    get_descriptions_path,
    compute_image_hash,
    load_image_descriptions,
    save_image_descriptions,
    save_raw_image,
    partition_new_vs_cached_images,
    describe_new_images,
    judge_images_by_macro,
    build_macro_search_queries,
    fetch_web_images,
    run_add_images,
    get_lesson_context,
)
from rt.llm.prompts import (
    build_image_description_user_prompt,
    build_image_descriptions_context_message,
    ImageDescription,
    ImageUnitJudgeResult,
)
from rt.llm.client import LLMClient
from rt.core.lesson_paths import lesson_path
from rt.core.idempotency import compute_source_fingerprint, compute_file_sha256, record_phase_fingerprint
from rt.pipeline.build import run_build, render_rielaborato_md
from rt.pipeline.outline import save_outline
from rt.pipeline.rewrite import save_draft
from rt.core.models import (
    Outline, OutlineMacro, OutlineUnit,
    Draft, DraftUnit,
    SegmentsData, Segment
)


def test_compute_image_hash():
    h1 = compute_image_hash(b"test image data")
    h2 = compute_image_hash(b"test image data")
    h3 = compute_image_hash(b"other data")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # sha256 hex string length


def test_load_save_descriptions(tmp_path):
    lesson_dir = str(tmp_path)
    assert load_image_descriptions(lesson_dir) == {}

    data = {
        "hash123": {
            "filename": "assets/images/hash123.png",
            "source": "pdf:slide.pdf#1",
            "slide_title": "Title",
            "ocr_text": "text",
            "visual_elements": "graph",
            "summary_keywords": ["k1"],
            "alt_text": "alt",
        }
    }
    save_image_descriptions(lesson_dir, data)
    assert os.path.isfile(get_descriptions_path(lesson_dir))
    loaded = load_image_descriptions(lesson_dir)
    assert loaded == data


def test_save_raw_image(tmp_path):
    lesson_dir = str(tmp_path)
    img_data = b"raw image bytes"
    img_hash = compute_image_hash(img_data)

    rel_path = save_raw_image(lesson_dir, img_data, img_hash, ext=".png")
    assert rel_path == f"assets/images/{img_hash[:16]}.png"
    full_path = os.path.join(lesson_dir, rel_path)
    assert os.path.isfile(full_path)
    with open(full_path, "rb") as f:
        assert f.read() == img_data

    # Save again (idempotent)
    rel_path_2 = save_raw_image(lesson_dir, img_data, img_hash, ext=".png")
    assert rel_path_2 == rel_path


def test_partition_new_vs_cached_images(tmp_path):
    lesson_dir = str(tmp_path)

    img1 = ExtractedImage(image_bytes=b"img 1", source_label="pdf:slide#1")
    img2 = ExtractedImage(image_bytes=b"img 2", source_label="pdf:slide#2")
    hash1 = compute_image_hash(img1.image_bytes)
    hash2 = compute_image_hash(img2.image_bytes)

    # Pre-populate descriptions with img1 cached
    save_image_descriptions(
        lesson_dir,
        {
            hash1: {
                "filename": "assets/images/hash1.png",
                "source": "pdf:slide#1",
                "alt_text": "cached img 1",
            }
        },
    )

    # Input has img1, img2, and duplicate of img1
    images = [img1, img2, ExtractedImage(image_bytes=b"img 1", source_label="pdf:slide#1_dup")]

    new_imgs, cached_imgs = partition_new_vs_cached_images(lesson_dir, images)

    assert len(cached_imgs) == 1
    assert cached_imgs[0][0] == hash1
    assert cached_imgs[0][1]["alt_text"] == "cached img 1"

    assert len(new_imgs) == 1
    assert new_imgs[0][0].source_label == "pdf:slide#2"
    assert new_imgs[0][1] == hash2


def test_build_image_description_user_prompt():
    prompt_with_ctx = build_image_description_user_prompt(context="BIOCHIMICA - Lipidi")
    assert "Contesto della lezione: BIOCHIMICA - Lipidi" in prompt_with_ctx

    prompt_no_ctx = build_image_description_user_prompt(context=None)
    assert "Contesto della lezione:" not in prompt_no_ctx


def test_call_structured_with_image_data_url():
    client = LLMClient(force_mock=True)
    res = client.call_structured(
        prompt="Descrivi",
        system_prompt="System",
        response_model=ImageDescription,
        job_name="image_description",
        image_data_url="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    )
    assert isinstance(res, ImageDescription)
    assert res.slide_title != ""


def test_describe_new_images(tmp_path):
    lesson_dir = str(tmp_path)
    (tmp_path / "info.yaml").write_text("materia: BIOCHIMICA\ntitolo: Lipidi\n")

    img_curated = ExtractedImage(image_bytes=b"curated bytes", source_label="pdf:slides.pdf#1")
    img_web = ExtractedImage(image_bytes=b"web bytes", source_label="websearch:query#1")
    h_curated = compute_image_hash(img_curated.image_bytes)
    h_web = compute_image_hash(img_web.image_bytes)

    new_images = [
        (img_curated, h_curated),
        (img_web, h_web),
    ]

    describe_new_images(lesson_dir, new_images, force_mock=True)

    desc_map = load_image_descriptions(lesson_dir)
    assert h_curated in desc_map
    assert h_web in desc_map
    assert desc_map[h_curated]["source"] == "pdf:slides.pdf#1"
    assert desc_map[h_web]["source"] == "websearch:query#1"
    assert os.path.isfile(os.path.join(lesson_dir, desc_map[h_curated]["filename"]))


def test_build_image_descriptions_context_message():
    desc = {
        "hash_b": {"slide_title": "B", "ocr_text": "text B", "visual_elements": [], "summary_keywords": [], "alt_text": "B"},
        "hash_a": {"slide_title": "A", "ocr_text": "text A", "visual_elements": [], "summary_keywords": [], "alt_text": "A"},
    }
    msg1 = build_image_descriptions_context_message(desc)
    msg2 = build_image_descriptions_context_message(desc)
    assert msg1 == msg2
    assert msg1.index("hash_a") < msg1.index("hash_b")


@dataclass
class MockUnit:
    id: str
    title: str
    key_concepts: List[str]

@dataclass
class MockMacro:
    id: str
    title: str
    units: List[MockUnit]

@dataclass
class MockOutline:
    macro_sections: List[MockMacro]


def test_judge_images_by_macro_empty(tmp_path):
    lesson_dir = str(tmp_path)
    outline = MockOutline(macro_sections=[MockMacro(id="1", title="M1", units=[])])
    res = judge_images_by_macro(lesson_dir, outline, force_mock=True)
    assert res == {}


def test_judge_images_by_macro_mock(tmp_path):
    lesson_dir = str(tmp_path)
    save_image_descriptions(
        lesson_dir,
        {
            "hash1": {"slide_title": "S1", "ocr_text": "T1", "visual_elements": [], "summary_keywords": [], "alt_text": "A1"}
        }
    )
    outline = MockOutline(
        macro_sections=[
            MockMacro(id="1", title="Macro 1", units=[MockUnit(id="1.1", title="U1.1", key_concepts=["c1"])]),
            MockMacro(id="2", title="Macro 2", units=[MockUnit(id="2.1", title="U2.1", key_concepts=["c2"])]),
        ]
    )
    res = judge_images_by_macro(lesson_dir, outline, force_mock=True)
    assert "1" in res
    assert "2" in res
    assert isinstance(res["1"], list)


def _synthetic_lesson(tmp_path, build: bool) -> str:
    """Lezione sintetica con prepare, outline e rewrite VALID; con build=True anche il
    documento finale."""
    from rt.core.manifest import init_or_update_manifest
    lesson_dir = str(tmp_path / "[2026-09-11] BIOCHIMICA - Lezione Test")
    os.makedirs(lesson_dir, exist_ok=True)
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    info_content = "data: '2026-09-11'\nmateria: BIOCHIMICA\nargomenti: Lipidi\nfase_corrente: completato\nstato: completato\n"
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write(info_content)

    seg_data = SegmentsData(segments=[
        Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text="Test", text_raw="Test")
    ])
    with open(lesson_path(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        f.write(seg_data.model_dump_json())

    with open(lesson_path(lesson_dir, "transcript_normalized.md"), "w", encoding="utf-8") as f:
        f.write("Transcript")

    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione Test",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Prima Sezione",
                units=[OutlineUnit(id="1.1", title="Unita Uno", start_segment_id="seg_000001", end_segment_id="seg_000001", key_concepts=["concetto"])]
            )
        ]
    )
    save_outline(outline, lesson_dir)

    draft = Draft(
        schema_version="1.0",
        units=[DraftUnit(unit_id="1.1", title="Unita Uno", start_segment_id="seg_000001", end_segment_id="seg_000001", source_segment_ids=["seg_000001"], content="Contenuto unita uno.")]
    )
    save_draft(draft, lesson_dir)

    init_or_update_manifest(lesson_dir, lesson_id="test", date="2026-09-11", subject="BIOCHIMICA",
                            current_state="draft_validato")
    for ph in ["prepare", "outline", "rewrite"]:
        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name=ph,
            source_fingerprint=compute_source_fingerprint(lesson_dir, ph),
            artifact_fingerprints={}
        )
    if build:
        run_build(lesson_dir, force=True)
    return lesson_dir


@pytest.fixture
def built_synthetic_lesson(tmp_path):
    return _synthetic_lesson(tmp_path, build=True)


@pytest.fixture
def drafted_synthetic_lesson(tmp_path):
    return _synthetic_lesson(tmp_path, build=False)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_run_add_images_requires_the_draft(tmp_path):
    unbuilt_dir = str(tmp_path / "unbuilt_lesson")
    os.makedirs(unbuilt_dir, exist_ok=True)
    with pytest.raises(RuntimeError) as exc_info:
        run_add_images(unbuilt_dir)
    assert "bozza" in str(exc_info.value)


def _add_one_image(lesson_dir, tmp_path, data: bytes, carousel: bool = False):
    from unittest.mock import patch
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir(exist_ok=True)
    (photos_dir / "slide1.png").write_bytes(data)
    h = compute_image_hash(data)
    with patch("rt.pipeline.add_images.judge_images_by_macro", side_effect=lambda *_a, **_k: {"1": [h]}):
        res = run_add_images(lesson_dir, input_path=str(photos_dir), carousel=carousel, force_mock=True)
    return h, res


def test_run_add_images_without_build_goes_in_preview_and_next_build(drafted_synthetic_lesson, tmp_path):
    """Senza build: le immagini finiscono nell'anteprima e il build successivo le include."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.pipeline.build import render_lesson_documents
    lesson_dir = drafted_synthetic_lesson
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.MISSING

    h, res = _add_one_image(lesson_dir, tmp_path, b"png slide bytes")
    assert res["images_added"] == 1
    assert res["macros_with_images"] == ["1"]
    assert res["build_stale"] is False
    assert not os.path.exists(lesson_path(lesson_dir, "rielaborato.md"))  # nessun documento finale scritto
    ref = f"assets/images/{h[:16]}.png"
    assert ref in render_lesson_documents(lesson_dir)["rielaborato"]

    build = run_build(lesson_dir)
    assert ref in _read(build["rielaborato"])
    assert ref in _read(build["named_file"])
    assert "assets/images" not in _read(build["pre_elaborato"])
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_run_add_images_after_build_makes_it_stale(built_synthetic_lesson, tmp_path):
    from rt.core.idempotency import PhaseStatus, check_phase_status
    lesson_dir = built_synthetic_lesson
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID
    final_before = _read(lesson_path(lesson_dir, "rielaborato.md"))

    h, res = _add_one_image(lesson_dir, tmp_path, b"png slide bytes")
    ref = f"assets/images/{h[:16]}.png"
    assert res["build_stale"] is True
    status, reason = check_phase_status(lesson_dir, "build")
    assert status == PhaseStatus.STALE
    assert "immagini" in reason
    assert _read(lesson_path(lesson_dir, "rielaborato.md")) == final_before  # finale intatto

    run_build(lesson_dir)
    assert ref in _read(lesson_path(lesson_dir, "rielaborato.md"))
    assert check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID


def test_run_add_images_carousel(drafted_synthetic_lesson, tmp_path):
    h, _res = _add_one_image(drafted_synthetic_lesson, tmp_path, b"png slide bytes 2", carousel=True)
    rielab_content = _read(run_build(drafted_synthetic_lesson)["rielaborato"])
    assert "```napkin-notes" in rielab_content
    assert f"[[assets/images/{h[:16]}.png]]" in rielab_content


def test_build_macro_search_queries():
    outline = MockOutline(
        macro_sections=[
            MockMacro(id="1", title="Macro 1", units=[MockUnit(id="1.1", title="U1.1", key_concepts=["K1", "K2", "K3", "K4"])]),
            MockMacro(id="2", title="Macro 2 (Senza KC)", units=[MockUnit(id="2.1", title="U2.1", key_concepts=[])]),
        ]
    )
    queries = build_macro_search_queries(outline)
    assert queries["1"] == "K1 K2 K3"
    assert queries["2"] == "Macro 2 (Senza KC)"


def test_fetch_web_images():
    outline = MockOutline(
        macro_sections=[
            MockMacro(id="1", title="M1", units=[MockUnit(id="1.1", title="U1", key_concepts=["K1"])]),
        ]
    )
    with pytest.raises(ValueError) as exc_info:
        fetch_web_images("dummy_dir", outline, total_count=3, base_url=None, force_mock=False)
    assert "searxng_base_url" in str(exc_info.value)

    web_imgs = fetch_web_images("dummy_dir", outline, total_count=3, base_url=None, force_mock=True)
    assert len(web_imgs) == 3
    assert web_imgs[0].source_label.startswith("websearch:")


def test_run_add_images_web_search(drafted_synthetic_lesson):
    res = run_add_images(drafted_synthetic_lesson, web_search_count=2, force_mock=True)
    assert os.path.isfile(res["placement"])
    assert res["images_added"] == 2

