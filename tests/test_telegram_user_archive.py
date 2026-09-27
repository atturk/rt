import asyncio
import json
import os
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from rt.api.errors import ApiError
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
        with pytest.raises(ApiError, match="Media"):
            asyncio.run(export_topic(-1001, 42))


def test_pending_telegram_login_does_not_store_api_hash(rt_db, monkeypatch, tmp_path):
    class LoginClient:
        connect = AsyncMock()
        disconnect = AsyncMock()
        send_code_request = AsyncMock(return_value=SimpleNamespace(phone_code_hash="code-hash"))

    session_path = str(tmp_path / "authorized")
    (tmp_path / "authorized.session").touch()
    monkeypatch.setattr("rt.services.telegram_user_archive._client", lambda *_: LoginClient())
    monkeypatch.setattr("rt.services.telegram_user_archive._session_path", lambda: session_path)
    asyncio.run(request_code(12345, "private-api-hash", "+391234567890"))
    with session_scope(rt_db) as session:
        saved = session.get(Setting, "telegram_user_pending_login")
        assert saved and "private-api-hash" not in json.dumps(saved.value)
