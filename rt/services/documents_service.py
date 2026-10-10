"""Aggiornamento automatico dei documenti: un job per lezione e debounce persistente."""
import json
import time

from rt.core.lesson_lock import lesson_lock
from rt.core.lesson_paths import lesson_path
from rt.services.context import phase_scope
from rt.storage import fs

DEBOUNCE_SECONDS = 3.0
STATE_FILE = "documents.json"


def _load(lesson_dir):
    path = lesson_path(lesson_dir, STATE_FILE)
    if not fs.isfile(path):
        return {}
    with fs.open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def _save(lesson_dir, state):
    path = lesson_path(lesson_dir, STATE_FILE)
    with fs.open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False)
    fs.replace(path + ".tmp", path)


def _ready(lesson_dir):
    return fs.isdir(lesson_dir) and all(fs.isfile(lesson_path(lesson_dir, name))
        for name in ("draft.json", "outline.json", "segments.json", "info.yaml"))


def ensure_documents_queued(lesson_dir, queue=None):
    """Riprende anche un cambio arrivato fra la scrittura e la fine del job precedente."""
    if not _ready(lesson_dir):
        return None
    from rt.db.engine import get_database
    from rt.services.jobs import DbJobQueue, JobState
    with lesson_lock(lesson_dir):
        state = _load(lesson_dir)
        if not state or state.get("version") == state.get("written_version"):
            return None
        db = get_database() if queue is None else None
        if queue is None and db is None:
            return None  # il comando CLI senza DB continua a scrivere con rt build
        queue = queue or DbJobQueue(db)
        active = queue.list(state=[JobState.QUEUED.value, JobState.RUNNING.value],
                            lesson_id=lesson_dir, job_type="documents")
        return active[0].id if active else queue.enqueue("documents", lesson_dir, {}, created_by="documents")


def request_documents(lesson_dir):
    """Segna l'ultimo cambio sotto lo stesso lock di decisione o salvataggio."""
    if not _ready(lesson_dir):
        return None
    with lesson_lock(lesson_dir):
        state = _load(lesson_dir)
        state.update(changed_at=time.time(), version=state.get("version", 0) + 1)
        _save(lesson_dir, state)
        return ensure_documents_queued(lesson_dir)


def run_documents(lesson_dir, ctx=None):
    """Aspetta tre secondi dall'ultimo cambio; non tiene il lock durante l'attesa."""
    from rt.pipeline.build import write_automatic_documents
    from rt.core.process_lock import LessonBusy, lesson_work_lock
    with phase_scope(ctx, "build") as scope:
        while True:
            if ctx:
                ctx.check_cancelled()
            with lesson_lock(lesson_dir):
                state = _load(lesson_dir)
                if not state or state.get("version") == state.get("written_version"):
                    return scope.complete({"status": "updated", "skipped": True, "lesson_dir": lesson_dir})
                remaining = DEBOUNCE_SECONDS - (time.time() - state["changed_at"])
                if remaining <= 0:
                    try:
                        # Il lock di lavorazione copre la scrittura, non il debounce.
                        with lesson_work_lock(lesson_dir):
                            result = write_automatic_documents(lesson_dir)
                            state["written_version"] = state["version"]
                            _save(lesson_dir, state)
                            return scope.complete(result)
                    except LessonBusy:
                        remaining = 0.2  # una modifica CLI finisce prima della scrittura
            time.sleep(min(0.2, remaining))


def documents_pending(lesson_dir):
    """Anche una nuova verifica può aver cambiato soltanto il registro degli errori."""
    state = _load(lesson_dir)
    return bool(state and state.get("version") != state.get("written_version"))


def mark_documents_written(lesson_dir):
    """La build esplicita ha già soddisfatto il lavoro derivato accodato."""
    from rt.db.engine import get_database
    from rt.services.jobs import DbJobQueue
    with lesson_lock(lesson_dir):
        state = _load(lesson_dir)
        if state:
            state["written_version"] = state["version"]
            _save(lesson_dir, state)
        db = get_database()
        if db:
            DbJobQueue(db).complete_queued_documents(lesson_dir)
