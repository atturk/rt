import os
import json
import pytest
from rt.core.image_extract import ExtractedImage
from rt.pipeline.add_images import (
    get_images_dir,
    get_descriptions_path,
    compute_image_hash,
    load_image_descriptions,
    save_image_descriptions,
    save_raw_image,
    partition_new_vs_cached_images,
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
