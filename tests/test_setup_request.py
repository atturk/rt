"""
tests/test_setup_request.py
RT4-A3: setup senza input(): metadati validati, campi mancanti come eccezione tipizzata,
prompt solo nell'adapter CLI.
"""
import shutil

import pytest

from rt.pipeline.setup import (
    MissingSetupFields, SetupError, resolve_setup_request, run_setup,
)
from rt.services.context import RunContext
from rt.services.events import ListReporter
from rt.services.pipeline_service import PipelineOptions, PipelineStatus, run_pipeline
from tests.golden_support import AUDIO_FIXTURE


@pytest.fixture(autouse=True)
def _no_stdin(monkeypatch):
    def _fail(*_a, **_k):
        raise AssertionError("il setup non deve leggere da stdin")
    monkeypatch.setattr("builtins.input", _fail)


@pytest.fixture
def audio(tmp_path):
    dst = tmp_path / "biochimica lezione.wav"
    shutil.copy(AUDIO_FIXTURE, dst)
    return str(dst)


def test_missing_audio_raises_missing_fields_without_terminal():
    with pytest.raises(MissingSetupFields) as exc:
        run_setup(audio=[], mock_asr=True, interactive=True)
    assert exc.value.fields == ["audio"]
    assert str(exc.value) == "Nessun file audio specificato."
    assert isinstance(exc.value, SetupError)


def test_strict_reports_all_missing_fields(audio):
    with pytest.raises(MissingSetupFields) as exc:
        resolve_setup_request(audio, strict=True)
    assert exc.value.fields == ["date", "materia"]


def test_defaults_without_prompter(audio):
    req = resolve_setup_request(audio, argomenti=" Lipidi ")
    assert req.materia == "BIOCHIMICA"  # dedotta dal nome del file
    assert req.argomenti == "Lipidi"
    assert len(req.date) == 10


def test_invalid_date_without_prompter_is_setup_error(audio):
    with pytest.raises(SetupError):
        resolve_setup_request(audio, date="non una data", materia="x")


def test_prompter_is_used_for_missing_and_invalid_fields(audio):
    class FakePrompter:
        def __init__(self):
            self.dates = iter(["boh", "3 marzo 2024"])
            self.invalid = []

        def ask_audio(self):
            return audio

        def ask_date(self, default):
            return next(self.dates)

        def invalid_date(self, raw):
            self.invalid.append(raw)

        def ask_materia(self, default_guess):
            assert default_guess == "BIOCHIMICA"
            return "fisiologia"

    p = FakePrompter()
    req = resolve_setup_request([], prompter=p)
    assert req.audio == [audio]
    assert req.date == "2024-03-03"
    assert req.materia == "FISIOLOGIA"
    assert p.invalid == ["boh"]


def test_pipeline_without_provider_waits_for_setup_metadata(audio):
    rep = ListReporter()
    res = run_pipeline([audio], PipelineOptions(mock=True), RunContext(reporter=rep))
    assert res.status == PipelineStatus.WAITING_FOR_DECISION
    assert res.decision.kind == "setup_metadata"
    assert res.decision.payload["missing"] == ["date", "materia"]

    res = run_pipeline([audio], PipelineOptions(mock=True, auto_accept=True, rename=False,
                                                date="2026-09-05", materia="biochimica"), RunContext())
    assert res.status == PipelineStatus.COMPLETED, res.error
