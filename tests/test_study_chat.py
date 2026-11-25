"""Test backend per la Chat dello Studio (servizio, routing, vision, note, STT e router API)."""
import os
import pytest

from rt.core.config import JobRoutingConfig, RTConfig, RouteConfig
from rt.core.models import DecisionLedger
from rt.db.models import StudyChatMessage
from rt.db.session import read_scope
from rt.llm.client import LLMClient
from rt.llm.errors import RateLimitFailure
from rt.llm.prompts import StudyChatReply
from rt.pipeline.ledger import write_ledger_file
from rt.services import study_chat_service
from rt.services.study_notes_service import decorate_study_note, list_study_notes
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02"
    b"\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _setup_lesson(tmp_path, monkeypatch, api_client):
    lesson_dir = _synthetic_lesson(
        isolated_workspace(tmp_path, monkeypatch),
        {
            "1.1": "La glicolisi avviene nel citosol e produce piruvato.",
            "1.2": "Il ciclo di Krebs avviene nella matrice mitocondriale.",
        },
    )
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)
    lesson_id = api_client.get("/api/v1/lessons").json()[0]["id"]
    return lesson_dir, lesson_id


def test_study_chat_context_and_history_limit(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    recorded_calls = []

    def fake_call(self, **kwargs):
        recorded_calls.append(kwargs)
        return StudyChatReply(text="Risposta **precisa** con $E = mc^2$.")

    monkeypatch.setattr(LLMClient, "call_structured", fake_call)

    # Invia 18 turni (36 messaggi) per verificare il limite della cronologia a 30 messaggi
    for i in range(18):
        res = study_chat_service.send_message(
            lesson_dir=lesson_dir,
            lesson_id=lesson_id,
            text=f"Domanda {i}",
            unit_id="1.2",
        )
        assert res["user_message"]["role"] == "user"
        assert res["assistant_message"]["role"] == "assistant"
        assert res["assistant_message"]["error"] is None

    last_call = recorded_calls[-1]
    assert last_call["job_name"] == "study_chat"
    assert "### 1.1 " in str(last_call["prompt_prefix"])
    assert "glicolisi" in str(last_call["prompt_prefix"])
    assert "### 1.2 " in str(last_call["prompt_prefix"])
    assert "L'utente sta leggendo l'unità 1.2" in last_call["prompt"]
    assert "Domanda 17" in last_call["prompt"]
    assert len(last_call["history"]) == study_chat_service.HISTORY_LIMIT
    # I primi messaggi (Domanda 0..2) non devono più stare nei 30 più recenti
    history_texts = [m["content"] for m in last_call["history"]]
    assert "Domanda 0" not in history_texts
    assert "Domanda 16" in history_texts


def test_study_chat_routing_falls_back_to_review(monkeypatch):
    cfg = RTConfig(
        jobs={
            "review": JobRoutingConfig(
                primary=RouteConfig(provider="openrouter", model="openai/gpt-4.1-mini", credential="openrouter")
            )
        }
    )
    monkeypatch.setattr("rt.llm.client.load_config", lambda *_a, **_kw: cfg)
    client = LLMClient()
    resolved = client._get_job_routing_config("study_chat")
    assert resolved.primary.model == "openai/gpt-4.1-mini"
    assert client.router.select_initial_route("study_chat").model == "openai/gpt-4.1-mini"


def test_study_chat_non_vision_model_saves_error_without_raising(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    # Default di test per review usa deepseek (senza vision)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cfg = RTConfig(
        jobs={
            "review": JobRoutingConfig(
                primary=RouteConfig(provider="deepseek", model="deepseek-chat", credential="deepseek")
            )
        }
    )
    monkeypatch.setattr("rt.llm.client.load_config", lambda *_a, **_kw: cfg)

    res = study_chat_service.send_message(
        lesson_dir=lesson_dir,
        lesson_id=lesson_id,
        text="Guarda questa slide",
        unit_id="1.1",
        images=[(_PNG_1X1, "image/png", "slide.png")],
        force_mock=False,
    )
    assistant = res["assistant_message"]
    assert assistant["error"] is not None
    assert "non legge le immagini" in assistant["error"]
    assert "Chat dello Studio" in assistant["error"]
    assert len(res["user_message"]["images"]) == 1


def test_study_chat_provider_image_error_handled(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    cfg = RTConfig(
        jobs={
            "study_chat": JobRoutingConfig(
                primary=RouteConfig(provider="openrouter", model="custom/text-only-model", credential="openrouter")
            )
        }
    )
    monkeypatch.setattr("rt.llm.client.load_config", lambda *_a, **_kw: cfg)

    def fail_image(self, **_kwargs):
        raise RuntimeError("HTTP 400: This model does not support image input.")

    monkeypatch.setattr(LLMClient, "call_structured", fail_image)
    res = study_chat_service.send_message(
        lesson_dir=lesson_dir,
        lesson_id=lesson_id,
        text="Leggi qui",
        unit_id="1.1",
        images=[(_PNG_1X1, "image/png", "slide.png")],
    )
    assert "non legge le immagini" in res["assistant_message"]["error"]


def test_study_chat_generic_llm_failure_uses_describe_llm_failure(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    def fail_rate(self, **_kwargs):
        raise RateLimitFailure("Troppo traffico", provider="openrouter", model="test-m")

    monkeypatch.setattr(LLMClient, "call_structured", fail_rate)
    res = study_chat_service.send_message(
        lesson_dir=lesson_dir,
        lesson_id=lesson_id,
        text="Spiega",
        unit_id="1.1",
    )
    assert "test-m" in res["assistant_message"]["error"]
    assert "rate_limit" in res["assistant_message"]["error"]


def test_study_chat_clear_removes_rows_and_images(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    res = study_chat_service.send_message(
        lesson_dir=lesson_dir,
        lesson_id=lesson_id,
        text="Con immagine",
        unit_id="1.1",
        images=[(_PNG_1X1, "image/png", "foto.png")],
        force_mock=True,
    )
    rel_img = res["user_message"]["images"][0]
    assert rel_img.startswith("chat/")
    assert os.path.isfile(os.path.join(lesson_dir, rel_img))

    study_chat_service.clear(lesson_dir, lesson_id)
    assert study_chat_service.list_messages(lesson_id) == []
    assert not os.path.exists(os.path.join(lesson_dir, rel_img))


def test_study_chat_save_idempotent_and_unsave(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    res = study_chat_service.send_message(
        lesson_dir=lesson_dir,
        lesson_id=lesson_id,
        text="Cos'è il piruvato?",
        unit_id="1.1",
        force_mock=True,
    )
    assistant_id = res["assistant_message"]["id"]

    first = study_chat_service.save_as_note(lesson_dir, lesson_id, assistant_id)
    second = study_chat_service.save_as_note(lesson_dir, lesson_id, assistant_id)
    assert first["note"]["id"] == second["note"]["id"]
    assert first["note"]["kind"] == "chat"
    assert first["note"]["request"] == "Cos'è il piruvato?"
    assert first["note"]["anchor_state"] == "trovata"
    assert first["message"]["saved_note_id"] == first["note"]["id"]

    notes = list_study_notes(lesson_id)
    assert len(notes) == 1
    decorated = decorate_study_note(notes[0], lesson_dir, lesson_id)
    assert decorated["anchor_state"] == "trovata"

    unsaved = study_chat_service.unsave_as_note(lesson_id, assistant_id)
    assert unsaved["saved_note_id"] is None
    assert list_study_notes(lesson_id) == []


def test_study_chat_transcribe_with_fake_stt(monkeypatch):
    seen = {}

    def fake_stt(audio_path, stt_engine="macparakeet"):
        seen["exists_during_call"] = os.path.isfile(audio_path)
        seen["engine"] = stt_engine
        with open(audio_path, "rb") as f:
            seen["bytes"] = f.read()
        seen["path"] = audio_path
        return "Domanda vocale trascritta"

    monkeypatch.setattr(study_chat_service, "transcribe_voice_answer", fake_stt)
    text = study_chat_service.transcribe_audio(b"RIFFfakeaudio", "nota.wav")
    assert text == "Domanda vocale trascritta"
    assert seen["exists_during_call"] is True
    assert seen["bytes"] == b"RIFFfakeaudio"
    assert not os.path.exists(seen["path"])


def test_study_chat_api_endpoints_and_limits(tmp_path, monkeypatch, rt_db, api_client):
    lesson_dir, lesson_id = _setup_lesson(tmp_path, monkeypatch, api_client)

    # 404 lezione inesistente
    assert api_client.get("/api/v1/lessons/99999/chat").status_code == 404

    # POST multipart con immagine e testo (mock)
    res = api_client.post(
        f"/api/v1/lessons/{lesson_id}/chat",
        data={"text": "Spiega la glicolisi", "unit_id": "1.1", "mock": "true"},
        files=[("images", ("slide.png", _PNG_1X1, "image/png"))],
    )
    assert res.status_code == 200
    body = res.json()
    assert body["user_message"]["content"] == "Spiega la glicolisi"
    assert len(body["user_message"]["image_urls"]) == 1
    assert "[MOCK]" in body["assistant_message"]["content"]
    assert body["assistant_message"]["content_html"]

    # Serve immagine salvata
    img_res = api_client.get(body["user_message"]["image_urls"][0])
    assert img_res.status_code == 200
    assert img_res.content == _PNG_1X1

    # GET cronologia
    hist = api_client.get(f"/api/v1/lessons/{lesson_id}/chat")
    assert hist.status_code == 200
    assert len(hist.json()) == 2

    # Save & Unsave endpoint
    msg_id = body["assistant_message"]["id"]
    save_res = api_client.post(f"/api/v1/lessons/{lesson_id}/chat/{msg_id}/save")
    assert save_res.status_code == 200
    assert save_res.json()["note"]["kind"] == "chat"
    unsave_res = api_client.delete(f"/api/v1/lessons/{lesson_id}/chat/{msg_id}/save")
    assert unsave_res.status_code == 200
    assert unsave_res.json()["saved_note_id"] is None

    # Limite > 4 immagini
    too_many = [("images", (f"i{i}.png", _PNG_1X1, "image/png")) for i in range(5)]
    res_many = api_client.post(
        f"/api/v1/lessons/{lesson_id}/chat",
        data={"text": "Troppe", "unit_id": "1.1", "mock": "true"},
        files=too_many,
    )
    assert res_many.status_code == 422

    # Formato non ammesso (415)
    res_bad_type = api_client.post(
        f"/api/v1/lessons/{lesson_id}/chat",
        data={"text": "PDF non ammesso", "unit_id": "1.1", "mock": "true"},
        files=[("images", ("doc.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    assert res_bad_type.status_code == 415

    # Limite dimensione > 10 MB (413)
    monkeypatch.setattr("rt.api.routers.study_chat.MAX_CHAT_IMAGE_BYTES", 8)
    res_big = api_client.post(
        f"/api/v1/lessons/{lesson_id}/chat",
        data={"text": "Grande", "unit_id": "1.1", "mock": "true"},
        files=[("images", ("big.png", _PNG_1X1, "image/png"))],
    )
    assert res_big.status_code == 413

    # Transcribe endpoint
    monkeypatch.setattr(study_chat_service, "transcribe_voice_answer", lambda *_a, **_kw: "Testo audio")
    stt_res = api_client.post(
        f"/api/v1/lessons/{lesson_id}/chat/transcribe",
        files={"audio": ("rec.webm", b"audio-data", "audio/webm")},
    )
    assert stt_res.status_code == 200
    assert stt_res.json()["text"] == "Testo audio"

    # DELETE cronologia
    del_res = api_client.delete(f"/api/v1/lessons/{lesson_id}/chat")
    assert del_res.status_code == 204
    assert api_client.get(f"/api/v1/lessons/{lesson_id}/chat").json() == []
    with read_scope(rt_db) as s:
        assert s.query(StudyChatMessage).filter_by(lesson_id=lesson_id).count() == 0
