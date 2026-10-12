"""
tests/test_readonly_api.py
Test per l'API di sola lettura (AP1) e la gestione della chiave di sola lettura.
"""
import pytest
from fastapi.testclient import TestClient

from rt.api.app import create_app
from rt.api.readonly_auth import (
    create_readonly_key,
    get_readonly_key_info,
    revoke_readonly_key,
    verify_readonly_token,
)
from rt.core.models import DecisionLedger
from rt.pipeline.ledger import write_ledger_file
from rt.services.fts_service import reindex_all_lessons
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_readonly_key_lifecycle(tmp_path, monkeypatch, rt_db):
    isolated_workspace(tmp_path, monkeypatch)

    # 1. Inizialmente non configurata
    info = get_readonly_key_info(rt_db)
    assert info["configured"] is False
    assert info["key_preview"] is None

    # 2. Creazione chiave
    key = create_readonly_key(rt_db)
    assert key.startswith("rt_ro_")

    info = get_readonly_key_info(rt_db)
    assert info["configured"] is True
    assert info["created_at"] is not None
    assert info["key_preview"] is not None

    # 3. Verifica token
    assert verify_readonly_token(key, rt_db) is True
    assert verify_readonly_token("chiave_sbagliata", rt_db) is False

    # 4. Revoca chiave
    assert revoke_readonly_key(rt_db) is True
    info = get_readonly_key_info(rt_db)
    assert info["configured"] is False
    assert verify_readonly_token(key, rt_db) is False


def test_readonly_api_endpoints_and_fts(tmp_path, monkeypatch, rt_db):
    app = create_app(auth_disabled=False, serve_spa=False)
    client = TestClient(app)

    # Crea lezione sintetica con due unità
    text_1 = "La respirazione cellulare avviene nei mitocondri attraverso la glicolisi e il ciclo di Krebs."
    text_2 = "La catena di trasporto degli elettroni produce la maggior parte dell'ATP cellulare."
    lesson_dir = _synthetic_lesson(
        isolated_workspace(tmp_path, monkeypatch),
        {"1.1": text_1, "1.2": text_2},
    )
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    # Recupera lesson_id dal DB (già inserita da _synthetic_lesson)
    from sqlalchemy import select
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    with read_scope(rt_db) as session:
        lesson_row = session.scalar(select(Lesson).where(Lesson.path == lesson_dir))
        lesson_id = lesson_row.id

    # Indicizza in FTS5
    reindex_all_lessons(rt_db)

    # Genera chiave di sola lettura
    key = create_readonly_key(rt_db)
    headers = {"Authorization": f"Bearer {key}"}

    # 1. Richiesta non autenticata fallisce con 401
    unauth = client.get("/api/v1/readonly/lessons")
    assert unauth.status_code == 401

    # 2. Elenco lezioni
    res_list = client.get("/api/v1/readonly/lessons", headers=headers)
    assert res_list.status_code == 200
    lessons = res_list.json()
    assert len(lessons) >= 1
    assert lessons[0]["id"] == lesson_id
    assert lessons[0]["subject"] == "BIOCHIMICA"

    # 3. Scaletta lezione
    res_outline = client.get(f"/api/v1/readonly/lessons/{lesson_id}/outline", headers=headers)
    assert res_outline.status_code == 200
    outline = res_outline.json()
    assert outline["lesson_id"] == lesson_id
    assert len(outline["units"]) == 3
    assert outline["units"][0]["unit_id"] == "1.1"

    # 4. Testo unità
    res_unit = client.get(f"/api/v1/readonly/lessons/{lesson_id}/units/1.1", headers=headers)
    assert res_unit.status_code == 200
    unit_data = res_unit.json()
    assert unit_data["unit_id"] == "1.1"
    assert "mitocondri" in unit_data["content"]

    # Unità inesistente -> 404
    assert client.get(f"/api/v1/readonly/lessons/{lesson_id}/units/9.9", headers=headers).status_code == 404

    # 5. Ricerca FTS5
    res_search = client.get("/api/v1/readonly/lessons/search?q=mitocondri", headers=headers)
    assert res_search.status_code == 200
    hits = res_search.json()
    assert len(hits) == 1
    assert hits[0]["lesson_id"] == lesson_id
    assert hits[0]["unit_id"] == "1.1"
    assert "<b>mitocondri</b>" in hits[0]["snippet"]

    # Ricerca con filtro materia
    hits_bio = client.get("/api/v1/readonly/lessons/search?q=mitocondri&subject=BIOCHIMICA", headers=headers).json()
    assert len(hits_bio) == 1
    hits_fis = client.get("/api/v1/readonly/lessons/search?q=mitocondri&subject=FISIOLOGIA", headers=headers).json()
    assert len(hits_fis) == 0

    # 6. OpenAPI dedicato per Open WebUI
    res_openapi = client.get("/api/v1/readonly/openapi.json")
    assert res_openapi.status_code == 200
    schema = res_openapi.json()
    assert "paths" in schema
    assert "/lessons/search" in schema["paths"] or "/api/v1/readonly/lessons/search" in schema["paths"] or any("search" in p for p in schema["paths"])


def test_readonly_key_settings_endpoints(api_client, api_token):
    # Endpoint amministrativi delle impostazioni (richiedono token admin)
    # 1. Info iniziale
    res = api_client.get("/api/v1/settings/readonly-key")
    assert res.status_code == 200
    assert res.json()["configured"] is False

    # 2. Creazione chiave
    res_post = api_client.post("/api/v1/settings/readonly-key")
    assert res_post.status_code == 200
    created = res_post.json()
    assert created["key"].startswith("rt_ro_")
    assert created["key_preview"] is not None

    # Info aggiornata
    info = api_client.get("/api/v1/settings/readonly-key").json()
    assert info["configured"] is True

    # 3. Revoca chiave
    res_del = api_client.delete("/api/v1/settings/readonly-key")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True

    # Info dopo revoca
    assert api_client.get("/api/v1/settings/readonly-key").json()["configured"] is False
