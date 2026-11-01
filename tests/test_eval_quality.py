"""
tests/test_eval_quality.py
scripts/eval_quality.py senza rete: lo zip della lezione golden e un giudice finto.
"""
import importlib.util
import io
import json
import os
import zipfile

from tests.golden_support import GOLDEN_DIR

SPEC = importlib.util.spec_from_file_location(
    "eval_quality", os.path.join(os.path.dirname(GOLDEN_DIR), "..", "scripts", "eval_quality.py"))
eval_quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_quality)


def lesson_zip(tmp_path):
    lesson = os.path.join(GOLDEN_DIR, "audio_full", "lesson")
    path = tmp_path / "lezione.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for root, _, files in os.walk(lesson):
            for name in files:
                archive.write(os.path.join(root, name), os.path.join("lezione", name))
    return path


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_judge(calls):
    def urlopen(request, timeout):
        body = json.loads(request.data)
        calls.append(body)
        name = body["response_format"]["json_schema"]["name"]
        verdict = {
            "unita": {"fedelta": 4, "completezza": 3, "chiarezza": 5, "formule_e_termini": 4,
                      "inventato": ["x"], "omesso": [], "nota": ""},
            "verifica": {"esito": "falso_allarme", "correzione_giusta": False, "nota": ""},
            "domanda": {"pertinenza": 4, "correttezza": 5, "chiarezza": 4, "risposta_quiz_giusta": None, "nota": ""},
        }[name]
        payload = {"choices": [{"message": {"content": json.dumps(verdict)}}],
                   "usage": {"cost": 0.004, "prompt_tokens": 900}}
        return FakeResponse(json.dumps(payload).encode())
    return urlopen


class Args:
    units, issues, questions, budget = 3, 1, 1, 1.0


def test_report_from_a_lesson_zip(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(eval_quality.urllib.request, "urlopen", fake_judge(calls))
    report = eval_quality.evaluate(lesson_zip(tmp_path), "chiave-finta", Args)
    # la lezione golden ha una sola unità e dieci segnalazioni, senza domande
    assert len(report["unita"]) == 1 and len(report["verifica"]) == 1 and report["domande"] == []
    assert report["sintesi"]["unita"]["fedelta"] == 4
    assert report["sintesi"]["affermazioni_inventate"] == 1
    assert report["sintesi"]["verifica_falsi_allarmi"] == 1
    assert report["costo_usd"] == round(0.004 * len(calls), 4)
    # il giudice vede il trascritto della sua unità e lavora a temperatura 0
    assert all(body["temperature"] == 0 and body["model"] == eval_quality.JUDGE_MODEL for body in calls)
    assert "TRASCRITTO" in calls[0]["messages"][1]["content"]


def test_budget_stops_the_evaluation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(eval_quality.urllib.request, "urlopen", fake_judge(calls))
    Args.budget, Args.issues = 0.005, 5
    try:
        report = eval_quality.evaluate(lesson_zip(tmp_path), "chiave-finta", Args)
    finally:
        Args.budget, Args.issues = 1.0, 1
    assert report["chiamate"] == 2  # la seconda supera il budget: le altre tre non partono
