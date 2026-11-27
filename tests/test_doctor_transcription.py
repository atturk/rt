"""Diagnostica e Impostazioni trovano macparakeet-cli anche fuori dal PATH (app aperta dal Finder)."""
import shutil
import sys
from types import SimpleNamespace

from rt.pipeline import setup
from rt.services import doctor_service, settings_service


def _homebrew_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(setup.fs, "exists", lambda path: path == "/opt/homebrew/bin/macparakeet-cli")
    monkeypatch.setattr(setup.os, "access", lambda path, mode: path == "/opt/homebrew/bin/macparakeet-cli")


def test_doctor_finds_macparakeet_outside_path(monkeypatch):
    _homebrew_only(monkeypatch)
    config = SimpleNamespace(transcription=SimpleNamespace(engine="macparakeet"))
    monkeypatch.setattr("rt.core.config.load_config", lambda: config)
    check = doctor_service.check_transcription()
    assert check.status == doctor_service.OK


def test_settings_finds_macparakeet_outside_path(monkeypatch):
    _homebrew_only(monkeypatch)
    engines = settings_service.transcription_engines()
    assert engines["macparakeet_installed"] is True
    assert engines["recommended"] == "parakeet"


def test_doctor_and_settings_fallback_on_mac_without_binary(monkeypatch):
    from rt.core import onnx_stt

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "")
    config = SimpleNamespace(transcription=SimpleNamespace(engine="macparakeet"))
    monkeypatch.setattr("rt.core.config.load_config", lambda: config)

    # Senza macparakeet-cli ma con ONNX e modello non ancora scaricato -> OK con nota
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    monkeypatch.setattr(onnx_stt, "model_ready", lambda: False)
    check = doctor_service.check_transcription()
    assert check.status == doctor_service.OK
    assert "Parakeet ONNX (macparakeet-cli non installato)" in check.message
    assert "modello da scaricare al primo uso" in check.message

    engines = settings_service.transcription_engines(config.transcription)
    assert engines["effective_engine"] == "parakeet"
    assert engines["macparakeet_fallback"] is True
    assert engines["recommended"] == "parakeet"

    # Con modello già scaricato -> OK senza nota download
    monkeypatch.setattr(onnx_stt, "model_ready", lambda: True)
    check_ready = doctor_service.check_transcription()
    assert check_ready.status == doctor_service.OK
    assert check_ready.message == "Parakeet ONNX (macparakeet-cli non installato)"

    # Senza né macparakeet-cli né ONNX -> WARN
    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    check_warn = doctor_service.check_transcription()
    assert check_warn.status == doctor_service.WARN
