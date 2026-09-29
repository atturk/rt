import asyncio
import json
import os
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from rt.services.errors import ServiceError
from rt.services.telegram_user_archive import export_topic
from rt.services.telegram_user_archive import request_code
from rt.db.models import Setting
from rt.db.session import session_scope


class FakeClient:
    get_entity = AsyncMock(return_value="forum")
    disconnect = AsyncMock()

    def __init__(self, fail_media=False):
        self.fail_media = fail_media

    async def get_messages(self, *_args, **_kwargs):
        return SimpleNamespace(id=42, date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                               sender_id=1, raw_text="Inizio", media=None)

    async def iter_messages(self, *_args, **_kwargs):
        yield SimpleNamespace(id=43, date=datetime(2026, 1, 2, tzinfo=timezone.utc),
                              sender_id=2, raw_text="Domanda <test>", media=object())

    async def download_media(self, _message, file):
        if self.fail_media:
            return None
        with open(file + ".ogg", "wb") as output:
            output.write(b"audio")
        return file + ".ogg"


def test_topic_archive_contains_users_bot_and_media(tmp_path):
    with patch("rt.services.telegram_user_archive._authorized_client", new=AsyncMock(return_value=FakeClient())), \
         patch("rt.services.telegram_user_archive.tempfile.mkdtemp", side_effect=lambda **_: str(tmp_path)):
        path, folder = asyncio.run(export_topic(-1001, 42))
    with zipfile.ZipFile(path) as zipped:
        assert sorted(zipped.namelist()) == ["index.html", "index.json", "media/43.ogg"]
        data = json.loads(zipped.read("index.json"))
        assert data["complete"] is True and len(data["messages"]) == 2
        assert data["messages"][1]["media"]["sha256"]
        assert b"&lt;test&gt;" in zipped.read("index.html")


def test_topic_archive_fails_if_media_missing(tmp_path):
    with patch("rt.services.telegram_user_archive._authorized_client", new=AsyncMock(return_value=FakeClient(True))), \
         patch("rt.services.telegram_user_archive.tempfile.mkdtemp", side_effect=lambda **_: str(tmp_path)):
        with pytest.raises(ServiceError, match="Media"):
            asyncio.run(export_topic(-1001, 42))


def test_pending_telegram_login_does_not_store_api_hash(rt_db, monkeypatch):
    class LoginClient:
        connect = AsyncMock()
        disconnect = AsyncMock()
        send_code_request = AsyncMock(return_value=SimpleNamespace(phone_code_hash="code-hash"))
        session = SimpleNamespace(save=lambda: "temporary-session")

    monkeypatch.setattr("rt.services.telegram_user_archive._client", lambda *_: LoginClient())
    asyncio.run(request_code(12345, "private-api-hash", "+391234567890"))
    with session_scope(rt_db) as session:
        saved = session.get(Setting, "telegram_user_pending_login")
        dumped = json.dumps(saved.value)
        assert saved and "private-api-hash" not in dumped and "temporary-session" not in dumped


def test_login_saves_session_as_a_secret_not_as_a_file(rt_db, monkeypatch, tmp_path):
    """La chiave di autorizzazione Telegram finisce con gli altri segreti, non in un file SQLite."""
    from rt.services import telegram_user_archive as archive
    used_sessions = []

    class LoginClient:
        connect = AsyncMock()
        disconnect = AsyncMock()
        send_code_request = AsyncMock(return_value=SimpleNamespace(phone_code_hash="code-hash"))
        sign_in = AsyncMock()
        is_user_authorized = AsyncMock(return_value=True)

        def __init__(self, session):
            used_sessions.append(session)
            self.session = SimpleNamespace(save=lambda: "authorized-session" if session else "temporary-session")

    env = tmp_path / ".env"
    monkeypatch.setattr(archive, "_env_path", lambda: env)
    monkeypatch.setattr(archive, "data_dir", lambda: str(tmp_path / "data"))
    monkeypatch.setattr(archive, "_client", lambda _id, _hash, session="": LoginClient(session))
    for name in ("RT_TELEGRAM_USER_API_ID", "RT_TELEGRAM_USER_API_HASH", archive.SESSION_SECRET):
        monkeypatch.delenv(name, raising=False)
    asyncio.run(request_code(12345, "private-api-hash", "+391234567890"))
    asyncio.run(archive.complete_login("12345"))
    assert used_sessions == ["", "temporary-session"]  # la conferma riusa la chiave del codice
    assert 'RT_TELEGRAM_USER_SESSION="authorized-session"' in env.read_text()
    assert oct(env.stat().st_mode & 0o777) == "0o600"
    assert not (tmp_path / "data" / "telegram-user").exists()
    with session_scope(rt_db) as session:
        assert session.get(Setting, "telegram_user_pending_login") is None


def test_legacy_plaintext_session_is_migrated_and_deleted(monkeypatch, tmp_path):
    from telethon.crypto import AuthKey
    from telethon.sessions import SQLiteSession, StringSession
    from rt.services import telegram_user_archive as archive

    folder = tmp_path / "telegram-user"
    folder.mkdir()
    old = SQLiteSession(str(folder / "authorized"))
    old.set_dc(2, "149.154.167.51", 443)
    old.auth_key = AuthKey(os.urandom(256))
    old.save()
    old.close()
    env = tmp_path / ".env"
    monkeypatch.setattr(archive, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(archive, "_env_path", lambda: env)
    monkeypatch.delenv(archive.SESSION_SECRET, raising=False)

    value = archive._saved_session()
    assert StringSession(value).auth_key.key == old.auth_key.key
    assert not (folder / "authorized.session").exists()
    assert archive.SESSION_SECRET in env.read_text()
    assert archive._saved_session() == value  # la seconda volta legge il segreto
