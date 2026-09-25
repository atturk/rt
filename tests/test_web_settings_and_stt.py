"""Persistenza della configurazione web e adattatore STT temporizzato."""

import yaml

from rt.core.config import load_config
from rt.core.custom_stt import transcribe_custom
from rt.web.app import _topic_from_link
from rt.web.settings import save_credential, save_route, save_telegram, save_transcription


def test_web_settings_persist_and_keep_existing_route_options(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("RT_GOOGLE_TEST_TWO_API_KEY", "RT_GOOGLE_TEST_THREE_API_KEY",
                 "RT_TELEGRAM_BOT_TOKEN", "RT_TELEGRAM_CHAT_ID"):
        monkeypatch.setenv(name, "temporary-test-value")
    project = tmp_path
    config = project / "config"
    config.mkdir()
    (config / "general.yaml").write_text(
        "credentials:\n  - name: google_test_one\n    provider: google\n"
        "    env_var: RT_GOOGLE_TEST_ONE_API_KEY\n"
        "telegram:\n  topics:\n    OLD: 11\n"
        "transcription:\n  timeout_seconds: 45\n", encoding="utf-8")
    (config / "outline.yaml").write_text(
        "primary:\n  provider: google\n  credential: google_test_one\n"
        "  model: old-model\n  temperature: 0.2\n", encoding="utf-8")

    save_credential(project, "google", "google_test_two", "second-test-key")
    save_credential(project, "google", "google_test_three", "third-test-key")
    assert "second-test-key" in (project / ".env").read_text(encoding="utf-8")
    save_route(project, "outline", "primary", "google", "google_test_one",
               "new-model", "https://generativelanguage.googleapis.com/v1beta/openai", True,
               ["google_test_one", "google_test_three"])
    job = yaml.safe_load((config / "outline.yaml").read_text(encoding="utf-8"))
    assert job["round_robin"] is True
    assert {route["credential"] for route in job["primary_routes"]} == {
        "google_test_one", "google_test_three"}
    assert job["primary"]["temperature"] == 0.2

    save_telegram(project, "bot-token", "-123", [["BIOCHIMICA", "22"]], "33")
    save_transcription(project, "custom", "http://localhost:8000/v1", "local-stt", "")
    loaded = load_config()
    assert loaded.telegram.topics == {"BIOCHIMICA": 22}
    assert loaded.transcription.engine == "custom"
    assert loaded.transcription.timeout_seconds == 45
    assert loaded.transcription.model == "local-stt"


def test_custom_stt_converts_seconds_to_rt_milliseconds(tmp_path, monkeypatch):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"test-audio")
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "Buongiorno", "segments": [
                {"start": 1.25, "end": 2.5, "text": "Buongiorno"}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["data"] = kwargs["data"]
        return Response()

    monkeypatch.setattr("rt.core.custom_stt.requests.post", fake_post)
    result = transcribe_custom(str(audio), "http://localhost:8000/v1", "local-stt")
    assert captured["url"] == "http://localhost:8000/v1/audio/transcriptions"
    assert captured["data"]["response_format"] == "verbose_json"
    assert result["transcriptSegments"] == [{"startMs": 1250.0, "endMs": 2500.0,
                                              "text": "Buongiorno", "confidence": None}]


def test_telegram_topic_link_keeps_unassigned_rows():
    status, chat, rows, cleared = _topic_from_link(
        "https://t.me/c/1234567890/12/34", [["", "11"]], "")
    assert "12" in status
    assert chat == "-1001234567890"
    assert rows == [["", "11"], ["", "12"]]
    assert cleared == ""
