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

    # 3. Copia della pagina 1 in assets/images, anche con l'editor aperto (non tocca il testo)
    assert api_client.post(f"/api/v1/lessons/{lid}/document/lease").status_code == 200
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

    # 4. Ritaglio di una pagina non ancora in assets
    crop = api_client.post(f"/api/v1/lessons/{lid}/media/crop",
                           json={"image_name": "material:src-mat-1:1", "rect": [0, 0, 0.5, 0.5]})
    assert crop.status_code == 201, crop.text
    assert crop.json()["alt_text"] == "Pag. 1 · ritaglio 1"


def _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch):
    """Lezione vera con un'immagine collocata dall'Arricchimento nel documento."""
    from tests.api_support import mock_image_description_for_unit
    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    mock_image_description_for_unit(monkeypatch, lesson)
    lid = _lesson_id(api_client)
    from PIL import Image
    Image.new("RGB", (100, 60), (50, 100, 150)).save(tmp_path / "slide.png", format="PNG")
    with open(tmp_path / "slide.png", "rb") as f:
        api_client.post(f"/api/v1/lessons/{lid}/images", files={"files": ("slide.png", f, "image/png")})
    drain(Worker(DbJobQueue(rt_db), worker_id="w", mock=True))
    image = api_client.get(f"/api/v1/lessons/{lid}/images").json()["images"][0]
    assert f"assets/images/{image['name']}" in api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
    return lesson, lid, image["name"]


def _placement_hashes(lesson):
    from rt.pipeline.image_placement import load_image_placement
    placement = load_image_placement(lesson) or {}
    return {h for group in ("macros", "units") for v in placement.get(group, {}).values() for h in v}


def test_remove_from_text_removes_from_doc_and_placement_without_touching_history_or_assets(
        api_client, ws, rt_db, tmp_path, monkeypatch):
    from rt.pipeline.add_images import load_image_descriptions
    lesson, lid, name = _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch)
    image_hash = next(h for h, d in load_image_descriptions(lesson).items() if d["filename"].endswith(name))
    assert image_hash in _placement_hashes(lesson)
    history = os.path.join(lesson, "history")
    before = sorted(os.listdir(history)) if os.path.isdir(history) else []

    res = api_client.post(f"/api/v1/lessons/{lid}/media/remove-from-text", json={"image_names": [name]})
    assert res.status_code == 200, res.text

    assert name not in api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
    assert image_hash not in _placement_hashes(lesson)
    assert os.path.isfile(os.path.join(lesson, "assets", "images", name))
    listed = api_client.get(f"/api/v1/lessons/{lid}/images").json()["images"]
    assert any(i["name"] == name and not i["in_document"] for i in listed)
    # le fotografie esistenti restano; il salvataggio ne aggiunge al più una nuova
    after = sorted(os.listdir(history)) if os.path.isdir(history) else []
    assert set(before) <= set(after)


def test_remove_from_text_respects_editor_lease(api_client, ws, rt_db, tmp_path, monkeypatch):
    lesson, lid, name = _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch)
    assert api_client.post(f"/api/v1/lessons/{lid}/document/lease").status_code == 200
    res = api_client.post(f"/api/v1/lessons/{lid}/media/remove-from-text", json={"image_names": [name]})
    assert res.status_code == 409
    assert name in api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]



def test_auto_place_selected_images_preserves_existing_placements(api_client, ws):
    import json
    from rt.storage import fs
    from rt.pipeline.image_placement import save_image_placement, load_image_placement
    from rt.pipeline.add_images import (
        run_add_images, load_image_descriptions, save_image_descriptions,
        compute_image_hash, save_raw_image,
    )
    from rt.core.sources import Source, _save

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)
    lid = _lesson_id(api_client)

    # 1. Posizionamento pre-esistente
    save_image_placement(
        lesson,
        macros={"1": ["preexisting_macro_hash"]},
        carousel=False,
        units={"1.1": ["preexisting_unit_hash"]},
    )

    # 2. Immagine già in assets con descrizione
    from rt.pipeline.outline import load_outline
    unit_title = load_outline(lesson).macro_sections[0].units[0].title
    img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    h1 = compute_image_hash(img_bytes)
    rel1 = save_raw_image(lesson, img_bytes, h1)
    descriptions = load_image_descriptions(lesson)
    descriptions[h1] = {
        "filename": rel1,
        "source": "editor:test.png",
        "alt_text": "Test Image 1",
        "ocr_text": unit_title,
    }
    save_image_descriptions(lesson, descriptions)

    # 3. Pagina dei materiali non ancora in assets
    impronta = "b" * 64
    source = Source(id="src-mat-2", tipo="materiale", file="slides2.pdf", impronta=impronta, aggiunta_il="2026-10-15", ordine=1)
    _save(lesson, [source])
    mat_dir = os.path.join(lesson, "materials", impronta)
    fs.makedirs(mat_dir, exist_ok=True)
    _png(os.path.join(mat_dir, "page-1-1.png"))
    pages = [
        {"numero": 1, "testo": unit_title, "immagini": [f"materials/{impronta}/page-1-1.png"]},
    ]
    with fs.open(os.path.join(mat_dir, "pages.json"), "w", encoding="utf-8") as f:
        json.dump({"impronta": impronta, "pages": pages}, f)

    # Colloca in automatico solo le selezionate (una in assets, una da materiale)
    mat_page_name = "material:src-mat-2:1"  # il nome che la griglia manda per le pagine non in assets
    res = run_add_images(
        lesson,
        selected_images=[os.path.basename(rel1), mat_page_name],
        force_mock=True,
    )
    assert res["images_added"] >= 1

    # Verifica placement: i preesistenti DEVONO rimanere intatti
    placement = load_image_placement(lesson)
    assert "preexisting_macro_hash" in placement["macros"].get("1", [])
    assert "preexisting_unit_hash" in placement["units"].get("1.1", [])

    # Verifica che la pagina del materiale sia stata copiata in assets/images
    descriptions_after = load_image_descriptions(lesson)
    mat_entry = next((d for d in descriptions_after.values() if "material:src-mat-2:1" in d.get("source", "")), None)
    assert mat_entry is not None
    assert fs.isfile(os.path.join(lesson, mat_entry["filename"]))

    # 4. Verifica endpoint API POST /lessons/{lesson_id}/images con selected_images
    api_res = api_client.post(
        f"/api/v1/lessons/{lid}/images",
        data={"selected_images": [os.path.basename(rel1)]},
    )
    assert api_res.status_code == 202
    assert "job_id" in api_res.json()


def test_pages_only_mode_without_llm_calls(ws, monkeypatch):
    from rt.pipeline.add_images import run_add_images, load_image_descriptions
    from rt.pipeline.image_placement import load_image_placement
    import rt.llm.client as llm_client

    lesson = make_lesson(ws)
    run_mock_pipeline(lesson)

    # Se un modello LLM venisse chiamato, solleva errore
    def fake_llm(*args, **kwargs):
        raise AssertionError("Nessun modello LLM deve essere chiamato in modalità Solo pagine!")
    monkeypatch.setattr(llm_client.LLMClient, "call_structured", fake_llm)

    # Crea un file immagine di prova
    img_dir = os.path.join(lesson, "upload_test")
    os.makedirs(img_dir, exist_ok=True)
    _png(os.path.join(img_dir, "foto1.png"))

    res = run_add_images(lesson, input_path=img_dir, pages_only=True)
    assert res["images_added"] == 1
    assert res["placement_changed"] is False

    # Verifica che l'immagine sia salvata in assets/images
    descriptions = load_image_descriptions(lesson)
    assert len(descriptions) >= 1

    # Verifica che placement.json NON sia stato modificato con nuove collocazioni
    placement = load_image_placement(lesson) or {}
    assert placement.get("macros", {}) == {}
    assert placement.get("units", {}) == {}


def test_crop_media_image_as_new_image(api_client, ws, rt_db, tmp_path, monkeypatch):
    from PIL import Image
    from rt.pipeline.add_images import load_image_descriptions
    lesson, lid, name = _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch)
    url = f"/api/v1/lessons/{lid}/media/crop"

    first = api_client.post(url, json={"image_name": name, "rect": [0.1, 0.1, 0.5, 0.5]})
    assert first.status_code == 201, first.text
    assert first.json()["alt_text"].endswith("ritaglio 1")
    with Image.open(os.path.join(lesson, first.json()["path"])) as cropped:
        assert cropped.size == (50, 30)
    # stesso riquadro: stessa immagine, il nome non cambia
    again = api_client.post(url, json={"image_name": name, "rect": [0.1, 0.1, 0.5, 0.5]})
    assert again.json()["name"] == first.json()["name"] and again.json()["alt_text"] == first.json()["alt_text"]
    # un altro riquadro e il ritaglio di un ritaglio contano sulla stessa pagina
    second = api_client.post(url, json={"image_name": name, "rect": [0.0, 0.0, 0.3, 0.3]})
    assert second.json()["alt_text"].endswith("ritaglio 2")
    third = api_client.post(url, json={"image_name": first.json()["name"], "rect": [0.0, 0.0, 0.5, 0.5]})
    assert third.json()["alt_text"].endswith("ritaglio 3")
    # l'originale resta nel testo, invariato
    assert name in api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
    original = next(d for d in load_image_descriptions(lesson).values() if d["filename"].endswith(name))
    assert "crop_of" not in original


@pytest.mark.parametrize("rect", [[0.1], [1.0, 0.0, 0.5, 0.5], [0.0, 0.0, 0.0, 0.5]])
def test_crop_rejects_invalid_rect(api_client, ws, rt_db, tmp_path, monkeypatch, rect):
    _lesson, lid, name = _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch)
    res = api_client.post(f"/api/v1/lessons/{lid}/media/crop", json={"image_name": name, "rect": rect})
    assert res.status_code in (400, 422)


def test_crop_media_image_replace(api_client, ws, rt_db, tmp_path, monkeypatch):
    from rt.pipeline.add_images import load_image_descriptions
    lesson, lid, name = _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch)
    old_hash = next(h for h, d in load_image_descriptions(lesson).items() if d["filename"].endswith(name))
    res = api_client.post(f"/api/v1/lessons/{lid}/media/crop",
                          json={"image_name": name, "rect": [0.2, 0.2, 0.5, 0.5], "replace": True})
    assert res.status_code == 201, res.text
    crop = res.json()
    assert crop["alt_text"].endswith("(ritagliata)")
    document = api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
    assert crop["path"] in document and f"assets/images/{name}" not in document
    hashes = _placement_hashes(lesson)
    assert old_hash not in hashes
    assert os.path.isfile(os.path.join(lesson, "assets", "images", name))


def test_crop_replace_with_editor_open_leaves_text_to_the_editor(api_client, ws, rt_db, tmp_path, monkeypatch):
    lesson, lid, name = _placed_image(api_client, ws, rt_db, tmp_path, monkeypatch)
    token = api_client.post(f"/api/v1/lessons/{lid}/document/lease").json()["token"]
    blocked = api_client.post(f"/api/v1/lessons/{lid}/media/crop",
                              json={"image_name": name, "rect": [0.2, 0.2, 0.5, 0.5], "replace": True})
    assert blocked.status_code == 409
    res = api_client.post(f"/api/v1/lessons/{lid}/media/crop",
                          json={"image_name": name, "rect": [0.2, 0.2, 0.5, 0.5], "replace": True,
                                "update_document": False, "lease_token": token})
    assert res.status_code == 201, res.text
    assert f"assets/images/{name}" in api_client.get(f"/api/v1/lessons/{lid}/document").json()["markdown"]
