"""Authorized Telegram user session for forum discovery and complete topic archives."""

import hashlib
import html
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from rt.api.errors import ApiError
from rt.core.paths import data_dir
from rt.db.engine import get_database
from rt.db.models import Setting
from rt.db.session import session_scope

PENDING_KEY = "telegram_user_pending_login"
_pending_api_hash: dict[str, str] = {}
MAX_MESSAGES = 100_000
MAX_MEDIA_BYTES = 10 * 1024 ** 3


def _session_path() -> str:
    folder = os.path.join(data_dir(), "telegram-user")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    return os.path.join(folder, "authorized")


def _client(api_id: int, api_hash: str):
    from telethon import TelegramClient
    return TelegramClient(_session_path(), api_id, api_hash)


def _credentials() -> tuple[int, str]:
    from rt.core.config import load_env_file
    load_env_file()
    try:
        return int(os.environ["RT_TELEGRAM_USER_API_ID"]), os.environ["RT_TELEGRAM_USER_API_HASH"]
    except (KeyError, ValueError):
        raise ApiError(409, "telegram_user_setup", "Collega prima un account Telegram utente.") from None


async def request_code(api_id: int, api_hash: str, phone: str) -> None:
    if api_id <= 0 or not api_hash.strip() or not phone.strip().startswith("+"):
        raise ApiError(422, "invalid_telegram_login", "Indica API ID, API hash e numero internazionale (+...).")
    client = _client(api_id, api_hash)
    try:
        await client.connect()
        os.chmod(_session_path() + ".session", 0o600)
        result = await client.send_code_request(phone)
        # L'API hash rimane in memoria solo per il tempo necessario alla conferma.
        # Setting è JSON in chiaro e non deve conservare credenziali Telegram.
        _pending_api_hash[phone] = api_hash
        with session_scope(get_database()) as session:
            row = session.get(Setting, PENDING_KEY)
            value = {"phone": phone, "api_id": api_id,
                     "phone_code_hash": result.phone_code_hash, "expires": time.time() + 600}
            if row: row.value = value
            else: session.add(Setting(key=PENDING_KEY, value=value))
    finally:
        await client.disconnect()


async def complete_login(code: str, password: str | None = None) -> None:
    from telethon.errors import SessionPasswordNeededError
    from rt.services import config_service
    with session_scope(get_database()) as session:
        row = session.get(Setting, PENDING_KEY)
        value = row.value if row else None
    if not value or time.time() > value["expires"] or value["phone"] not in _pending_api_hash:
        raise ApiError(409, "telegram_code_expired", "Richiedi un nuovo codice Telegram.")
    api_hash = _pending_api_hash[value["phone"]]
    client = _client(value["api_id"], api_hash)
    try:
        await client.connect()
        try:
            await client.sign_in(phone=value["phone"], code=code, phone_code_hash=value["phone_code_hash"])
        except SessionPasswordNeededError:
            if not password:
                raise ApiError(409, "telegram_password_required", "Serve la password di verifica in due passaggi.") from None
            await client.sign_in(password=password)
        if not await client.is_user_authorized():
            raise ApiError(409, "telegram_user_unauthorized", "Accesso Telegram non completato.")
        os.chmod(_session_path() + ".session", 0o600)
        from rt.core.paths import config_home
        config_service.set_secret("RT_TELEGRAM_USER_API_ID", str(value["api_id"]), path=Path(config_home()) / ".env")
        config_service.set_secret("RT_TELEGRAM_USER_API_HASH", api_hash, path=Path(config_home()) / ".env")
        os.environ["RT_TELEGRAM_USER_API_ID"] = str(value["api_id"])
        os.environ["RT_TELEGRAM_USER_API_HASH"] = api_hash
        _pending_api_hash.pop(value["phone"], None)
        with session_scope(get_database()) as session:
            row = session.get(Setting, PENDING_KEY)
            if row: session.delete(row)
    finally:
        await client.disconnect()


async def _authorized_client():
    client = _client(*_credentials())
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise ApiError(409, "telegram_user_unauthorized", "La sessione utente è scaduta: collegala di nuovo.")
    return client


async def revoke_session() -> None:
    """Revoca la sessione sul server, rimuove il file locale e le credenziali RT."""
    from rt.core.paths import config_home
    from rt.services import config_service, secrets_service
    from rt.security.secrets import store_path_for_env_file
    env_path = Path(config_home()) / ".env"
    try:
        client = await _authorized_client()
    except ApiError:
        client = None
    if client:
        try:
            await client.log_out()
        finally:
            await client.disconnect()
    for suffix in (".session", ".session-journal", ".session-wal", ".session-shm"):
        try:
            os.unlink(_session_path() + suffix)
        except FileNotFoundError:
            pass
    secret_path = store_path_for_env_file(env_path)
    for name in ("RT_TELEGRAM_USER_API_ID", "RT_TELEGRAM_USER_API_HASH"):
        if secret_path.is_file():
            secrets_service.unset_secret(name, path=secret_path)
        if env_path.is_file():
            config_service.set_env_var(env_path, name, "")
        os.environ.pop(name, None)


async def list_topics(chat_id: int) -> list[dict]:
    from telethon.tl.functions.messages import GetForumTopicsRequest
    client = await _authorized_client()
    try:
        entity = await client.get_entity(chat_id)
        offset_date = None
        offset_id = offset_topic = 0
        topics = []
        while True:
            page = await client(GetForumTopicsRequest(entity, offset_date=offset_date,
                offset_id=offset_id, offset_topic=offset_topic, limit=100, q=""))
            found = list(page.topics)
            if not found: break
            topics.extend({"id": t.id, "name": t.title} for t in found)
            last = found[-1]
            if len(found) < 100: break
            offset_topic, offset_id = last.id, last.top_message
            offset_date = getattr(last, "date", None)
        return topics
    finally:
        await client.disconnect()


async def export_topic(chat_id: int, topic_id: int) -> tuple[str, str]:
    client = await _authorized_client()
    folder = tempfile.mkdtemp(prefix="rt-topic-")
    os.chmod(folder, 0o700)
    output = os.path.join(folder, f"topic-{topic_id}.zip")
    try:
        entity = await client.get_entity(chat_id)
        records, media_files, total_size = [], [], 0
        root = await client.get_messages(entity, ids=topic_id)
        messages = client.iter_messages(entity, reply_to=topic_id, reverse=True)

        async def append_message(message):
            nonlocal total_size
            if len(records) >= MAX_MESSAGES:
                raise ApiError(413, "topic_limit", "Topic troppo grande: archivio non creato.")
            record = {"id": message.id, "date": message.date.isoformat() if message.date else None,
                      "sender_id": message.sender_id, "text": message.raw_text or "", "media": None}
            if message.media:
                target = os.path.join(folder, f"media-{message.id}")
                saved = await client.download_media(message, file=target)
                if not saved or not os.path.isfile(saved):
                    raise ApiError(502, "media_download_failed", f"Media del messaggio {message.id} non scaricato.")
                size = os.path.getsize(saved)
                total_size += size
                if total_size > MAX_MEDIA_BYTES:
                    raise ApiError(413, "topic_limit", "Media troppo grandi: archivio non creato.")
                name = f"media/{message.id}{os.path.splitext(saved)[1]}"
                with open(saved, "rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                record["media"] = {"path": name, "size": size, "sha256": digest}
                media_files.append((saved, name))
            records.append(record)

        if root:
            await append_message(root)
        async for message in messages:
            if not root or message.id != root.id:
                await append_message(message)
        records.sort(key=lambda item: item["id"])
        document = {"format": "rt-telegram-topic", "version": 1, "chat_id": chat_id,
                    "topic_id": topic_id, "complete": True, "messages": records}
        markup = "<!doctype html><meta charset='utf-8'><title>Topic Telegram</title><h1>Topic Telegram</h1>" + "".join(
            f"<article><h2>{r['id']} · {html.escape(r['date'] or '')} · {r['sender_id']}</h2>"
            f"<p>{html.escape(r['text']).replace(chr(10), '<br>')}</p>" +
            (f"<a href='{r['media']['path']}'>Media</a>" if r['media'] else "") + "</article>" for r in records)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr("index.json", json.dumps(document, ensure_ascii=False, indent=2))
            zipped.writestr("index.html", markup)
            for source, name in media_files:
                zipped.write(source, name)
        return output, folder
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await client.disconnect()
