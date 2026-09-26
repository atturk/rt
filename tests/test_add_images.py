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
    build_unit_search_queries,
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


@pytest.fixture
def built_synthetic_lesson(tmp_path):
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

    for ph in ["prepare", "outline", "rewrite", "build"]:
        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name=ph,
            source_fingerprint=compute_source_fingerprint(lesson_dir, ph),
            artifact_fingerprints={}
        )

    run_build(lesson_dir, force=True)
    for ph in ["prepare", "outline", "rewrite", "build"]:
        record_phase_fingerprint(
            lesson_dir=lesson_dir,
            phase_name=ph,
            source_fingerprint=compute_source_fingerprint(lesson_dir, ph),
            artifact_fingerprints={}
        )
    return lesson_dir


def test_run_add_images_not_built(tmp_path):
    unbuilt_dir = str(tmp_path / "unbuilt_lesson")
    os.makedirs(unbuilt_dir, exist_ok=True)
    with pytest.raises(RuntimeError) as exc_info:
        run_add_images(unbuilt_dir)
    assert "non ha ancora completato la fase di build" in str(exc_info.value)


def test_run_add_images_end_to_end(built_synthetic_lesson, tmp_path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    (photos_dir / "slide1.png").write_bytes(b"png slide bytes")

    # Mock judge to return hash of slide1 for macro "1"
    h = compute_image_hash(b"png slide bytes")

    def mock_judge(lesson_dir, outline, force_mock=False):
        return {"1": [h]}

    from unittest.mock import patch
    with patch("rt.pipeline.add_images.judge_images_by_macro", side_effect=mock_judge):
        res = run_add_images(built_synthetic_lesson, input_path=str(photos_dir), force_mock=True)

    assert res["images_added"] == 1
    assert "1" in res["macros_with_images"]

    rielab_content = open(res["rielaborato_md"], "r", encoding="utf-8").read()
    deliverable_content = open(res["deliverable_md"], "r", encoding="utf-8").read()
    pre_content = open(lesson_path(built_synthetic_lesson, "pre-elaborato.md"), "r", encoding="utf-8").read()

    assert f"assets/images/{h[:16]}.png" in rielab_content
    assert f"assets/images/{h[:16]}.png" in deliverable_content
    assert "assets/images" not in pre_content


def test_run_add_images_plain_markdown_links(built_synthetic_lesson, tmp_path):
    """Niente carosello: le immagini sono link Markdown, una per riga, e basta."""
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    (photos_dir / "slide1.png").write_bytes(b"png slide bytes 2")
    (photos_dir / "slide2.png").write_bytes(b"png slide bytes 3")
    h1, h2 = compute_image_hash(b"png slide bytes 2"), compute_image_hash(b"png slide bytes 3")

    def mock_judge(lesson_dir, outline, force_mock=False):
        return {"1": [h1, h2]}

    from unittest.mock import patch
    with patch("rt.pipeline.add_images.judge_images_by_macro", side_effect=mock_judge):
        res = run_add_images(built_synthetic_lesson, input_path=str(photos_dir), force_mock=True)

    rielab_content = open(res["rielaborato_md"], "r", encoding="utf-8").read()
    assert "napkin-notes" not in rielab_content and "[[assets/images" not in rielab_content
    lines = rielab_content.splitlines()
    first = next(i for i, line in enumerate(lines) if f"assets/images/{h1[:16]}.png" in line)
    assert lines[first].startswith("![") and lines[first].endswith(f"(assets/images/{h1[:16]}.png)")
    assert lines[first + 1].startswith("![") and lines[first + 1].endswith(f"(assets/images/{h2[:16]}.png)")
    with pytest.raises(TypeError):
        run_add_images(built_synthetic_lesson, input_path=str(photos_dir), carousel=True, force_mock=True)


def test_build_unit_search_queries():
    outline = MockOutline(
        macro_sections=[
            MockMacro(id="1", title="Macro 1", units=[
                MockUnit(id="1.1", title="U1.1", key_concepts=["K1", "K2", "K3", "K4"]),
                MockUnit(id="1.2", title="Senza: KC", key_concepts=[]),
            ]),
            MockMacro(id="2", title="Macro 2", units=[MockUnit(id="2.1", title="U2.1", key_concepts=["K5", "K5"])]),
        ]
    )
    assert build_unit_search_queries(outline) == {"1.1": "K1 K2 K3", "1.2": "Senza  KC", "2.1": "K5"}
    assert build_unit_search_queries(outline, ["2.1", "1.1"]) == {"1.1": "K1 K2 K3", "2.1": "K5"}
    with pytest.raises(ValueError, match="9.9"):
        build_unit_search_queries(outline, ["1.1", "9.9"])


def test_fetch_web_images():
    outline = MockOutline(
        macro_sections=[
            MockMacro(id="1", title="M1", units=[MockUnit(id="1.1", title="U1", key_concepts=["K1"]),
                                                 MockUnit(id="1.2", title="U2", key_concepts=["K2"])]),
        ]
    )
    with pytest.raises(ValueError) as exc_info:
        fetch_web_images("dummy_dir", outline, per_unit=3, base_url=None, force_mock=False)
    assert "Impostazioni" in str(exc_info.value) and "general.yaml" not in str(exc_info.value)

    web_imgs, found = fetch_web_images("dummy_dir", outline, per_unit=3, base_url=None, force_mock=True)
    assert len(web_imgs) == 6 and found == {"1.1": 3, "1.2": 3}
    assert web_imgs[0].source_label.startswith("websearch:")
    assert web_imgs[0].image_bytes.startswith(b"\x89PNG")
    assert len({img.image_bytes for img in web_imgs}) == 6

    only, found = fetch_web_images("dummy_dir", outline, per_unit=2, force_mock=True, unit_ids=["1.2"])
    assert found == {"1.2": 2} and all("K2" in img.source_label for img in only)


def fake_searxng_server(results_per_query=10):
    """SearXNG finto: /search?format=json restituisce results_per_query immagini per query,
    servite dallo stesso server. server.queries registra le query ricevute."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse
    from rt.pipeline.add_images import _mock_png

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/search":
                q = parse_qs(url.query)["q"][0]
                self.server.queries.append(q)
                base = f"http://127.0.0.1:{self.server.server_address[1]}"
                body = _json.dumps({"results": [
                    {"img_src": f"{base}/img/{len(self.server.queries)}-{i}.png", "title": q, "url": base}
                    for i in range(results_per_query)]}).encode()
                ctype = "application/json"
            else:
                body, ctype = _mock_png(url.path), "image/png"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.queries = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_fetch_web_images_per_unit_with_fake_searxng():
    """N risultati per unità, una query per unità, solo sulle unità scelte."""
    outline = MockOutline(
        macro_sections=[
            MockMacro(id="1", title="M1", units=[MockUnit(id="1.1", title="U1", key_concepts=["Lipidi"]),
                                                 MockUnit(id="1.2", title="U2", key_concepts=["Steroidi"])]),
            MockMacro(id="2", title="M2", units=[MockUnit(id="2.1", title="U3", key_concepts=["Cere"])]),
        ]
    )
    server, url = fake_searxng_server()
    try:
        images, found = fetch_web_images("dummy_dir", outline, per_unit=2, base_url=url)
        assert server.queries == ["Lipidi", "Steroidi", "Cere"]
        assert found == {"1.1": 2, "1.2": 2, "2.1": 2} and len(images) == 6
        assert [img.source_label for img in images[:2]] == ["websearch:Lipidi"] * 2

        server.queries.clear()
        images, found = fetch_web_images("dummy_dir", outline, per_unit=3, base_url=url, unit_ids=["2.1", "1.1"])
        assert server.queries == ["Lipidi", "Cere"]
        assert found == {"1.1": 3, "2.1": 3} and len(images) == 6
    finally:
        server.shutdown()


def test_run_add_images_web_search(built_synthetic_lesson):
    res = run_add_images(built_synthetic_lesson, web_search_count=2, force_mock=True)
    assert "rielaborato_md" in res
    assert os.path.isfile(res["rielaborato_md"])

    from rt.pipeline.outline import load_outline
    units = [str(u.id) for m in load_outline(built_synthetic_lesson).macro_sections for u in m.units]
    assert res["web_images_by_unit"] == {u: 2 for u in units}

    first = units[0]
    res = run_add_images(built_synthetic_lesson, web_search_count=1, unit_ids=[first], force_mock=True)
    assert res["web_images_by_unit"] == {first: 1}
    with pytest.raises(ValueError):
        run_add_images(built_synthetic_lesson, web_search_count=1, unit_ids=["nessuna"], force_mock=True)
