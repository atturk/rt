"""Docente all'importazione e avanzamento della trascrizione (report del 30 settembre)."""
import json
import os
from unittest.mock import patch

import yaml

from rt.core.lesson_paths import lesson_path
from rt.pipeline.setup import _run_transcribe_with_spinner, run_setup


def test_docente_is_saved_in_info_yaml_and_not_in_folder_name(tmp_path):
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"audio")
    res = run_setup(str(audio), date="2026-09-30", materia="PGSS", docente="  Prof.ssa  Maria Rossi ",
                    dest_dir=str(tmp_path), mock_asr=True, interactive=False)
    assert res["docente"] == "Prof.ssa Maria Rossi"
    assert "Rossi" not in res["folder_name"]
    with open(lesson_path(res["lesson_dir"], "info.yaml"), encoding="utf-8") as f:
        info = yaml.safe_load(f)
    assert info["docente"] == "Prof.ssa Maria Rossi" and info["materia"] == "PGSS"


def test_without_docente_info_yaml_has_no_key(tmp_path):
    audio = tmp_path / "lezione.m4a"
    audio.write_bytes(b"audio")
    res = run_setup(str(audio), date="2026-09-30", materia="PGSS", dest_dir=str(tmp_path), mock_asr=True, interactive=False)
    with open(lesson_path(res["lesson_dir"], "info.yaml"), encoding="utf-8") as f:
        assert "docente" not in yaml.safe_load(f)


def test_transcription_percent_reported_once_per_change(tmp_path):
    script = tmp_path / "fake.sh"
    script.write_text("#!/bin/sh\necho 'Transcribing 10%'\necho 'Transcribing 10%'\necho 'chunk'\necho 'Transcribing 55%'\necho 'done 100%'\n")
    os.chmod(script, 0o755)
    seen = []
    res = _run_transcribe_with_spinner([str(script)], "Test", on_percent=seen.append)
    assert res.returncode == 0
    assert seen == [10, 55, 100]


def test_pipeline_emits_transcription_progress(tmp_path):
    """Il job mostra la percentuale di macparakeet nella barra (fase setup)."""
    from rt.services.context import RunContext
    from rt.services.pipeline_service import PipelineOptions, _setup

    events = []

    class Reporter:
        def emit(self, event):
            events.append(event)

    def fake_setup(**kwargs):
        kwargs["on_transcription_progress"](42)
        assert kwargs["docente"] == "Rossi"
        return {"lesson_dir": str(tmp_path)}

    _setup(fake_setup, ["a.m4a"], PipelineOptions(materia="X", docente="Rossi"), RunContext(reporter=Reporter()), None)
    progress = [e for e in events if e.type == "phase_progress"]
    assert [(p.phase, p.current, p.total) for p in progress] == [("setup", 42, 100)]
    assert "42%" in progress[0].message
