"""Il pacchetto toglie le parti superflue della libreria standard e conserva il bytecode."""
import importlib.util
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
