"""Spazio e svuotamento dei soli tipi di cache rigenerabili."""
from pathlib import Path

import pytest

from rt.storage import fs

ZERO = {"audio": {"entries": 0, "bytes": 0}, "waveform": {"entries": 0, "bytes": 0},
        "total": {"entries": 0, "bytes": 0}}


@pytest.fixture
def cache_root(api_client):
    return Path(fs.data_dir()) / "cache"


def test_cache_size_and_clear_only_known_types(api_client, cache_root):
    for name, data in (("audio/a.m4a", b"audio"), ("audio/old/b.m4a", b"clip"),
                       ("waveform/w.json", b"[3,40,72]"), ("unknown/keep", b"altro")):
        path = cache_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    original = cache_root.parent / "media" / "originale.wav"
    original.parent.mkdir()
    original.write_bytes(b"sorgente")
    expected = {"audio": {"entries": 2, "bytes": 9}, "waveform": {"entries": 1, "bytes": 9},
                "total": {"entries": 3, "bytes": 18}}
    size = api_client.get("/api/v1/system/cache")
    assert size.status_code == 200 and size.json() == expected
    cleared = api_client.delete("/api/v1/system/cache")
    assert cleared.status_code == 200 and cleared.json() == expected
    assert api_client.get("/api/v1/system/cache").json() == ZERO
    assert not list((cache_root / "audio").rglob("*.m4a"))
    assert not list((cache_root / "waveform").iterdir())
    assert (cache_root / "unknown" / "keep").read_bytes() == b"altro"
    assert original.read_bytes() == b"sorgente"
    assert api_client.delete("/api/v1/system/cache").json() == ZERO


def test_absent_cache_is_empty_and_is_not_created(api_client, cache_root):
    assert not cache_root.exists()
    for method in (api_client.get, api_client.delete):
        response = method("/api/v1/system/cache")
        assert response.status_code == 200 and response.json() == ZERO
    assert not cache_root.exists()


@pytest.mark.parametrize("link", ["cache", "kind", "subdir", "file"])
def test_cache_does_not_follow_links_outside_data_dir(api_client, cache_root, tmp_path, link):
    outside = tmp_path / "originals"
    outside.mkdir()
    original = outside / "originale.m4a"
    original.write_bytes(b"originale")
    if link == "cache":
        cache_root.symlink_to(outside, target_is_directory=True)
    else:
        cache_root.mkdir()
        if link == "kind":
            (cache_root / "audio").symlink_to(outside, target_is_directory=True)
        else:
            (cache_root / "audio").mkdir()
            (cache_root / "audio" / "link").symlink_to(outside if link == "subdir" else original,
                                                         target_is_directory=link == "subdir")
    assert api_client.get("/api/v1/system/cache").json() == ZERO
    assert api_client.delete("/api/v1/system/cache").json() == ZERO
    assert original.read_bytes() == b"originale"


def test_cache_requires_authentication(api_client):
    api_client.headers.pop("Authorization")
    assert api_client.get("/api/v1/system/cache").status_code == 401
    assert api_client.delete("/api/v1/system/cache").status_code == 401
