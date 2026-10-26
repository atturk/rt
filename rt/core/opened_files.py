"""Gestione dei file aperti con RT (Dock, 'Apri con', doppio clic, trascina su icona)."""
import json
import logging
import os
import re
import secrets
import time
from typing import Optional

from rt.core import paths

log = logging.getLogger(__name__)

ACCEPTED_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".ogg",
    ".flac",
    ".wma",
    ".opus",
    ".pdf",
    ".pptx",
    ".docx",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".zip",
}

TOKEN_MAX_AGE_SECONDS = 10 * 60  # 10 minuti
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _log(message: str) -> None:
    try:
        from rt.desktop import _sayer
        _sayer()(message)
    except Exception:
        log.info("%s", message)


def opened_dir() -> str:
    target = os.path.join(paths.sub_dir("run", create=True), "opened")
    os.makedirs(target, exist_ok=True)
    return target


def register_file(file_path: str) -> Optional[dict]:
    """Registra un file aperto con RT in run/opened/<token>.json con permessi 0600."""
    try:
        real_path = os.path.abspath(file_path)
        if not os.path.isfile(real_path):
            return None
        _, ext = os.path.splitext(real_path)
        if ext.lower() not in ACCEPTED_EXTENSIONS:
            return None
        token = secrets.token_urlsafe(24)
        name = os.path.basename(real_path)
        size = os.path.getsize(real_path)
        created = time.time()
        data = {
            "token": token,
            "path": real_path,
            "name": name,
            "size": size,
            "created": created,
        }
        json_path = os.path.join(opened_dir(), f"{token}.json")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(json_path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        _log(f"File aperto: {real_path}")
        return {"token": token, "name": name, "size": size, "created": created}
    except Exception as exc:
        _log(f"Impossibile registrare il file aperto {file_path}: {exc}")
        return None


def consume_token(token: str) -> Optional[str]:
    """Valida il token, restituisce il percorso del file e rimuove il token (monouso)."""
    if not token or not SAFE_TOKEN_RE.fullmatch(token):
        return None
    token_path = os.path.join(opened_dir(), f"{token}.json")
    if not os.path.isfile(token_path):
        return None
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        _remove(token_path)
        return None

    if not isinstance(data, dict):
        _remove(token_path)
        return None

    created = data.get("created", 0)
    if time.time() - created > TOKEN_MAX_AGE_SECONDS:
        _remove(token_path)
        return None

    target_file = data.get("path")
    if not target_file or not os.path.isfile(target_file):
        _remove(token_path)
        return None

    _, ext = os.path.splitext(target_file)
    if ext.lower() not in ACCEPTED_EXTENSIONS:
        _remove(token_path)
        return None

    _remove(token_path)
    return target_file


def get_unannounced_tokens(since: float = 0.0, exclude: Optional[set] = None) -> list[dict]:
    """Restituisce i file registrati in run/opened/ creati dopo since e non esclusi."""
    exclude_set = exclude or set()
    result = []
    directory = opened_dir()
    try:
        entries = os.listdir(directory)
    except OSError:
        return []

    for fname in entries:
        if not fname.endswith(".json"):
            continue
        token = fname[:-5]
        if token in exclude_set or not SAFE_TOKEN_RE.fullmatch(token):
            continue
        fpath = os.path.join(directory, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            created = data.get("created", 0)
            if created >= since and (time.time() - created <= TOKEN_MAX_AGE_SECONDS):
                result.append({"token": token, "name": data.get("name", ""), "size": data.get("size", 0)})
        except Exception:
            continue
    return result


def cleanup_expired(max_age_seconds: int = TOKEN_MAX_AGE_SECONDS) -> None:
    """Cancella i file token scaduti in run/opened/."""
    directory = opened_dir()
    now = time.time()
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for fname in entries:
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(directory, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if now - data.get("created", 0) > max_age_seconds:
                _remove(fpath)
        except Exception:
            _remove(fpath)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
