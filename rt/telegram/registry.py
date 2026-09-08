"""
rt.telegram.registry
Registro globale short_id -> lesson_dir, condiviso tra il processo effimero
'rt run' (che registra) e il daemon persistente (che risolve). Prima scrittura
concorrente multi-processo del progetto: usa un lock a file semplice, nessuna
nuova dipendenza (niente 'filelock').
"""
import os
import json
import time
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any


def _registry_path(state_dir: str) -> str:
    return os.path.join(state_dir, "registry.json")


def _lock_path(state_dir: str) -> str:
    return _registry_path(state_dir) + ".lock"


def _acquire_lock(state_dir: str, retries: int = 5, backoff: float = 0.2) -> None:
    os.makedirs(state_dir, exist_ok=True)
    lock_path = _lock_path(state_dir)
    for attempt in range(retries):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > 30:
                    os.remove(lock_path)  # lock stale, presumibile crash del processo che lo teneva
                    continue
            except FileNotFoundError:
                continue
            time.sleep(backoff * (attempt + 1))
    raise TimeoutError(f"Impossibile acquisire il lock su '{lock_path}' dopo {retries} tentativi.")


def _release_lock(state_dir: str) -> None:
    try:
        os.remove(_lock_path(state_dir))
    except FileNotFoundError:
        pass


def _load_registry(state_dir: str) -> Dict[str, Any]:
    path = _registry_path(state_dir)
    if not os.path.isfile(path):
        return {"schema_version": "1.0", "entries": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(state_dir: str, data: Dict[str, Any]) -> None:
    path = _registry_path(state_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def register_pending(lesson_dir: str, round_: int, kind: str, state_dir: str, message_thread_id: Optional[int] = None) -> str:
    short_id = hashlib.sha256(
        f"{os.path.abspath(lesson_dir)}|{round_}|{datetime.now().isoformat()}".encode("utf-8")
    ).hexdigest()[:10]
    _acquire_lock(state_dir)
    try:
        data = _load_registry(state_dir)
        data["entries"][short_id] = {
            "lesson_dir": os.path.abspath(lesson_dir),
            "round": round_,
            "kind": kind,
            "created_at": datetime.now().isoformat(),
            "message_thread_id": message_thread_id,
        }
        _save_registry(state_dir, data)
    finally:
        _release_lock(state_dir)
    return short_id


def resolve_pending(short_id: str, state_dir: str) -> Optional[Dict[str, Any]]:
    data = _load_registry(state_dir)
    return data["entries"].get(short_id)


def prune_registry(state_dir: str, max_age_days: int = 7) -> None:
    _acquire_lock(state_dir)
    try:
        data = _load_registry(state_dir)
        cutoff = time.time() - max_age_days * 86400
        kept = {}
        for sid, entry in data["entries"].items():
            try:
                created_ts = datetime.fromisoformat(entry["created_at"]).timestamp()
            except Exception:
                created_ts = 0
            if created_ts >= cutoff:
                kept[sid] = entry
        data["entries"] = kept
        _save_registry(state_dir, data)
    finally:
        _release_lock(state_dir)
