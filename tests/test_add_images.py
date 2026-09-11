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
    get_lesson_context,
)
from rt.llm.prompts import (
    build_image_description_user_prompt,
    build_image_descriptions_context_message,
    ImageDescription,
    ImageUnitJudgeResult,
)
from rt.llm.client import LLMClient


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
    # Verify hash_a appears before hash_b due to sorted keys
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
