import json
import os
from rt.services import lesson_service
from tests.api_support import isolated_workspace, make_lesson


def test_media_count_zero_and_n(tmp_path, monkeypatch, rt_db):
    ws = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = make_lesson(ws)

    # 1. 0 senza immagini
    summary = lesson_service.lesson_summary(1, lesson_dir)
    assert summary["media_count"] == 0
    assert lesson_service.count_lesson_images(lesson_dir) == 0

    # 2. N con N immagini
    from rt.pipeline.add_images import save_image_descriptions
    descriptions = {
        "hash1": {
            "filename": "assets/images/img1.png",
            "source": "websearch:cellula",
        },
        "hash2": {
            "filename": "assets/images/img2.jpg",
            "source": "editor:screenshot.jpg",
        },
        "hash3": {
            "filename": "assets/images/img3.webp",
            "source": "web:diagram",
        },
        "hash_ignored": {
            "filename": "assets/images/document.pdf",
            "source": "other",
        },
    }
    save_image_descriptions(lesson_dir, descriptions)

    summary = lesson_service.lesson_summary(1, lesson_dir)
    assert summary["media_count"] == 3
    assert lesson_service.count_lesson_images(lesson_dir) == 3
