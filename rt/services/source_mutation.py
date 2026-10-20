"""Esclusione mutua e lease per le modifiche alle fonti di una lezione."""
from contextlib import contextmanager

from rt.core.process_lock import lesson_work_lock, LessonBusy
from rt.services.document_edit_lease import assert_editable
from rt.services.errors import Conflict
from rt.services.jobs import get_job_queue


@contextmanager
def source_mutation(lesson_id, lesson_dir, *, allow_documents=True):
    try:
        with lesson_work_lock(lesson_dir):
            assert_editable(lesson_id)
            busy = [job for job in get_job_queue().list(state=['queued', 'running', 'waiting_for_decision'],
                                                       lesson_id=lesson_dir)
                    if job.type != 'documents' or not allow_documents]
            if busy:
                raise Conflict('lesson_busy', 'La lezione ha un lavoro attivo o in attesa.')
            yield
    except LessonBusy:
        raise Conflict('lesson_busy', 'La lezione è in lavorazione.') from None
