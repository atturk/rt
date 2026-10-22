"""Creazione di una lezione con fonti miste, mantenendo l'import storico separato."""
import os
import uuid
from datetime import datetime, timezone

import yaml

from rt.core.lesson_paths import lesson_path
from rt.core.sources import add_source
from rt.core.source_selection import set_primary
from rt.pipeline.setup import parse_flexible_date, sanitize_filename_part
from rt.storage import fs


def create_source_lesson(*, audio, materiali, appunti='', principale=None, allega_materiali=True,
                         unisci=True, opzioni=None,
                         date, materia, argomenti='', docente='', ora='', dest_dir):
    date = parse_flexible_date(date)
    materia = sanitize_filename_part((materia or '').strip().upper())
    if not materia:
        raise ValueError('Indica la materia')
    if not audio and not materiali and not (appunti or '').strip():
        raise ValueError('Aggiungi almeno una fonte')
    argomenti = argomenti or ''
    docente = docente or ''
    ora = ora or ''
    from rt.services.lesson_conflicts import lesson_folder, require_no_lesson_conflict, create_lesson_directory
    require_no_lesson_conflict(date, materia, argomenti, dest_dir)
    folder = lesson_folder(date, materia, argomenti)
    lesson_dir = os.path.join(dest_dir, folder)
    # Verifica la principale prima di creare la lezione.
    if not audio and principale and principale not in {os.path.basename(path) for path in materiali} | ({'Appunti', 'appunti.txt'} if appunti.strip() else set()):
        raise ValueError('Fonte principale inesistente')
    # L'unione si fa prima di creare la lezione: se fallisce non resta una lezione a metà che
    # blocca il nuovo tentativo ("Esiste già una lezione"). Il file temporaneo sta in una
    # cartella di sistema: con le lezioni nel database la cartella delle lezioni può non esistere.
    merged_dir = None
    if audio and len(audio) > 1 and unisci:
        import shutil
        import tempfile
        from rt.pipeline.setup import merge_audio_for_transcription
        from rt.pipeline.source_update import _duration
        from rt.core.sources import format_source_duration
        parts = []
        for p in audio:
            dur_s = None
            try:
                dur_s = _duration(p)
            except Exception:
                pass
            parts.append({
                "nome": os.path.basename(p),
                "durata": format_source_duration(dur_s) if dur_s is not None else None,
                "durata_s": dur_s,
            })
        merged_dir = tempfile.mkdtemp(prefix='rt-merge-')
        temp_merged = os.path.join(merged_dir, 'audio completo.m4a')
        try:
            merge_audio_for_transcription(audio, temp_merged)
        except BaseException:
            shutil.rmtree(merged_dir, ignore_errors=True)
            raise
    try:
        lesson_dir = create_lesson_directory(date, materia, argomenti, dest_dir)
    except BaseException:
        if merged_dir:
            shutil.rmtree(merged_dir, ignore_errors=True)
        raise
    info = {'data': date, 'materia': materia, 'argomenti': argomenti, 'docente': docente,
        'ora': ora, 'cartella': folder, 'file_audio': '', 'creato_il': datetime.now(timezone.utc).isoformat(),
        'fase_corrente': 'setup_completato', 'stato': 'pronto_per_rielaborazione',
        'allega_materiali': bool(materiali and allega_materiali)}
    with fs.open(lesson_path(lesson_dir, 'info.yaml'), 'w', encoding='utf-8') as stream:
        yaml.safe_dump(info, stream, allow_unicode=True, sort_keys=False)
    if merged_dir:
        try:
            audio_sources = [add_source(lesson_dir, 'audio', 'audio completo.m4a', None, source_path=temp_merged, parti=parts)]
        finally:
            shutil.rmtree(merged_dir, ignore_errors=True)
    else:
        audio_sources = [add_source(lesson_dir, 'audio', os.path.basename(path), None, source_path=path) for path in audio]
    notes = add_source(lesson_dir, 'appunti', 'appunti.txt', appunti.encode('utf-8')) if appunti.strip() else None
    documents = [add_source(lesson_dir, 'materiale', os.path.basename(path), None, source_path=path, **(opzioni or {}).get(os.path.basename(path), {})) for path in materiali]
    if audio_sources:
        primary = audio_sources[0]
    elif principale in ('Appunti', 'appunti.txt') and notes:
        primary = notes
    elif principale:
        primary = next(s for s in documents if os.path.basename(s.file) == principale)
    elif documents:
        primary = documents[0]
    else:
        primary = notes
    guide = [s for s in documents if (opzioni or {}).get(os.path.basename(s.file), {}).get('uso') == 'guida']
    set_primary(lesson_dir, guide[-1].id if guide else primary.id)
    from rt.db.sync import dual_write_lesson
    dual_write_lesson(lesson_dir)
    return lesson_dir


def link_imported_lesson(lesson_dir, entry_id, calendar_date, calendar_materia=None, calendar_start=None):
    """calendar_entry_id è la key dell'ora restituita da GET /calendar/day."""
    if not entry_id:
        return
    from rt.services.calendar_service import get_day_view, link_lesson
    from rt.services.calendar_models import CalendarLinkLessonRequest
    from rt.services.lesson_service import lesson_id_for_dir
    lesson_id = lesson_id_for_dir(lesson_dir)
    events = get_day_view(calendar_date).events
    if any(e.lesson and e.lesson.id == lesson_id for e in events):
        return
    event = next((e for e in events if e.key == entry_id), None)
    if event is None:
        matches = [e for e in events if calendar_materia and e.materia.casefold() == calendar_materia.casefold()
                   and e.start_time == calendar_start and e.status != 'annullata']
        event = matches[0] if len(matches) == 1 else None
    if event is None or event.status == 'annullata':
        import logging
        logging.getLogger(__name__).warning(
            "Lezione importata, ma l'ora del calendario è cambiata: collegala dal calendario.")
        return
    link_lesson(CalendarLinkLessonRequest(date=calendar_date, entry_key=event.key,
        template_entry_id=event.template_entry_id, override_id=event.override_id,
        lesson_id=lesson_id))


def record_import(lesson_dir):
    """Prima versione della lezione, registrata a fine della prima build (mai al setup):
    la fotografia contiene già scaletta, testo e documenti, quindi ripristinarla non svuota la lezione."""
    from rt.core.update_history import list_versions, record_version
    from rt.core.sources import load_sources
    from rt.pipeline.outline import load_outline
    if list_versions(lesson_dir):
        return
    count = 0
    if fs.isfile(lesson_path(lesson_dir, 'outline.json')):
        count = sum(len(m.units) for m in load_outline(lesson_dir).macro_sections)
    record_version(lesson_dir, 'import', added=[s.id for s in load_sources(lesson_dir)], new=count)


def finish_import(outcome, payload):
    lesson = outcome.lesson_path
    if lesson:
        link_imported_lesson(lesson, payload.get('calendar_entry_id'), payload.get('calendar_date'),
                             payload.get('calendar_materia'), payload.get('calendar_start'))
    return outcome
