"""Test dell'apertura di file con RT (endpoint /api/v1/system/opened-files/{token})."""
import json
import time

import pytest

from rt.core import opened_files


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "lezione.pdf"
    f.write_bytes(b"%PDF-1.4 test content")
    return f


def test_endpoint_serves_valid_token_once(api_client, tmp_path, monkeypatch, sample_file):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))

    reg = opened_files.register_file(str(sample_file))
    assert reg is not None
    token = reg["token"]

    # Prima richiesta: 200 con il contenuto del file
    res = api_client.get(f"/api/v1/system/opened-files/{token}")
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 test content"

    # Seconda richiesta: 404 (il token è monouso)
    res_second = api_client.get(f"/api/v1/system/opened-files/{token}")
    assert res_second.status_code == 404


def test_endpoint_404_expired_token(api_client, tmp_path, monkeypatch, sample_file):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))

    reg = opened_files.register_file(str(sample_file))
    token = reg["token"]

    # Rendi il token vecchio di 11 minuti
    token_json = tmp_path / "run" / "opened" / f"{token}.json"
    data = json.loads(token_json.read_text())
    data["created"] = time.time() - (11 * 60)
    token_json.write_text(json.dumps(data))

    res = api_client.get(f"/api/v1/system/opened-files/{token}")
    assert res.status_code == 404
    assert not token_json.exists()


def test_endpoint_404_missing_file_or_invalid_extension(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))

    # File non esistente
    missing = tmp_path / "non_esiste.pdf"
    assert opened_files.register_file(str(missing)) is None

    # Estensione non accettata
    bad_ext = tmp_path / "script.sh"
    bad_ext.write_text("echo hi")
    assert opened_files.register_file(str(bad_ext)) is None

    # Se un token manomesso punta a un'estensione non accettata
    token_dir = tmp_path / "run" / "opened"
    token_dir.mkdir(parents=True, exist_ok=True)
    fake_token = "fake_token_123"
    (token_dir / f"{fake_token}.json").write_text(
        json.dumps({"token": fake_token, "path": str(bad_ext), "name": "script.sh", "size": 7, "created": time.time()})
    )
    res = api_client.get(f"/api/v1/system/opened-files/{fake_token}")
    assert res.status_code == 404


def test_endpoint_path_traversal_token_returns_404(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("RT_DATA_DIR", str(tmp_path))
    res = api_client.get("/api/v1/system/opened-files/..%2Fetc%2Fpasswd")
    assert res.status_code in (404, 400)
