"""
tests/test_recall_evaluation_voice.py
Test di accettazione per la Fase D3: valutazione LLM di mirate/vaste, download
e trascrizione delle risposte vocali (rt/pipeline/recall.py, rt/telegram/client.py,
rt/core/recall_stt.py).
"""
import os
import json
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from rt.core.models import RecallQuestion, RecallQuestionType, RecallBank, Draft, DraftUnit
from rt.pipeline.recall import save_recall_bank, evaluate_recall_answer
from rt.telegram.client import download_voice, TelegramAPIError
from rt.telegram.config import TelegramConfig
from rt.core.recall_stt import transcribe_voice_answer


def _setup_lesson_with_unit(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    draft = Draft(schema_version="1.0", lesson_id="L1", units=[
        DraftUnit(unit_id="1.1", title="Metabolismo del ferro", content="Il ferro e' trasportato dalla transferrina.",
                  start_segment_id="seg_000001", end_segment_id="seg_000001", source_segment_ids=["seg_000001"])
    ])
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)


# ---------------------------------------------------------------------------
# 1. evaluate_recall_answer (percorso LLM reale, mockato)
# ---------------------------------------------------------------------------

class TestEvaluateRecallAnswer:
    def test_mirata_format_and_prompt(self, tmp_path):
        lesson_dir = str(tmp_path)
        _setup_lesson_with_unit(lesson_dir)
        q = RecallQuestion(id="recall_1", type=RecallQuestionType.MIRATA, unit_ids=["1.1"], question_text="Chi trasporta il ferro?")
        save_recall_bank(RecallBank(questions=[q]), lesson_dir)

        captured_prompts = {}

        def fake_call_structured(self, prompt, system_prompt, response_model, **kwargs):
            captured_prompts["prompt"] = prompt
            captured_prompts["job_name"] = kwargs.get("job_name")
            return response_model(correttezza=90, completezza=85, commento="Ottima risposta, precisa.")

        with patch("rt.llm.client.LLMClient.call_structured", fake_call_structured):
            result = evaluate_recall_answer(lesson_dir, "recall_1", "La transferrina.", force_mock=False)

        assert result == "Correttezza: 90%\nCompletezza: 85%\n\nOttima risposta, precisa."
        assert captured_prompts["job_name"] == "recall_eval_mirata"
        assert "transferrina" in captured_prompts["prompt"]  # risposta studente inclusa
        assert "Metabolismo del ferro" in captured_prompts["prompt"]  # riferimento unita' incluso

    def test_vasta_includes_pregenerated_material_in_prompt(self, tmp_path):
        lesson_dir = str(tmp_path)
        _setup_lesson_with_unit(lesson_dir)
        q = RecallQuestion(
            id="recall_2", type=RecallQuestionType.VASTA, unit_ids=["1.1"],
            question_text="Descrivi il metabolismo del ferro.",
            pregenerated_material="1) Assorbimento; 2) Trasporto via transferrina; 3) Deposito in ferritina.",
        )
        save_recall_bank(RecallBank(questions=[q]), lesson_dir)

        captured_prompts = {}

        def fake_call_structured(self, prompt, system_prompt, response_model, **kwargs):
            captured_prompts["prompt"] = prompt
            captured_prompts["job_name"] = kwargs.get("job_name")
            return response_model(commento="Copre 2 punti su 3, manca il deposito.")

        with patch("rt.llm.client.LLMClient.call_structured", fake_call_structured):
            result = evaluate_recall_answer(lesson_dir, "recall_2", "Viene assorbito e trasportato.", force_mock=False)

        assert result == "Copre 2 punti su 3, manca il deposito."
        assert captured_prompts["job_name"] == "recall_eval_vasta"
        assert "ferritina" in captured_prompts["prompt"]  # scaletta ideale inclusa come riferimento

    def test_quiz_raises(self, tmp_path):
        lesson_dir = str(tmp_path)
        _setup_lesson_with_unit(lesson_dir)
        q = RecallQuestion(id="recall_3", type=RecallQuestionType.QUIZ, unit_ids=["1.1"], question_text="?",
                            options=["a", "b", "c", "d"], correct_index=0)
        save_recall_bank(RecallBank(questions=[q]), lesson_dir)

        with pytest.raises(ValueError):
            evaluate_recall_answer(lesson_dir, "recall_3", "a", force_mock=False)

    def test_force_mock_bypasses_llm(self, tmp_path):
        lesson_dir = str(tmp_path)
        _setup_lesson_with_unit(lesson_dir)
        q = RecallQuestion(id="recall_4", type=RecallQuestionType.MIRATA, unit_ids=["1.1"], question_text="?")
        save_recall_bank(RecallBank(questions=[q]), lesson_dir)

        with patch("rt.llm.client.LLMClient.call_structured") as mock_call:
            result = evaluate_recall_answer(lesson_dir, "recall_4", "risposta", force_mock=True)
            assert not mock_call.called
        assert "Correttezza" in result and "Completezza" in result


# ---------------------------------------------------------------------------
# 2. download_voice
# ---------------------------------------------------------------------------

class TestDownloadVoice:
    def test_downloads_file_content(self, tmp_path):
        cfg = TelegramConfig(bot_token="TOK", chat_id=1)
        dest_path = str(tmp_path / "voice.oga")

        get_file_resp = MagicMock()
        get_file_resp.json.return_value = {"ok": True, "result": {"file_id": "F1", "file_path": "voice/file_1.oga"}}

        binary_resp = MagicMock()
        binary_resp.status_code = 200
        binary_resp.content = b"AUDIO_BYTES_HERE"

        with patch("requests.post", return_value=get_file_resp) as mock_post, \
             patch("requests.get", return_value=binary_resp) as mock_get:
            download_voice(cfg, "F1", dest_path)

        assert mock_post.call_args[0][0] == "https://api.telegram.org/botTOK/getFile"
        assert mock_get.call_args[0][0] == "https://api.telegram.org/file/botTOK/voice/file_1.oga"
        with open(dest_path, "rb") as f:
            assert f.read() == b"AUDIO_BYTES_HERE"

    def test_raises_on_missing_file_path(self, tmp_path):
        cfg = TelegramConfig(bot_token="TOK", chat_id=1)
        get_file_resp = MagicMock()
        get_file_resp.json.return_value = {"ok": True, "result": {"file_id": "F1"}}  # niente file_path

        with patch("requests.post", return_value=get_file_resp):
            with pytest.raises(TelegramAPIError):
                download_voice(cfg, "F1", str(tmp_path / "x.oga"))


# ---------------------------------------------------------------------------
# 3. transcribe_voice_answer
# ---------------------------------------------------------------------------

class TestTranscribeVoiceAnswer:
    def test_transcribes_via_macparakeet(self, tmp_path):
        audio_path = str(tmp_path / "voice.oga")
        with open(audio_path, "wb") as f:
            f.write(b"FAKE_AUDIO")

        def fake_run(cmd, stdout=None, stderr=None, text=None):
            payload = json.dumps({"transcriptSegments": [{"text": "Ciao "}, {"text": "mondo."}], "rawTranscript": "Ciao mondo."})
            return MagicMock(returncode=0, stdout=payload, stderr="")

        with patch("rt.pipeline.setup.find_macparakeet_binary", return_value="/usr/local/bin/macparakeet-cli"), \
             patch("subprocess.run", side_effect=fake_run) as mock_run:
            text = transcribe_voice_answer(audio_path, stt_engine="macparakeet")

        assert text == "Ciao mondo."
        cmd_used = mock_run.call_args[0][0]
        assert cmd_used[0] == "/usr/local/bin/macparakeet-cli"
        assert cmd_used[1] == "transcribe"
        assert "--format" in cmd_used and "json" in cmd_used
        assert audio_path in cmd_used

    def test_raises_when_macparakeet_not_found(self, tmp_path):
        audio_path = str(tmp_path / "voice.oga")
        with open(audio_path, "wb") as f:
            f.write(b"FAKE_AUDIO")

        with patch("rt.pipeline.setup.find_macparakeet_binary", return_value=""):
            with pytest.raises(RuntimeError):
                transcribe_voice_answer(audio_path)

    def test_api_engine_not_implemented(self, tmp_path):
        audio_path = str(tmp_path / "voice.oga")
        with open(audio_path, "wb") as f:
            f.write(b"FAKE_AUDIO")
        with pytest.raises(NotImplementedError):
            transcribe_voice_answer(audio_path, stt_engine="api")
