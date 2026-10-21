"""
tests/test_export_pdf.py
Piano 3: Esporta PDF della lezione.
- Ridimensionamento immagini a max 1600 px sul lato lungo (?max=1600), scelta tra JPEG e PNG, cache su disco.
- GET /lessons/{id}/export?format=pdf con browser simulato (cookie di sessione, rotta di stampa, 409 browser missing).
- Rendering PDF vero con Chromium (se disponibile): 3 immagini, nessuna più larga di 1600 px.
"""
import io
import os
import shutil
import threading
import time
from unittest.mock import MagicMock

import pytest
from PIL import Image

from rt.api import auth
from rt.api.app import create_app
from rt.api.routers import lessons as lessons_router
from rt.core.lesson_paths import lesson_path
from rt.llm.enrichment_media import BrowserMissingError, find_capture_browser_executable
from rt.storage import fs
from rt.storage.export import final_markdown_name, lesson_file_names
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def test_image_resize_max_1600_and_cache(api_client, ws, monkeypatch):
    """?max=1600 riduce a 1600 px sul lato lungo, sceglie JPEG per una foto e PNG per
    un'immagine con trasparenza, e usa la cache la seconda volta."""
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    images_dir = os.path.join(lesson, "assets", "images")
    os.makedirs(images_dir, exist_ok=True)

    # 1. Foto-like 3000x1700: JPEG qualità 82 pesa molto meno di PNG -> scelta JPEG
    photo_raw = os.urandom(3000 * 1700 * 3)
    photo_img = Image.frombytes("RGB", (3000, 1700), photo_raw)
    photo_path = os.path.join(images_dir, "photo.png")
    photo_img.save(photo_path, format="PNG")

    res_photo = api_client.get(f"/api/v1/lessons/{lid}/assets/images/photo.png?max=1600")
    assert res_photo.status_code == 200
    assert res_photo.headers["content-type"] == "image/jpeg"
    im_photo = Image.open(io.BytesIO(res_photo.content))
    assert max(im_photo.size) == 1600
    assert im_photo.size == (1600, 907)

    # Verifica presenza file in cache
    cache_dir = os.path.join(fs.data_dir(), "cache", "pdf-images")
    assert os.path.isdir(cache_dir)
    cached_files = [f for f in os.listdir(cache_dir) if f.endswith("-1600.jpg")]
    assert len(cached_files) == 1

    # Seconda richiesta: servita dalla cache
    res_photo_cache = api_client.get(f"/api/v1/lessons/{lid}/assets/images/photo.png?max=1600")
    assert res_photo_cache.status_code == 200
    assert res_photo_cache.headers["content-type"] == "image/jpeg"
    assert res_photo_cache.content == res_photo.content

    # 2. Immagine con trasparenza 3000x1700 -> scelta PNG
    transp_img = Image.new("RGBA", (3000, 1700), (50, 100, 150, 128))
    transp_path = os.path.join(images_dir, "transp.png")
    transp_img.save(transp_path, format="PNG")

    res_transp = api_client.get(f"/api/v1/lessons/{lid}/assets/images/transp.png?max=1600")
    assert res_transp.status_code == 200
    assert res_transp.headers["content-type"] == "image/png"
    im_transp = Image.open(io.BytesIO(res_transp.content))
    assert max(im_transp.size) == 1600
    assert im_transp.size == (1600, 907)
    assert im_transp.mode in ("RGBA", "LA", "P")


def test_export_lesson_pdf_with_simulated_browser(api_client, ws, monkeypatch):
    """format=pdf con page.pdf simulato apre la rotta di stampa con il cookie di sessione
    e restituisce application/pdf con il nome giusto; chiude la sessione."""
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]

    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    simulated_pdf = b"%PDF-1.4 simulated pdf document"
    mock_page.pdf.return_value = simulated_pdf

    created_sessions = []
    dropped_sessions = []
    orig_create_session = auth.create_session
    orig_drop_session = auth.drop_session

    def tracked_create_session(*args, **kwargs):
        sid = orig_create_session(*args, **kwargs)
        created_sessions.append(sid)
        return sid

    def tracked_drop_session(sid):
        dropped_sessions.append(sid)
        orig_drop_session(sid)

    monkeypatch.setattr(auth, "create_session", tracked_create_session)
    monkeypatch.setattr(auth, "drop_session", tracked_drop_session)
    monkeypatch.setattr("rt.llm.enrichment_media.launch_capture_browser", lambda p, **kw: mock_browser)

    res = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == simulated_pdf

    # Nome file derivato dal Markdown finale
    from urllib.parse import unquote
    disposition = unquote(res.headers.get("content-disposition", ""))
    assert ".pdf" in disposition
    assert "[2026-09-05]" in disposition

    # Sessione creata, usata nei cookie e poi eliminata
    assert len(created_sessions) == 1
    session_id = created_sessions[0]
    assert dropped_sessions == [session_id]

    mock_context.add_cookies.assert_called_once_with([{
        "name": auth.SESSION_COOKIE,
        "value": session_id,
        "url": "http://127.0.0.1:8000",
    }])
    mock_page.goto.assert_called_once_with(f"http://127.0.0.1:8000/lezioni/{lid}/stampa", wait_until="commit")
    mock_page.wait_for_selector.assert_called_once_with('body[data-ready="1"]', timeout=60000)
    assert mock_page.pdf.called


def test_export_lesson_pdf_browser_missing_returns_409(api_client, ws, monkeypatch):
    """Senza browser risponde 409 pdf_browser_missing."""
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]

    def fail_browser(p, **kw):
        raise BrowserMissingError("No browser available")

    monkeypatch.setattr("rt.llm.enrichment_media.launch_capture_browser", fail_browser)

    res = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res.status_code == 409
    data = res.json()
    assert data["error"]["code"] == "pdf_browser_missing"
    assert "Il browser per il PDF si sta ancora scaricando" in data["error"]["message"]


def test_export_lesson_real_pdf_with_three_images(ws, monkeypatch):
    """(se Chromium è disponibile, altrimenti salta) un PDF vero di una lezione finta con tre immagini:
    tre immagini nel PDF, nessuna più larga di 1600 px."""
    from playwright.sync_api import sync_playwright
    import uvicorn

    try:
        with sync_playwright() as p:
            if not find_capture_browser_executable(p):
                pytest.skip("Chromium non disponibile in questo ambiente")
    except Exception:
        pytest.skip("Playwright non disponibile")

    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf non disponibile")

    from rt.core.paths import find_spa_dir
    if not find_spa_dir():
        pytest.skip("build della web app non disponibile (serve la rotta di stampa)")

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)

    # Crea 3 immagini grandi (2000x1000)
    images_dir = os.path.join(lesson, "assets", "images")
    os.makedirs(images_dir, exist_ok=True)
    for i in range(1, 4):
        img = Image.new("RGB", (2000, 1000), (40 * i, 80, 120))
        img.save(os.path.join(images_dir, f"slide{i}.png"))

    img_markdown = (
        "\n\n![slide 1 pagina 1](assets/images/slide1.png)"
        "\n\n![slide 2 pagina 2](assets/images/slide2.png)"
        "\n\n![slide 3](assets/images/slide3.png)\n"
    )

    # Aggiorna rielaborato.md e il file deliverable
    lp = lesson_path(lesson, "rielaborato.md")
    if os.path.isfile(lp):
        with open(lp, "a", encoding="utf-8") as f:
            f.write(img_markdown)

    names = lesson_file_names(lesson)
    final = final_markdown_name(names)
    if final and os.path.isfile(names[final]):
        with open(names[final], "a", encoding="utf-8") as f:
            f.write(img_markdown)

    from rt.services.lesson_service import ensure_indexed, list_lessons
    ensure_indexed([lesson])
    lid = list_lessons()[0]["id"]

    # Avvia uvicorn su porta libera per servire SPA e API
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(create_app(serve_spa=True), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    try:
        pdf_bytes = lessons_router._render_pdf(lid, port)
        assert len(pdf_bytes) > 1000
        assert pdf_bytes.startswith(b"%PDF")

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        imgs = [doc.extract_image(img[0]) for pg in doc for img in pg.get_images()]
        assert len(imgs) == 3
        for im in imgs:
            assert im["width"] <= 1600
            assert im["height"] <= 1600
    finally:
        server.should_exit = True
        thread.join(timeout=5)
