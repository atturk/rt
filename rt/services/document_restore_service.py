"""Copia della versione della pipeline e ripristino delle modifiche manuali."""
import json
import os
from contextlib import nullcontext

from sqlalchemy import select

from rt.core.idempotency import DOCUMENT_EDITS_FILE, IMAGE_PLACEMENT_FILE, check_phase_status, compute_source_fingerprint
from rt.core.lesson_paths import lesson_path
from rt.core.lesson_lock import lesson_locked
from rt.core.process_lock import LessonBusy, lesson_work_lock
from rt.db.engine import get_database
from rt.db.models import Job
from rt.db.session import session_scope
from rt.db.sync import suspend_dual_write
from rt.services.errors import Conflict
from rt.storage import fs

SNAPSHOT_FILE = 'pipeline_version.json'
FILES = ('draft.json', DOCUMENT_EDITS_FILE, IMAGE_PLACEMENT_FILE)


def _read(lesson_dir, filename):
    path = lesson_path(lesson_dir, filename)
    if not fs.isfile(path):
        return None
    with fs.open(path, encoding='utf-8') as stream:
        return stream.read()


def _write(lesson_dir, filename, text):
    path = lesson_path(lesson_dir, filename)
    if text is None:
        if fs.isfile(path):
            fs.remove(path)
        return
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    with fs.open(path + '.tmp', 'w', encoding='utf-8') as stream:
        stream.write(text)
    fs.replace(path + '.tmp', path)


def preserve_pipeline_version(lesson_dir):
    """Prima modifica reale: la copia resta identica ai salvataggi successivi."""
    if fs.isfile(lesson_path(lesson_dir, SNAPSHOT_FILE)):
        return
    data = {'files': {name: _read(lesson_dir, name) for name in FILES},
            'source': compute_source_fingerprint(lesson_dir, 'rewrite')}
    _write(lesson_dir, SNAPSHOT_FILE, json.dumps(data, ensure_ascii=False))


def forget_pipeline_version(lesson_dir):
    """Una nuova rielaborazione apre un nuovo ciclo di modifiche manuali."""
    _write(lesson_dir, SNAPSHOT_FILE, None)


def _snapshot(lesson_dir):
    text = _read(lesson_dir, SNAPSHOT_FILE)
    return json.loads(text) if text else None


def _modified_units(lesson_dir, snapshot):
    original = snapshot['files']
    parse = lambda text: json.loads(text) if text else {}
    before = {u['unit_id']: u for u in parse(original['draft.json']).get('units', [])}
    after = {u['unit_id']: u for u in parse(_read(lesson_dir, 'draft.json')).get('units', [])}
    old_edits = parse(original[DOCUMENT_EDITS_FILE])
    new_edits = parse(_read(lesson_dir, DOCUMENT_EDITS_FILE))
    old_images = parse(original[IMAGE_PLACEMENT_FILE]).get('macros', {})
    new_images = parse(_read(lesson_dir, IMAGE_PLACEMENT_FILE)).get('macros', {})
    old_macros, new_macros = old_edits.get('macros', {}), new_edits.get('macros', {})
    # Una modifica alla sezione o alle sue immagini riguarda tutte le unità della sezione.
    macros = {mid for mid in set(old_macros) | set(new_macros) | set(old_images) | set(new_images)
              if old_macros.get(mid) != new_macros.get(mid) or old_images.get(mid) != new_images.get(mid)}
    return sorted(uid for uid in set(before) | set(after)
                  if before.get(uid) != after.get(uid)
                  or old_edits.get('units', {}).get(uid) != new_edits.get('units', {}).get(uid)
                  or uid.rsplit('.', 1)[0] in macros)


def pipeline_version(lesson_dir):
    snapshot = _snapshot(lesson_dir)
    return {'available': snapshot is not None,
            'modified_units': len(_modified_units(lesson_dir, snapshot)) if snapshot else 0}


@lesson_locked
def restore_pipeline_version(lesson_id, lesson_dir, lease_token=None):
    try:
        with lesson_work_lock(lesson_dir):
            result = _restore_locked(lesson_id, lesson_dir, lease_token)
        from rt.services.documents_service import request_documents
        request_documents(lesson_dir)
        return result
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None


def _restore_locked(lesson_id, lesson_dir, lease_token):
    db = get_database()
    before = {name: _read(lesson_dir, name) for name in FILES}
    try:
        with session_scope(db) if db else nullcontext() as session, suspend_dual_write():
            if session is not None:
                busy = session.scalar(select(Job.id).where(Job.lesson_path == lesson_dir,
                    Job.state.in_(['queued', 'running', 'waiting_for_decision']), Job.type != 'documents').limit(1))
                if busy:
                    raise Conflict('lesson_busy', 'La lezione ha un job attivo o in attesa.')
                # read_scope riusa questa transazione anche per il lease.
                from rt.db.models import Setting
                from rt.services.document_edit_lease import _key, _active, DocumentBeingEdited
                row = session.get(Setting, _key(lesson_id))
                if row and _active(row.value) and row.value.get('token') != lease_token:
                    raise DocumentBeingEdited()
                if lease_token and (not row or not _active(row.value) or row.value.get('token') != lease_token):
                    raise Conflict('document_edit_invalid', 'Sessione di modifica scaduta.')
            snapshot = _snapshot(lesson_dir)
            if snapshot is None:
                raise Conflict('pipeline_version_missing', 'Nessuna versione della pipeline da ripristinare.')
            if snapshot['source'] != compute_source_fingerprint(lesson_dir, 'rewrite'):
                raise Conflict('pipeline_version_stale', 'La scaletta o i segmenti sono cambiati: rielabora la lezione.')
            units = _modified_units(lesson_dir, snapshot)
            for name in FILES:
                _write(lesson_dir, name, snapshot['files'][name])
            status, reason = check_phase_status(lesson_dir, 'build')
            return {'modified_units': len(units), 'units_changed': units,
                    'build_status': status.value, 'build_reason': reason}
    except BaseException:
        if not fs.is_db_lesson(lesson_dir):
            for name, text in before.items():
                _write(lesson_dir, name, text)
        raise
