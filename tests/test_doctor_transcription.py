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
    assert settings_service.transcription_engines()["macparakeet_installed"] is True
