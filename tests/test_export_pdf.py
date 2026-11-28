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
        "url": "http://127.0.0.1:80",
    }])
    # La porta è quella su cui ascolta il server (TestClient: 80), non quella dell'URL.
    mock_page.goto.assert_called_once_with(f"http://127.0.0.1:80/lezioni/{lid}/stampa", wait_until="commit")
    mock_page.wait_for_selector.assert_called_once_with('body[data-ready="1"]', timeout=60000)
    assert mock_page.pdf.called


def test_export_pdf_without_rt_qr_when_preference_is_off(api_client, ws, monkeypatch):
    """Con pdf.qr-sito = false il PDF esce senza timbro: niente seconda pagina di stampa."""
    from rt.services.preferences_service import save_preference

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    mock_browser = MagicMock()
    mock_page = mock_browser.new_context.return_value.new_page.return_value
    mock_page.pdf.return_value = b"%PDF-1.4 senza qr"
    monkeypatch.setattr("rt.llm.enrichment_media.launch_capture_browser", lambda p, **kw: mock_browser)

    save_preference(lessons_router.PDF_QR_PREFERENCE, False)
    res = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 senza qr"
    mock_page.evaluate.assert_not_called()
    mock_page.set_content.assert_not_called()
    assert mock_page.pdf.call_count == 1


def test_pdf_uses_the_local_port_behind_tailscale_serve():
    """Da https://mac.ts.net (Tailscale Serve) l'URL non ha porta: conta quella del server."""
    from starlette.requests import Request
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"mac.tailnet.ts.net")],
             "scheme": "https", "server": ("127.0.0.1", 8765), "query_string": b""}
    assert lessons_router._local_port(Request(scope)) == 8765
    scope_without_server = {**scope, "server": None}
    assert lessons_router._local_port(Request(scope_without_server)) == 8765  # DEFAULT_PORT


def test_export_lesson_pdf_print_page_timeout_returns_504(api_client, ws, monkeypatch):
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    mock_browser = MagicMock()
    page = mock_browser.new_context.return_value.new_page.return_value
    page.wait_for_selector.side_effect = TimeoutError("Timeout 60000ms exceeded")
    monkeypatch.setattr("rt.llm.enrichment_media.launch_capture_browser", lambda p, **kw: mock_browser)
    res = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res.status_code == 504
    assert res.json()["error"]["code"] == "pdf_timeout"
    mock_browser.close.assert_called_once()


def test_export_lesson_pdf_browser_missing_returns_409(api_client, ws, tmp_path, monkeypatch):
    """Senza browser avvia il download una sola volta e risponde 409 pdf_browser_missing."""
    from rt.core import components
    from rt.llm import enrichment_media

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "browsers"))
    monkeypatch.setattr(components, "browser_available", lambda: True)
    monkeypatch.setattr(enrichment_media, "detect_system_browser", lambda: None)

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]

    def fail_browser(p, **kw):
        raise BrowserMissingError("No browser available")

    monkeypatch.setattr("rt.llm.enrichment_media.launch_capture_browser", fail_browser)

    started = []

    def fake_start_download(cid):
        started.append(cid)
        components._write_component_state(cid, {
            "state": "downloading",
            "auto_resume": True,
            "pid": os.getpid(),
            "error": None,
        })
        return {**components.get_component(cid), "state": "downloading"}

    monkeypatch.setattr(components, "start_download", fake_start_download)

    res = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res.status_code == 409
    data = res.json()
    assert data["error"]["code"] == "pdf_browser_missing"
    assert data["error"]["message"] == (
        "Per il PDF serve un browser: sto scaricando il browser minimo (circa 110 MB). "
        "Vedi l'avanzamento in Impostazioni › Lavorazione delle lezioni › Componenti, poi riprova."
    )
    assert started == [components.BROWSER_ID]

    # Seconda richiesta mentre è già attivo/scaricando (lock simulato): non riavvia il download
    monkeypatch.setattr(components, "is_download_active", lambda cid: cid == components.BROWSER_ID)
    res2 = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res2.status_code == 409
    assert started == [components.BROWSER_ID]

    # Stato paused -> dice che è in pausa
    monkeypatch.setattr(components, "is_download_active", lambda _cid: False)
    components._write_component_state(components.BROWSER_ID, {"state": "paused", "auto_resume": False, "error": None})
    res_paused = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res_paused.status_code == 409
    assert "in pausa" in res_paused.json()["error"]["message"]
    assert started == [components.BROWSER_ID]

    # Stato error -> dice che è in errore
    components._write_component_state(components.BROWSER_ID, {"state": "error", "auto_resume": False, "error": "rete giù"})
    res_err = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res_err.status_code == 409
    assert "non è riuscito" in res_err.json()["error"]["message"]
    assert "rete giù" in res_err.json()["error"]["message"]
    assert started == [components.BROWSER_ID]


def test_export_lesson_pdf_browser_failed_to_launch_returns_500(api_client, ws, tmp_path, monkeypatch):
    """Se un browser esisteva ma non si avvia, restituisce 500 pdf_browser_failed senza avviare download."""
    from rt.core import components

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "browsers"))
    started = []
    monkeypatch.setattr(components, "start_download", lambda cid: started.append(cid))
    monkeypatch.setattr(
        "rt.llm.enrichment_media.launch_capture_browser",
        lambda p, **kw: (_ for _ in ()).throw(RuntimeError("crash. Scarica il browser minimo da Impostazioni › Lavorazione delle lezioni › Componenti")),
    )

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]

    res = api_client.get(f"/api/v1/lessons/{lid}/export?format=pdf")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "pdf_browser_failed"
    assert "Impostazioni › Lavorazione delle lezioni › Componenti" in res.json()["error"]["message"]
    assert started == []


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
        + "".join(f"\n\nParagrafo di verifica impaginazione {i}. " * 12 for i in range(18))
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
        assert doc.page_count >= 2
        imgs = [doc.extract_image(img[0]) for pg in doc for img in pg.get_images()]
        assert len(imgs) == 3
        for im in imgs:
            assert im["width"] <= 1600
            assert im["height"] <= 1600

        p1_text = doc[0].get_text()
        p2_text = doc[1].get_text()
        assert "Rielaborato con RT" in p1_text
        assert "Rielaborato con RT" not in p2_text
        p1_uris = [lnk.get("uri", "") for lnk in doc[0].get_links()]
        p2_uris = [lnk.get("uri", "") for lnk in doc[1].get_links()]
        assert any("atturk.github.io/rt" in u for u in p1_uris)
        assert not any("atturk.github.io/rt" in u for u in p2_uris)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_stamp_first_page_overlays_only_page_one_and_preserves_text_and_link():
    pymupdf = pytest.importorskip("pymupdf")

    base = pymupdf.open()
    p1 = base.new_page(width=595, height=842)
    p1.insert_text((72, 100), "Contenuto prima pagina")
    p2 = base.new_page(width=595, height=842)
    p2.insert_text((72, 100), "Contenuto seconda pagina")
    base_bytes = base.tobytes()

    stamp = pymupdf.open()
    sp = stamp.new_page(width=595, height=842)
    sp.insert_text((420, 30), "Rielaborato con RT")
    sp.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": pymupdf.Rect(420, 15, 540, 45),
        "uri": "https://atturk.github.io/rt/",
    })
    stamp_bytes = stamp.tobytes()

    out_bytes = lessons_router._stamp_first_page(base_bytes, stamp_bytes)
    out = pymupdf.open(stream=out_bytes, filetype="pdf")
    assert out.page_count == 2
    assert "Contenuto prima pagina" in out[0].get_text()
    assert "Rielaborato con RT" in out[0].get_text()
    assert any("atturk.github.io/rt" in lnk.get("uri", "") for lnk in out[0].get_links())
    assert "Contenuto seconda pagina" in out[1].get_text()
    assert "Rielaborato con RT" not in out[1].get_text()
    assert not any("atturk.github.io/rt" in lnk.get("uri", "") for lnk in out[1].get_links())


def test_stamp_first_page_inserts_fallback_link_if_stamp_has_no_links():
    pymupdf = pytest.importorskip("pymupdf")

    base = pymupdf.open()
    base.new_page(width=595, height=842).insert_text((72, 100), "Pagina")
    stamp = pymupdf.open()
    stamp.new_page(width=595, height=842).insert_text((420, 30), "Rielaborato con RT")

    out_bytes = lessons_router._stamp_first_page(base.tobytes(), stamp.tobytes())
    out = pymupdf.open(stream=out_bytes, filetype="pdf")
    uris = [lnk.get("uri", "") for lnk in out[0].get_links()]
    assert lessons_router.RT_SITE_URL in uris


def test_stamp_first_page_returns_original_pdf_on_error(caplog):
    pymupdf = pytest.importorskip("pymupdf")

    base = pymupdf.open()
    base.new_page(width=595, height=842).insert_text((72, 100), "Originale")
    original = base.tobytes()

    with caplog.at_level("WARNING"):
        res = lessons_router._stamp_first_page(original, b"not-a-valid-pdf")
    assert res == original
    assert any("timbro QR" in rec.message for rec in caplog.records)
