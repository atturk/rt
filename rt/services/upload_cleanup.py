"""Inventario conservativo degli upload temporanei, con cancellazione esplicita."""

import os
import re
import shutil
import time
from datetime import datetime, timezone

from sqlalchemy import select

from rt.services.errors import Conflict, NotFound
from rt.db.engine import get_database
from rt.db.models import Job
from rt.db.session import session_scope
from rt.services.jobs import ACTIVE_STATES
from rt.services.lesson_service import lessons_root

_UPLOAD_ID = re.compile(r"[0-9a-f]{32}\Z")
RECENT_SECONDS = 3600


def _root() -> str:
    base = lessons_root() or os.path.expanduser("~")
    return os.path.join(base, ".rt", "uploads")


def _references() -> dict[str, list[dict]]:
    refs: dict[str, list[dict]] = {}
    with session_scope(get_database()) as session:
        for job in session.scalars(select(Job)):
            path = (job.payload or {}).get("upload_dir")
            if isinstance(path, str):
                refs.setdefault(os.path.abspath(path), []).append({"id": job.id, "state": job.state})
    return refs


def _item(root: str, name: str, refs: dict) -> dict | None:
    if not _UPLOAD_ID.fullmatch(name):
        return None
    path = os.path.join(root, name)
    if os.path.islink(path) or not os.path.isdir(path):
        return None
    jobs = refs.get(os.path.abspath(path), [])
    # Un upload appena scritto può non avere ancora il suo job (salvataggio in corso): lo si
    # tratta come attivo per RECENT_SECONDS, così non compare tra quelli eliminabili.
    recent = time.time() - os.path.getmtime(path) < RECENT_SECONDS
    state = ("active" if recent or any(j["state"] in ACTIVE_STATES for j in jobs)
             else "referenced" if jobs else "orphan")
    return {"id": name, "state": state, "job_ids": [j["id"] for j in jobs],
            "files": len([entry for entry in os.scandir(path) if entry.is_file(follow_symlinks=False)]),
            "modified_at": datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()}


def list_uploads() -> list[dict]:
    root = _root()
    if not os.path.isdir(root):
        return []
    refs = _references()
    return [item for name in sorted(os.listdir(root)) if (item := _item(root, name, refs))]


def delete_orphan(upload_id: str, include_referenced: bool = False) -> None:
    """Elimina un upload orfano; con include_referenced anche quello di un job concluso senza
    successo (fallito o annullato): il job non si potrà più riprovare. Mai quelli attivi."""
    if not _UPLOAD_ID.fullmatch(upload_id):
        raise NotFound("upload_not_found", "Upload non trovato.")
    root = _root()
    item = _item(root, upload_id, _references())
    if item is None:
        raise NotFound("upload_not_found", "Upload non trovato.")
    if item["state"] == "active":
        raise Conflict("upload_active", "L'upload è in uso da un job in corso o appena caricato.")
    if item["state"] == "referenced" and not include_referenced:
        raise Conflict("upload_referenced", "L'upload è associato a un job: conferma che il job non verrà ripreso.")
    # L'ID è un nome UUID generato dal server e la directory non è un symlink.
    shutil.rmtree(os.path.join(root, upload_id))
