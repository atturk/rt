"""Stato del promemoria periodico per sostenere RT (<config_dir>/supporto.json)."""
from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from rt.core.paths import config_dir

SupportEvent = Literal["opened", "hidden", "donated", "already_donated"]

# Giorni d'uso: il bottone compare ogni 20, nascosto con la pressione lunga ogni 30.
# Solo «Ho già donato» lo mette in pausa per 6 mesi (RT non può verificare la donazione).
INITIAL_DAYS = 20
REAPPEAR_DAYS = 20
HIDDEN_DAYS = 30
DONATED_PAUSE_DAYS = 182

_LOCK = threading.Lock()


def initial_state() -> dict[str, Any]:
    """Stato iniziale del promemoria."""
    return {
        "used_days": 0,
        "last_day": None,
        "next_at": INITIAL_DAYS,
        "hide_streak": 0,
        "paused_until": None,
    }


def _valid_int(value: Any, default: int, minimum: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
        return value
    return default


def _valid_iso_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _normalize_state(raw: Any) -> dict[str, Any]:
    defaults = initial_state()
    if not isinstance(raw, dict):
        return defaults
    return {
        "used_days": _valid_int(raw.get("used_days"), defaults["used_days"], minimum=0),
        "last_day": _valid_iso_date(raw.get("last_day")),
        "next_at": _valid_int(raw.get("next_at"), defaults["next_at"], minimum=0),
        "hide_streak": _valid_int(raw.get("hide_streak"), defaults["hide_streak"], minimum=0),
        "paused_until": _valid_iso_date(raw.get("paused_until")),
    }


def register_day(state: dict[str, Any], today: date) -> dict[str, Any]:
    """Conta il giorno d'uso se non è già stato registrato oggi."""
    today_iso = today.isoformat()
    if state.get("last_day") == today_iso:
        return dict(state)
    return {
        **state,
        "used_days": state["used_days"] + 1,
        "last_day": today_iso,
    }


def is_visible(state: dict[str, Any], today: date) -> bool:
    """True quando sono passati abbastanza giorni d'uso e l'eventuale pausa è scaduta."""
    if state["used_days"] < state["next_at"]:
        return False
    paused_until = state.get("paused_until")
    if paused_until:
        try:
            if today < date.fromisoformat(paused_until):
                return False
        except ValueError:
            pass
    return True


def on_opened(state: dict[str, Any]) -> dict[str, Any]:
    """Clic sul bottone della barra: ripropone dopo 20 giorni d'uso."""
    return {
        **state,
        "next_at": state["used_days"] + REAPPEAR_DAYS,
        "hide_streak": 0,
    }


def on_hidden(state: dict[str, Any]) -> dict[str, Any]:
    """Pressione lunga per nascondere: ripropone dopo 30 giorni d'uso."""
    return {
        **state,
        "hide_streak": state["hide_streak"] + 1,
        "next_at": state["used_days"] + HIDDEN_DAYS,
    }


def on_donated(state: dict[str, Any]) -> dict[str, Any]:
    """Clic su «Dona con Ko-fi»: apre solo Ko-fi, il bottone torna dopo 20 giorni d'uso."""
    return on_opened(state)


def on_already_donated(state: dict[str, Any], today: date) -> dict[str, Any]:
    """«Ho già donato»: pausa di 182 giorni di calendario, sulla parola."""
    return {
        **state,
        "paused_until": (today + timedelta(days=DONATED_PAUSE_DAYS)).isoformat(),
        "next_at": state["used_days"] + REAPPEAR_DAYS,
        "hide_streak": 0,
    }


def state_path() -> Path:
    return Path(config_dir()) / "supporto.json"


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or state_path()
    try:
        with open(target, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return initial_state()
    return _normalize_state(raw)


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def check_support_prompt(today: date | None = None) -> bool:
    """Registra il giorno d'uso locale, salva e restituisce se il bottone va mostrato."""
    current_day = today or date.today()
    with _LOCK:
        state = load_state()
        updated = register_day(state, current_day)
        if updated != state:
            try:
                save_state(updated)
            except OSError:
                return False
        return is_visible(updated, current_day)


def record_support_event(event: SupportEvent, today: date | None = None) -> bool:
    """Applica l'evento sul promemoria, salva e restituisce la visibilità risultante."""
    current_day = today or date.today()
    with _LOCK:
        state = load_state()
        if event == "opened":
            updated = on_opened(state)
        elif event == "hidden":
            updated = on_hidden(state)
        elif event == "donated":
            updated = on_donated(state)
        elif event == "already_donated":
            updated = on_already_donated(state, current_day)
        else:
            raise ValueError(f"Evento non valido: {event}")
        try:
            save_state(updated)
        except OSError:
            return False
        return is_visible(updated, current_day)
