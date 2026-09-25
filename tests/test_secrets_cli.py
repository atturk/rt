"""
tests/test_secrets_cli.py
RT4-C2: 'rt secrets' end-to-end su una cartella temporanea con un .env finto, salvataggio dei
segreti dal wizard/web nell'archivio cifrato e suggerimento di migrazione.
"""
import io
import os
import stat
import sys
import types

import pytest

from rt.cli import main
from rt.security import secrets as sec
from rt.security.secrets import EncryptedFileSecretStore, SecretStoreError
from rt.services import config_service, secrets_service

OPENROUTER = "sk-or-v1-chiave-openrouter-0123456789"
TELEGRAM = "123456789:AAH-token-telegram-vero-abcdef"

GENERAL_YAML = """credentials:
  - name: openrouter
    provider: openrouter
    env_var: OPENROUTER_API_KEY
"""


@pytest.fixture
def fake_keyring(monkeypatch):
    vault = {}
    mod = types.ModuleType("keyring")
    mod.get_password = lambda service, user: vault.get((service, user))
    mod.set_password = lambda service, user, value: vault.__setitem__((service, user), value)
    monkeypatch.setitem(sys.modules, "keyring", mod)
    return vault


@pytest.fixture
def workdir(tmp_path, monkeypatch, fake_keyring):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "general.yaml").write_text(GENERAL_YAML, encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "# commento da conservare\n"
        f"OPENROUTER_API_KEY={OPENROUTER}\n"
        f'export RT_TELEGRAM_BOT_TOKEN="{TELEGRAM}"\n'
        "RT_TELEGRAM_CHAT_ID=-100123\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RT_SECRETS_FILE", raising=False)
    monkeypatch.delenv("RT_MASTER_KEY", raising=False)
    for name in ("OPENROUTER_API_KEY", "RT_STT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    sec._reset_for_tests()
    yield tmp_path
    sec._reset_for_tests()
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["RT_TELEGRAM_BOT_TOKEN"] = "test-disabled-token"


def rt(*argv):
    try:
        main(list(argv))
    except SystemExit as exc:
        return exc.code or 0
    return 0


def test_init_migrate_list_end_to_end(workdir, fake_keyring, capsys):
    assert secrets_service.env_needs_migration(workdir / ".env")

    assert rt("secrets", "init") == 0
    out = capsys.readouterr().out
    store_path = workdir / "config" / "secrets.enc"
    assert store_path.is_file() and "portachiavi" in out
    key = fake_keyring[("rt", "master_key")]
    assert key not in out  # nel portachiavi: non viene stampata
    assert not secrets_service.env_needs_migration(workdir / ".env")

    assert rt("secrets", "migrate", "--yes") == 0
    out = capsys.readouterr().out
    assert OPENROUTER not in out and TELEGRAM not in out

    env_text = (workdir / ".env").read_text(encoding="utf-8")
    assert OPENROUTER not in env_text and TELEGRAM not in env_text
    assert "# commento da conservare" in env_text and "RT_TELEGRAM_CHAT_ID=-100123" in env_text
    backups = list(workdir.glob(".env.bak-*"))
    assert len(backups) == 1 and OPENROUTER in backups[0].read_text(encoding="utf-8")
    if sys.platform != "win32":
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600

    store = EncryptedFileSecretStore(store_path)
    assert store.get("OPENROUTER_API_KEY") == OPENROUTER
    assert store.get("RT_TELEGRAM_BOT_TOKEN") == TELEGRAM
    assert store.get("RT_TELEGRAM_CHAT_ID") is None

    # Idempotente: una seconda migrazione non trova nulla e non crea altri backup.
    assert rt("secrets", "migrate", "--yes") == 0
    assert "Nessun segreto da migrare" in capsys.readouterr().out
    assert len(list(workdir.glob(".env.bak-*"))) == 1

    assert rt("secrets", "list") == 0
    out = capsys.readouterr().out
    assert "OPENROUTER_API_KEY" in out and "RT_TELEGRAM_BOT_TOKEN" in out
    assert OPENROUTER not in out and TELEGRAM not in out

    # Dopo la migrazione le credenziali si risolvono dallo store.
    from rt.core.config import load_env_file
    os.environ.pop("OPENROUTER_API_KEY", None)
    load_env_file(override=True)
    assert os.environ["OPENROUTER_API_KEY"] == OPENROUTER


def test_migrate_keep_env_and_conflicts(workdir, capsys):
    assert rt("secrets", "init") == 0
    secrets_service.set_secret("OPENROUTER_API_KEY", "sk-or-v1-valore-piu-recente-999")
    capsys.readouterr()
    assert rt("secrets", "migrate", "--keep-env") == 0
    out = capsys.readouterr().out
    assert "OPENROUTER_API_KEY: nell'archivio c'è un valore diverso" in out
    assert OPENROUTER in (workdir / ".env").read_text(encoding="utf-8")
    assert not list(workdir.glob(".env.bak-*"))
    store = secrets_service.store()
    assert store.get("OPENROUTER_API_KEY") == "sk-or-v1-valore-piu-recente-999"
    assert store.get("RT_TELEGRAM_BOT_TOKEN") == TELEGRAM


def test_migrate_never_strips_env_if_verification_fails(workdir, monkeypatch):
    secrets_service.init_store()
    real_get_all = EncryptedFileSecretStore.get_all
    monkeypatch.setattr(EncryptedFileSecretStore, "get_all",
                        lambda self: {k: "alterato" for k in real_get_all(self)})
    before = (workdir / ".env").read_text(encoding="utf-8")
    with pytest.raises(SecretStoreError, match="Verifica fallita"):
        secrets_service.migrate_env(workdir / ".env", secrets_service.secret_names_from_config(), strip_env=True)
    assert (workdir / ".env").read_text(encoding="utf-8") == before
    assert not list(workdir.glob(".env.bak-*"))


def test_migrate_without_init_fails_cleanly(workdir, capsys):
    assert rt("secrets", "migrate", "--yes") == 1
    assert "rt secrets init" in capsys.readouterr().err


def test_set_unset_via_stdin(workdir, monkeypatch, capsys):
    rt("secrets", "init")
    monkeypatch.setattr(sys, "stdin", io.StringIO("sk-stt-chiave-da-stdin-123\n"))
    assert rt("secrets", "set", "RT_STT_API_KEY", "--stdin") == 0
    assert secrets_service.store().get("RT_STT_API_KEY") == "sk-stt-chiave-da-stdin-123"
    assert os.environ["RT_STT_API_KEY"] == "sk-stt-chiave-da-stdin-123"
    assert rt("secrets", "unset", "RT_STT_API_KEY") == 0
    assert secrets_service.store().get("RT_STT_API_KEY") is None
    assert "sk-stt-chiave-da-stdin" not in capsys.readouterr().out
    os.environ.pop("RT_STT_API_KEY", None)


def test_init_without_keyring_prints_key_once(workdir, capsys):
    assert rt("secrets", "init", "--no-keyring") == 0
    out = capsys.readouterr().out
    assert "RT_MASTER_KEY" in out
    printed = [line.strip() for line in out.splitlines() if len(line.strip()) == 44]
    assert len(printed) == 1
    assert rt("secrets", "init") == 1  # già inizializzato
    os.environ["RT_MASTER_KEY"] = printed[0]
    try:
        assert secrets_service.list_secrets() == {}
    finally:
        os.environ.pop("RT_MASTER_KEY")


def test_rotate_with_keyring(workdir, fake_keyring):
    secrets_service.init_store()
    secrets_service.set_secret("OPENROUTER_API_KEY", OPENROUTER)
    old = fake_keyring[("rt", "master_key")]
    assert rt("secrets", "rotate") == 0
    new = fake_keyring[("rt", "master_key")]
    assert new != old and "," not in new
    path = secrets_service.store().path
    assert EncryptedFileSecretStore(path, master_key=new).get("OPENROUTER_API_KEY") == OPENROUTER
    with pytest.raises(SecretStoreError):
        EncryptedFileSecretStore(path, master_key=old).get("OPENROUTER_API_KEY")


def test_rotate_with_env_key_prints_new_key(workdir, monkeypatch, capsys):
    monkeypatch.setenv("RT_MASTER_KEY", sec.generate_master_key())
    secrets_service.init_store()
    secrets_service.set_secret("OPENROUTER_API_KEY", OPENROUTER)
    capsys.readouterr()
    assert rt("secrets", "rotate") == 0
    out = capsys.readouterr().out
    assert "Aggiorna RT_MASTER_KEY" in out
    new = [line.strip() for line in out.splitlines() if len(line.strip()) == 44][0]
    path = secrets_service.store().path
    assert EncryptedFileSecretStore(path, master_key=new).get("OPENROUTER_API_KEY") == OPENROUTER


# ---------------------------------------------------------------------------
# Wizard e web salvano nello store quando è inizializzato
# ---------------------------------------------------------------------------

def test_set_secret_uses_env_file_without_store(workdir):
    assert config_service.set_secret("DEEPSEEK_API_KEY", "sk-deepseek-123456789") == "env"
    assert 'DEEPSEEK_API_KEY="sk-deepseek-123456789"' in (workdir / ".env").read_text(encoding="utf-8")
    os.environ.pop("DEEPSEEK_API_KEY", None)


def test_set_secret_uses_store_when_initialized(workdir):
    secrets_service.init_store()
    assert config_service.set_secret("DEEPSEEK_API_KEY", "sk-deepseek-123456789") == "store"
    assert "sk-deepseek" not in (workdir / ".env").read_text(encoding="utf-8")
    assert secrets_service.store().get("DEEPSEEK_API_KEY") == "sk-deepseek-123456789"
    os.environ.pop("DEEPSEEK_API_KEY", None)


def test_wizard_saves_to_store(workdir):
    from rt.tui.configure import _save_secret
    secrets_service.init_store()
    _save_secret(str(workdir / ".env"), "RT_TELEGRAM_BOT_TOKEN", "999:token-dal-wizard-abc")
    assert secrets_service.store().get("RT_TELEGRAM_BOT_TOKEN") == "999:token-dal-wizard-abc"
    assert "token-dal-wizard" not in (workdir / ".env").read_text(encoding="utf-8")


def test_web_telegram_settings_keep_chat_id_in_env(workdir):
    from rt.web import settings
    secrets_service.init_store()
    settings.save_telegram(workdir, "999:token-dal-web-abcdef", "-100555", [], "")
    env_text = (workdir / ".env").read_text(encoding="utf-8")
    assert "-100555" in env_text and "token-dal-web" not in env_text
    assert secrets_service.store().get("RT_TELEGRAM_BOT_TOKEN") == "999:token-dal-web-abcdef"


def test_update_hint(workdir, capsys):
    from rt.core.version import _print_secrets_migration_hint
    _print_secrets_migration_hint(str(workdir))
    assert "rt secrets migrate" in capsys.readouterr().out
    secrets_service.init_store()
    _print_secrets_migration_hint(str(workdir))
    assert capsys.readouterr().out == ""


def test_placeholder_env_does_not_trigger_hint(workdir):
    (workdir / ".env").write_text("RT_TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token\n", encoding="utf-8")
    assert not secrets_service.env_needs_migration(workdir / ".env")
