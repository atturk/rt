"""
tests/test_secret_store.py
RT4-C1: archivio segreti cifrato (rt/security/secrets.py) e priorità delle sorgenti.
"""
import json
import logging
import os
import stat
import sys

import pytest

from rt.core.config import load_env_file
from rt.llm.credentials import GLOBAL_CREDENTIALS, CredentialRef
from rt.security import secrets as sec
from rt.security.secrets import (
    EncryptedFileSecretStore,
    EnvSecretStore,
    SecretStoreError,
    generate_master_key,
)

SECRET = "sk-or-v1-supersegreto-0123456789"


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    """Archivio in tmp_path, chiave in RT_MASTER_KEY, nessun accesso al portachiavi."""
    key = generate_master_key()
    path = tmp_path / "config" / "secrets.enc"
    monkeypatch.setenv("RT_SECRETS_FILE", str(path))
    monkeypatch.setenv("RT_MASTER_KEY", key)
    monkeypatch.setattr(sec, "keyring_get_master_key", lambda: None)
    sec._reset_for_tests()
    yield path, key
    sec._reset_for_tests()


def test_encrypt_decrypt_roundtrip(store_env):
    path, _ = store_env
    store = EncryptedFileSecretStore(path)
    store.set("OPENROUTER_API_KEY", SECRET)
    store.set("RT_TELEGRAM_BOT_TOKEN", "123456:telegram-token-abc")

    raw = path.read_text(encoding="utf-8")
    assert SECRET not in raw and "telegram-token" not in raw
    assert json.loads(raw)["version"] == 1

    fresh = EncryptedFileSecretStore(path)
    assert fresh.get("OPENROUTER_API_KEY") == SECRET
    assert fresh.list_names() == ["OPENROUTER_API_KEY", "RT_TELEGRAM_BOT_TOKEN"]
    assert set(fresh.metadata()["OPENROUTER_API_KEY"]) == {"updated_at"}
    assert fresh.delete("OPENROUTER_API_KEY") is True
    assert fresh.delete("OPENROUTER_API_KEY") is False
    assert fresh.get("OPENROUTER_API_KEY") is None


@pytest.mark.skipif(sys.platform == "win32", reason="permessi POSIX")
def test_file_permissions_are_600(store_env):
    path, _ = store_env
    EncryptedFileSecretStore(path).set("X_API_KEY", SECRET)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]


def test_wrong_key_gives_clear_error_without_values(store_env):
    path, _ = store_env
    EncryptedFileSecretStore(path).set("X_API_KEY", SECRET)
    other = generate_master_key()
    with pytest.raises(SecretStoreError) as exc:
        EncryptedFileSecretStore(path, master_key=other).get("X_API_KEY")
    msg = str(exc.value)
    assert "chiave master" in msg
    assert SECRET not in msg and other not in msg


def test_corrupted_file(store_env):
    path, key = store_env
    EncryptedFileSecretStore(path).set("X_API_KEY", SECRET)
    path.write_text("{non json", encoding="utf-8")
    with pytest.raises(SecretStoreError, match="danneggiato"):
        EncryptedFileSecretStore(path).get("X_API_KEY")
    envelope = {"version": 1, "cipher": "fernet", "token": "gAAAAA-alterato"}
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(SecretStoreError) as exc:
        EncryptedFileSecretStore(path).get("X_API_KEY")
    assert key not in str(exc.value)


def test_invalid_master_key_format(tmp_path):
    with pytest.raises(SecretStoreError, match="non valida") as exc:
        EncryptedFileSecretStore(tmp_path / "s.enc", master_key="corta").set("A", "valore-lungo")
    assert "corta" not in str(exc.value)


def test_missing_master_key_explains_how_to_fix(store_env, monkeypatch):
    path, _ = store_env
    EncryptedFileSecretStore(path).set("X_API_KEY", SECRET)
    monkeypatch.delenv("RT_MASTER_KEY")
    with pytest.raises(SecretStoreError, match="RT_MASTER_KEY"):
        EncryptedFileSecretStore(path).get("X_API_KEY")


def test_master_key_from_keyring(store_env, monkeypatch):
    path, key = store_env
    EncryptedFileSecretStore(path).set("X_API_KEY", SECRET)
    monkeypatch.delenv("RT_MASTER_KEY")
    monkeypatch.setattr(sec, "keyring_get_master_key", lambda: key)
    assert EncryptedFileSecretStore(path).get("X_API_KEY") == SECRET


def test_rotation_with_multifernet(store_env, monkeypatch):
    path, old = store_env
    store = EncryptedFileSecretStore(path)
    store.set("X_API_KEY", SECRET)
    new = generate_master_key()
    store.rotate(new)
    with pytest.raises(SecretStoreError):
        EncryptedFileSecretStore(path, master_key=old).get("X_API_KEY")
    assert EncryptedFileSecretStore(path, master_key=new).get("X_API_KEY") == SECRET
    # Durante la transizione "nuova,vecchia" legge tutto.
    assert EncryptedFileSecretStore(path, master_key=f"{new},{old}").get("X_API_KEY") == SECRET


def test_env_store_is_read_only(monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", " valore ")
    store = EnvSecretStore()
    assert store.get("SOME_API_KEY") == "valore"
    with pytest.raises(SecretStoreError):
        store.set("SOME_API_KEY", "x")


# ---------------------------------------------------------------------------
# Priorità: ambiente esplicito > store cifrato > .env
# ---------------------------------------------------------------------------

@pytest.fixture
def credential(monkeypatch):
    GLOBAL_CREDENTIALS.register(CredentialRef(name="c1test", provider="openrouter", env_var="C1TEST_API_KEY"))
    monkeypatch.delenv("C1TEST_API_KEY", raising=False)
    yield "C1TEST_API_KEY"
    os.environ.pop("C1TEST_API_KEY", None)


def test_without_store_everything_works_as_before(tmp_path, monkeypatch, credential):
    monkeypatch.setenv("RT_SECRETS_FILE", str(tmp_path / "config" / "secrets.enc"))
    monkeypatch.delenv("RT_MASTER_KEY", raising=False)
    monkeypatch.setattr(sec, "keyring_get_master_key", lambda: pytest.fail("portachiavi interrogato"))
    sec._reset_for_tests()
    env = tmp_path / ".env"
    env.write_text(f"{credential}=da-dotenv-12345\n", encoding="utf-8")
    load_env_file(str(env))
    assert GLOBAL_CREDENTIALS.get_api_key("c1test") == "da-dotenv-12345"


def test_store_beats_dotenv(tmp_path, store_env, credential, caplog):
    path, _ = store_env
    EncryptedFileSecretStore(path).set(credential, "da-store-12345")
    env = tmp_path / ".env"
    env.write_text(f"{credential}=da-dotenv-12345\n", encoding="utf-8")
    load_env_file(str(env), override=True)
    assert GLOBAL_CREDENTIALS.get_api_key("c1test") == "da-store-12345"
    assert sec.source_of(credential) == "store"
    # Una seconda override=True (come fa rt.cli.main) non riporta il valore di .env.
    load_env_file(str(env), override=True)
    assert os.environ[credential] == "da-store-12345"


def test_explicit_env_beats_store(tmp_path, store_env, credential, monkeypatch):
    path, _ = store_env
    EncryptedFileSecretStore(path).set(credential, "da-store-12345")
    monkeypatch.setenv(credential, "esportata-a-mano")
    load_env_file(str(tmp_path / "manca.env"))
    assert GLOBAL_CREDENTIALS.get_api_key("c1test") == "esportata-a-mano"


def test_store_updates_are_picked_up(tmp_path, store_env, credential):
    path, _ = store_env
    store = EncryptedFileSecretStore(path)
    store.set(credential, "primo-valore-123")
    load_env_file(str(tmp_path / "manca.env"))
    assert os.environ[credential] == "primo-valore-123"
    store.set(credential, "secondo-valore-456")
    load_env_file(str(tmp_path / "manca.env"))
    assert os.environ[credential] == "secondo-valore-456"


def test_plaintext_dotenv_warns_once_when_store_exists(tmp_path, store_env, credential, caplog):
    path, _ = store_env
    EncryptedFileSecretStore(path).set("ALTRO_API_KEY", "altro-valore-123")
    env = tmp_path / ".env"
    env.write_text(f"{credential}=in-chiaro-12345\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="rt.security.secrets"):
        load_env_file(str(env), override=True)
        load_env_file(str(env), override=True)
    warnings = [r for r in caplog.records if credential in r.getMessage()]
    assert len(warnings) == 1
    assert "rt secrets migrate" in warnings[0].getMessage()
    assert "in-chiaro-12345" not in caplog.text
    os.environ.pop("ALTRO_API_KEY", None)


def test_unreadable_store_keeps_dotenv_and_warns(tmp_path, store_env, credential, monkeypatch, caplog):
    path, _ = store_env
    EncryptedFileSecretStore(path).set(credential, "da-store-12345")
    monkeypatch.setenv("RT_MASTER_KEY", generate_master_key())
    env = tmp_path / ".env"
    env.write_text(f"{credential}=da-dotenv-12345\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="rt.security.secrets"):
        load_env_file(str(env))
    assert os.environ[credential] == "da-dotenv-12345"
    assert "Segreti cifrati non caricati" in caplog.text


def test_sanitize_redacts_store_values(tmp_path, store_env):
    path, _ = store_env
    token = "987654:token-telegram-dallo-store"
    EncryptedFileSecretStore(path).set("RT_TELEGRAM_BOT_TOKEN", token)
    os.environ["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"
    sec._reset_for_tests()
    os.environ.pop("RT_TELEGRAM_BOT_TOKEN")
    load_env_file(str(tmp_path / "manca.env"))
    try:
        out = GLOBAL_CREDENTIALS.sanitize_secrets(f"errore https://api.telegram.org/bot{token}/send")
        assert token not in out and "[REDACTED]" in out
    finally:
        os.environ["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"
