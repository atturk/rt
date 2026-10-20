"""Il pacchetto toglie le parti superflue della libreria standard e conserva il bytecode."""
import importlib.util
import os
from pathlib import Path

import pytest

from scripts.build_app import _trim


@pytest.mark.parametrize('target', ['macos', 'windows'])
def test_trim_keeps_modules_and_bytecode(tmp_path, target):
    lib = tmp_path / 'python' / ('Lib' if target == 'windows' else 'lib/python3.12')
    module = lib / 'site-packages' / 'esempio' / '__init__.py'
    module.parent.mkdir(parents=True)
    module.write_text('VALUE = 1\n', encoding='utf-8')
    cache = Path(importlib.util.cache_from_source(str(module)))
    cache.parent.mkdir()
    cache.write_bytes(b'cache rigenerabile')
    orphan = cache.parent / 'solo_bytecode.cpython-312.pyc'
    orphan.write_bytes(b'modulo senza sorgente')
    other = cache.with_suffix('.bin')
    other.write_bytes(b'dati')
    empty_module = lib / 'json.py'
    empty_module.write_text('# sorgente\n', encoding='utf-8')
    empty_cache = Path(importlib.util.cache_from_source(str(empty_module)))
    empty_cache.parent.mkdir(exist_ok=True)
    empty_cache.write_bytes(b'cache')
    binary = module.parent / 'native.so'
    binary.write_bytes(b'binario necessario')
    for name in ('test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip'):
        (lib / name).mkdir()
        (lib / name / 'file').write_bytes(b'superfluo')

    _trim(str(tmp_path), target)

    assert module.read_text(encoding='utf-8') == 'VALUE = 1\n'
    assert binary.read_bytes() == b'binario necessario'
    assert orphan.read_bytes() == b'modulo senza sorgente'
    assert other.read_bytes() == b'dati'
    # Avvio veloce anche da un'app in sola lettura.
    assert cache.read_bytes() == b'cache rigenerabile'
    assert empty_cache.read_bytes() == b'cache'
    assert all(not (lib / name).exists() for name in ('test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip'))


def test_write_build_info(tmp_path):
    import json
    from scripts.build_app import write_build_info, read_version

    env_full = {
        "GITHUB_SHA": "1234567890abcdef",
        "GITHUB_RUN_NUMBER": "812",
    }
    info_full = write_build_info(str(tmp_path), "macos", env=env_full)
    assert info_full["version"] == read_version()
    assert info_full["target"] == "macos"
    assert info_full["commit"] == "1234567"
    assert info_full["run"] == "812"
    assert "built_at" in info_full

    saved_full = json.loads((tmp_path / "BUILD.json").read_text(encoding="utf-8"))
    assert saved_full == info_full

    # Solo campi disponibili: senza GITHUB_RUN_NUMBER
    payload_min = tmp_path / "min"
    payload_min.mkdir()
    env_min = {"GITHUB_SHA": "abcdef12345"}
    info_min = write_build_info(str(payload_min), "windows", env=env_min)
    assert info_min["target"] == "windows"
    assert info_min["commit"] == "abcdef1"
    assert "run" not in info_min


def test_launcher_disables_bytecode():
    from scripts.build_app import LAUNCHER
    assert "export PYTHONDONTWRITEBYTECODE=1" in LAUNCHER


def test_dmg_background_dimensions():
    from PIL import Image
    root = Path(__file__).resolve().parent.parent
    bg_1x = root / "packaging" / "dmg" / "background.png"
    bg_2x = root / "packaging" / "dmg" / "background@2x.png"

    assert bg_1x.is_file()
    assert bg_2x.is_file()

    with Image.open(bg_1x) as img1:
        assert img1.size == (660, 400)

    with Image.open(bg_2x) as img2:
        assert img2.size == (1320, 800)


def test_build_macos_signs_macho_then_bundle_and_runs_dmgbuild(tmp_path, monkeypatch):
    import scripts.build_app as build_app

    work = tmp_path / "work"
    out = tmp_path / "dist"
    work.mkdir()
    out.mkdir()

    calls = []
    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(build_app.subprocess, "run", fake_run)
    monkeypatch.setattr(build_app, "read_version", lambda: "4.3.2b2")

    def fake_build_payload(target, payload, archive, spa_dist):
        os.makedirs(payload, exist_ok=True)
        # un Mach-O binario (con magic Mach-O 64-bit)
        macho = Path(payload) / "native.dylib"
        macho.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 20)
        # un file di testo non-Mach-O
        text = Path(payload) / "note.txt"
        text.write_text("ciao", encoding="utf-8")

    monkeypatch.setattr(build_app, "build_payload", fake_build_payload)

    dmg = build_app.build_macos(str(work), str(out), "fake.tar.gz", "fake_dist")
    assert dmg.endswith("RT-4.3.2b2-macos-arm64.dmg")

    # Controlla sequenza chiamate codesign
    codesign_calls = [c for c in calls if c[0] == "codesign"]
    assert len(codesign_calls) == 3

    # 1. Firma del Mach-O interno
    assert codesign_calls[0] == ["codesign", "--force", "--sign", "-", "--timestamp=none", str(work / "dmg" / "RT.app" / "Contents" / "Resources" / "app" / "native.dylib")]
    # 2. Firma del bundle RT.app
    assert codesign_calls[1] == ["codesign", "--force", "--sign", "-", "--timestamp=none", str(work / "dmg" / "RT.app")]
    # 3. Verifica del bundle
    assert codesign_calls[2] == ["codesign", "--verify", "--strict", "--verbose=2", str(work / "dmg" / "RT.app")]

    # 4. dmgbuild
    dmgbuild_call = next(c for c in calls if "dmgbuild" in c)
    assert "-s" in dmgbuild_call
    assert f"app={work / 'dmg' / 'RT.app'}" in dmgbuild_call
    assert dmgbuild_call[-2:] == ["RT", dmg]

