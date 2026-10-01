"""Telegram identity and short-lived credentials limited to the study router."""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import Depends, Request

from rt.api.auth import bearer_scheme, require_auth
from rt.api.errors import ApiError

TTL = 3600
MAX_INIT_AGE = 300
PREFIX = "rtmini."


def _config():
    from rt.core.config import load_env_file
    load_env_file()
    token = (os.environ.get("RT_TELEGRAM_MINI_APP_BOT_TOKEN") or os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")).strip()
    allowed = {v.strip() for v in os.environ.get("RT_TELEGRAM_MINI_APP_USER_IDS", "").split(",") if v.strip()}
    if not token or not allowed:
        raise ApiError(503, "mini_app_not_configured", "Accesso Telegram non configurato in RT.")
    return token, allowed


def _key(token):
    return hmac.new(token.encode(), b"RT-Mini-App-Session-v1", hashlib.sha256).digest()


def verify_init_data(raw: str) -> int:
    token, allowed = _config()
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("duplicate fields")
        supplied = fields.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("signature")
        age = time.time() - int(fields["auth_date"])
        if age < -30 or age > MAX_INIT_AGE:
            raise ValueError("expired")
        user = json.loads(fields["user"])
        uid = user["id"]
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            raise ValueError("user")
    except (ValueError, KeyError, TypeError):
        raise ApiError(401, "telegram_auth_failed", "Apri nuovamente la Mini App da Telegram.")
    if str(uid) not in allowed:
        raise ApiError(403, "telegram_user_forbidden", "Questo account non è autorizzato ad accedere a RT.")
    return uid


def issue_session(uid: int) -> dict:
    token, _ = _config()
    exp = int(time.time()) + TTL
    encoded = base64.urlsafe_b64encode(json.dumps({"user": uid, "exp": exp}, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_key(token), encoded.encode(), hashlib.sha256).hexdigest()
    return {"token": PREFIX + encoded + "." + sig, "expires_at": exp}


def study_actor(request: Request, credentials=Depends(bearer_scheme)) -> str:
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials.startswith(PREFIX):
        token, allowed = _config()
        try:
            encoded, sig = credentials.credentials[len(PREFIX):].split(".")
            if not hmac.compare_digest(hmac.new(_key(token), encoded.encode(), hashlib.sha256).hexdigest(), sig):
                raise ValueError("signature")
            data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if data["exp"] <= time.time() or str(data["user"]) not in allowed:
                raise ValueError("expired")
            return f"telegram-mini-app:{data['user']}"
        except (ValueError, KeyError, TypeError):
            raise ApiError(401, "mini_session_expired", "Sessione scaduta: riapri la Mini App.")
    # Authenticated local preview uses the existing browser session and its CSRF rules.
    return require_auth(request, credentials)


StudyActor = Annotated[str, Depends(study_actor)]
