"""Diagnostica e Impostazioni trovano macparakeet-cli anche fuori dal PATH (app aperta dal Finder)."""
import shutil
import sys
from types import SimpleNamespace

from rt.pipeline import setup
from rt.services import doctor_service, settings_service


def _homebrew_only(monkeypatch):
    monkeypatch.setenv("RT_USE_SYSTEM_MACPARAKEET", "1")
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
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    engines = settings_service.transcription_engines()
    assert engines["macparakeet_installed"] is True
    assert engines["recommended"] == "macparakeet"


def test_homebrew_macparakeet_ignored_by_default(monkeypatch):
    # un 3.1.0 di Homebrew può non leggere il database aggiornato dal 5.1.0: RT usa la propria copia
    _homebrew_only(monkeypatch)
    monkeypatch.delenv("RT_USE_SYSTEM_MACPARAKEET")
    assert setup.find_macparakeet_binary() == ""


def test_doctor_and_settings_on_mac_without_binary(monkeypatch):
    from rt.core import onnx_stt

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: True)
    monkeypatch.setattr(setup, "find_macparakeet_binary", lambda: "")
    config = SimpleNamespace(transcription=SimpleNamespace(engine="macparakeet"))
    monkeypatch.setattr("rt.core.config.load_config", lambda: config)

    # Apple Silicon senza binario: NON ricade su ONNX; dice che si scarica al primo uso o da Componenti
    monkeypatch.setattr(onnx_stt, "available", lambda: True)
    monkeypatch.setattr(onnx_stt, "model_ready", lambda: False)
    check = doctor_service.check_transcription()
    assert check.status == doctor_service.OK
    assert "Componenti" in check.message
    assert "brew install" not in check.message and "brew install" not in check.fix

    engines = settings_service.transcription_engines(config.transcription)
    assert engines["effective_engine"] == "macparakeet"
    assert engines["macparakeet_fallback"] is False
    assert engines["recommended"] == "macparakeet"

    # Mac Intel senza binario -> ricade su Parakeet ONNX se disponibile
    monkeypatch.setattr("rt.core.config.is_apple_silicon", lambda: False)
    check_intel = doctor_service.check_transcription()
    assert check_intel.status == doctor_service.OK
    assert "Parakeet ONNX" in check_intel.message
    assert "modello da scaricare al primo uso" in check_intel.message

    engines_intel = settings_service.transcription_engines(config.transcription)
    assert engines_intel["effective_engine"] == "parakeet"
    assert engines_intel["macparakeet_fallback"] is True
    assert engines_intel["recommended"] == "parakeet"

    monkeypatch.setattr(onnx_stt, "model_ready", lambda: True)
    check_ready = doctor_service.check_transcription()
    assert check_ready.status == doctor_service.OK
    assert "Parakeet ONNX" in check_ready.message

    # Mac Intel senza ONNX -> WARN senza brew install
    monkeypatch.setattr(onnx_stt, "available", lambda: False)
    check_warn = doctor_service.check_transcription()
    assert check_warn.status == doctor_service.WARN
    assert "Homebrew" not in check_warn.fix
