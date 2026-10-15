"""
tests/test_api_images_mock.py
RT4-F6: endpoint delle immagini della lezione (elenco e file per l'anteprima), 'rt worker --mock'
e bot Telegram finto usati dai test end-to-end della SPA.
"""
import os
import subprocess
import sys

import pytest

from rt.services.jobs import DbJobQueue
from rt.services.worker import Worker, mock_payload
from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline
from tests.golden_support import AUDIO_FIXTURE, PROJECT_ROOT


@pytest.fixture
def ws(tmp_path, monkeypatch, rt_db):
    return isolated_workspace(tmp_path, monkeypatch)


def drain(worker, limit=10):
    done = 0
    while worker.run_once() is not None:
        done += 1
        assert done <= limit


def _lesson_id(client):
    return client.get("/api/v1/lessons").json()[0]["id"]


def _png(path):
    from PIL import Image
    Image.new("RGB", (24, 24), (200, 30, 30)).save(path, format="PNG")
    return path


def test_mock_payload_forces_mock_everywhere():
    assert mock_payload({"phase": "outline", "options": {"mock": False, "force": True}}) == {
        "phase": "outline", "options": {"mock": True, "force": True}, "mock": True, "force_mock": True}
    assert mock_payload({})["mock"] is True


def test_images_list_and_file(api_client, ws, rt_db, tmp_path, monkeypatch):
    from tests.api_support import mock_image_description_for_unit
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    mock_image_description_for_unit(monkeypatch, lesson)
    lid = _lesson_id(api_client)
    assert api_client.get(f"/api/v1/lessons/{lid}/images").json() == {"images": []}

    with open(_png(tmp_path / "slide.png"), "rb") as f:
        res = api_client.post(f"/api/v1/lessons/{lid}/images", files={"files": ("slide.png", f, "image/png")})
    assert res.status_code == 202
    # il client non chiede il mock: lo impone il worker, come 'rt worker --mock'
    drain(Worker(DbJobQueue(rt_db), worker_id="w", mock=True))
    assert api_client.get(f"/api/v1/jobs/{res.json()['job_id']}").json()["state"] == "succeeded"

    images = api_client.get(f"/api/v1/lessons/{lid}/images").json()["images"]
    assert len(images) == 1
    image = images[0]
    assert image["source"].startswith("folder:") and image["url"].endswith("/assets/images/" + image["name"])
    document = api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
    # La descrizione mock è pertinente: il mapping la mette nella sottounità candidata.
    assert image["in_document"] is True and f"assets/images/{image['name']}" in document

    served = api_client.get(image["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.content.startswith(b"\x89PNG")


@pytest.mark.parametrize("name", ["descriptions.json", "..%2Finfo.yaml", ".hidden.png", "nope.png"])
def test_image_file_rejects_other_files(api_client, ws, name):
    run_mock_pipeline(make_lesson(ws))
    lid = _lesson_id(api_client)
    res = api_client.get(f"/api/v1/lessons/{lid}/assets/images/{name}")
    assert res.status_code == 404


def test_voice_answer_in_mock_skips_stt(api_client, ws, rt_db):
    run_mock_pipeline(make_lesson(ws))
    lid = _lesson_id(api_client)
    worker = Worker(DbJobQueue(rt_db), worker_id="w", mock=True)
    assert api_client.post(f"/api/v1/lessons/{lid}/recall/generate", json={}).status_code == 202
    drain(worker)
    question = api_client.post(f"/api/v1/lessons/{lid}/recall/next", params={"qtype": "mirata"}).json()
    with open(AUDIO_FIXTURE, "rb") as f:
        res = api_client.post(f"/api/v1/lessons/{lid}/recall/answer-voice",
                              files={"audio": ("risposta.webm", f, "audio/webm")}, data={"question_id": question["id"]})
    assert res.status_code == 202
    drain(worker)
    job = api_client.get(f"/api/v1/jobs/{res.json()['job_id']}").json()
    assert job["state"] == "succeeded", job
    from rt.services.api_jobs import MOCK_VOICE_TRANSCRIPT
    answers = api_client.get(f"/api/v1/lessons/{lid}/recall/history").json()["answers"]
    voice = [a for a in answers if a["question_id"] == question["id"]]
    assert voice and voice[-1]["is_voice"] and voice[-1]["answer_text"] == MOCK_VOICE_TRANSCRIPT
    assert voice[-1]["evaluation"]


def test_fake_telegram_daemon_start_stop(tmp_path, monkeypatch):
    """RT_TELEGRAM_FAKE=1: 'rt telegram-daemon' prende il PID file senza contattare Telegram."""
    from rt.telegram import daemon_status as ds
    pid_path = str(tmp_path / "home" / ".rt" / "telegram_daemon.pid")
    env = {**os.environ, "HOME": str(tmp_path / "home"), "RT_TELEGRAM_FAKE": "1", "PYTHONPATH": PROJECT_ROOT}
    proc = subprocess.Popen([sys.executable, "-m", "rt.cli", "telegram-daemon"], cwd=PROJECT_ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        import time
        deadline = time.monotonic() + 20
        while ds.get_daemon_pid(pid_path) is None and time.monotonic() < deadline:
            assert proc.poll() is None, proc.stderr.read()
            time.sleep(0.1)
        assert ds.get_daemon_pid(pid_path) == proc.pid
        proc.terminate()
        assert proc.wait(timeout=10) == 0
        assert ds.get_daemon_pid(pid_path) is None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_web_search_requires_searxng_before_enqueue(api_client, ws, rt_db):
    """RT4-FA7: senza SearXNG l'errore arriva subito e rimanda alle Impostazioni."""
    run_mock_pipeline(make_lesson(ws))
    lid = _lesson_id(api_client)
    res = api_client.post(f"/api/v1/lessons/{lid}/images", data={"web_search": "2"})
    assert res.status_code == 409
    error = res.json()["error"]
    assert error["code"] == "searxng_not_configured"
    assert "Impostazioni" in error["message"] and "yaml" not in error["message"]
    assert api_client.get("/api/v1/jobs").json() == [] or all(
        j["type"] != "add_images" for j in api_client.get("/api/v1/jobs").json())


def test_web_search_per_unit_on_selected_units(api_client, ws, rt_db):
    """N immagini per unità, solo sulle unità scelte, passate nel payload del job."""
    with open(os.path.join("config", "general.yaml"), "a", encoding="utf-8") as f:
        f.write("searxng_base_url: http://127.0.0.1:9\n")
    run_mock_pipeline(make_lesson(ws))
    lid = _lesson_id(api_client)
    outline = api_client.get(f"/api/v1/lessons/{lid}/outline").json()
    units = [u["id"] for m in outline["macro_sections"] for u in m["units"]]
    chosen = units[:1]  # la lezione in mock ha una sola unità: la selezione multipla è in test_add_images

    res = api_client.post(f"/api/v1/lessons/{lid}/images", data={"web_search": "2", "units": ["nessuna"]})
    assert res.status_code == 422 and "nessuna" in res.json()["error"]["message"]
    assert api_client.post(f"/api/v1/lessons/{lid}/images", data={"web_search": "11"}).status_code == 422

    res = api_client.post(f"/api/v1/lessons/{lid}/images", data={"web_search": "2", "units": chosen})
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]
    job = api_client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["payload"]["unit_ids"] == chosen and job["payload"]["web_search_count"] == 2
    assert "carousel" not in job["payload"]
    drain(Worker(DbJobQueue(rt_db), worker_id="w", mock=True))
    job = api_client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "succeeded", job
    assert job["result"]["web_images_by_unit"] == {u: 2 for u in chosen}
    images = api_client.get(f"/api/v1/lessons/{lid}/images").json()["images"]
    assert len(images) == 2 and all(i["source"].startswith("websearch:") for i in images)
    document = api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
    assert "napkin-notes" not in document and document.count("](assets/images/") == 2


def test_material_pages_list_serve_and_copy(api_client, ws, rt_db, tmp_path):
    import json
    from rt.core.sources import Source, _save
    from rt.storage import fs

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = _lesson_id(api_client)

    # Crea una fonte materiale fittizia con due pagine
    impronta = "a" * 64
    source = Source(id="src-mat-1", tipo="materiale", file="slides.pdf", impronta=impronta, aggiunta_il="2026-10-15", ordine=1)
    _save(lesson, [source])

    mat_dir = os.path.join(lesson, "materials", impronta)
    fs.makedirs(mat_dir, exist_ok=True)
    _png(os.path.join(mat_dir, "page-1-1.png"))
    _png(os.path.join(mat_dir, "page-2-1.png"))
    pages = [
        {"numero": 1, "testo": "Testo slide 1", "immagini": [f"materials/{impronta}/page-1-1.png"]},
        {"numero": 2, "testo": "Testo slide 2", "immagini": [f"materials/{impronta}/page-2-1.png"]},
    ]
    with fs.open(os.path.join(mat_dir, "pages.json"), "w", encoding="utf-8") as f:
        json.dump({"impronta": impronta, "pages": pages}, f)

    # 1. Elenco include le pagine dei materiali non ancora in assets
    res = api_client.get(f"/api/v1/lessons/{lid}/images").json()
    images = res["images"]
    assert len(images) == 2
    img1 = images[0]
    assert img1["source_name"] == "slides.pdf"
    assert img1["page"] == 1
    assert img1["in_assets"] is False
    assert img1["in_document"] is False
    assert img1["url"] == f"/api/v1/lessons/{lid}/materials/{impronta}/page-1-1.png"

    # 2. Servire il file della pagina direttamente da materials/
    served = api_client.get(img1["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content.startswith(b"\x89PNG")

    # 3. Copia della pagina 1 in assets/images
    copy_res = api_client.post(
        f"/api/v1/lessons/{lid}/media/material-page",
        json={"source_id": "src-mat-1", "page": 1},
    )
    assert copy_res.status_code == 201
    asset_img = copy_res.json()
    assert asset_img["path"].startswith("assets/images/")
    assert asset_img["alt_text"] == "slides.pdf, pagina 1"

    # Ora la pagina 1 risulta in_assets=True
    res2 = api_client.get(f"/api/v1/lessons/{lid}/images").json()
    images2 = res2["images"]
    assert len(images2) == 2
    assert images2[0]["in_assets"] is True
    assert images2[0]["source"].startswith("material:src-mat-1:1")
    assert images2[0]["url"].endswith(asset_img["name"])
    assert images2[1]["in_assets"] is False


def test_remove_from_text_removes_from_doc_and_placement_without_touching_history_or_assets(api_client, ws):
    from rt.storage import fs
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = _lesson_id(api_client)
    from rt.pipeline.image_placement import save_image_placement

    # Setup file assets/images
    images_dir = os.path.join(lesson, "assets", "images")
    fs.makedirs(images_dir, exist_ok=True)
    img1_file = os.path.join(images_dir, "img_keep.png")
    img2_file = os.path.join(images_dir, "img_remove.png")
    _png(img1_file)
    _png(img2_file)

    # Setup document.md
    doc_path = os.path.join(lesson, "document.md")
    with fs.open(doc_path, "w", encoding="utf-8") as f:
        f.write("# Titolo\n\n![Img1](assets/images/img_keep.png)\n\nTesto normale\n\n![Img2](assets/images/img_remove.png)\n")

    # Setup placement.json
    save_image_placement(lesson, macros={"1": ["img_keep", "img_remove"]}, carousel=False, units={"1.1": ["img_remove"]})

    # Setup dummy history file
    hist_dir = os.path.join(lesson, "history", "v1")
    fs.makedirs(hist_dir, exist_ok=True)
    hist_file = os.path.join(hist_dir, "snapshot.txt")
    with fs.open(hist_file, "w", encoding="utf-8") as f:
        f.write("history snapshot")

    # Chiama remove-from-text
    res = api_client.post(
        f"/api/v1/lessons/{lid}/media/remove-from-text",
        json={"image_names": ["img_remove.png"]},
    )
    assert res.status_code == 200

    # Verifica document.md
    with fs.open(doc_path, "r", encoding="utf-8") as f:
        new_doc = f.read()
    assert "img_remove.png" not in new_doc
    assert "img_keep.png" in new_doc
    assert "Testo normale" in new_doc

    # Verifica placement.json
    from rt.pipeline.image_placement import load_image_placement
    placement = load_image_placement(lesson)
    assert "img_remove" not in placement["macros"].get("1", [])
    assert "img_keep" in placement["macros"].get("1", [])
    assert "img_remove" not in placement["units"].get("1.1", [])

    # Verifica che il file originale in assets NON sia stato cancellato
    assert fs.isfile(img2_file)

    # Verifica che history sia intatta
    assert fs.isfile(hist_file)
    with fs.open(hist_file, "r", encoding="utf-8") as f:
        assert f.read() == "history snapshot"


