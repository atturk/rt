import io
import os
import wave

import fitz
import pytest

from rt.core.sources import load_sources
from rt.core.lesson_paths import lesson_path
from rt.core.state import read_info_yaml
from rt.core.update_history import list_versions
from rt.core.segments import load_segments_json
from rt.services.jobs import DbJobQueue, job_needs_stt
from rt.services.worker import Worker
from rt.pipeline.outline import load_outline
from rt.pipeline.image_placement import images_for_document
from rt.storage import fs
from tests.api_support import isolated_workspace
from tests.test_materials import pdf_bytes


def long_pdf():
    document = fitz.open()
    for i in range(2):
        document.new_page().insert_text((50, 50), f'Long document page {i + 1}')
    data = document.tobytes()
    document.close()
    return data


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 32000)
    return stream.getvalue()


def work(rt_db):
    job = Worker(DbJobQueue(rt_db), job_types=['ingest_sources'], mock=True, on_message=lambda *_: None).run_once()
    assert job is not None and job.state == 'succeeded', job.error if job else 'no job'
    return job.lesson_path


@pytest.mark.parametrize('run', [False, True])
def test_import_only_materials_defaults_longest_and_records_import(api_client, rt_db, tmp_path, monkeypatch, run):
    isolated_workspace(tmp_path, monkeypatch)
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Biologia',
        'run': str(run).lower(), 'mock': 'true', 'auto_accept': 'true', 'with_enrichment': 'false'}, files=[
        ('materiali', ('small.pdf', pdf_bytes('SMALL'), 'application/pdf')),
        ('materiali', ('large.pdf', long_pdf(), 'application/pdf'))])
    assert response.status_code == 202, response.text
    assert response.json()['type'] == 'ingest_sources'
    lesson = work(rt_db)
    sources = load_sources(lesson)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    view = api_client.get(f'/api/v1/lessons/{lid}/sources').json()
    assert view['principale'] == sources[1].id and view['principale_usato'] == sources[1].id
    assert [s['pagine'] for s in view['sources']] == [1, 2]
    assert all(s.source_file == sources[1].id for s in load_segments_json(lesson_path(lesson, 'segments.json')).segments)
    # La versione "import" nasce a fine della prima build, mai al setup.
    if run:
        version = list_versions(lesson)[0]
        assert version['modo'] == 'import'
        snapshot = os.path.join(lesson, 'history', version['id'])
        assert all(fs.isfile(os.path.join(snapshot, name)) for name in ('outline.json', 'draft.json', 'rielaborato.md'))
    else:
        assert list_versions(lesson) == []
    assert read_info_yaml(lesson_path(lesson, 'info.yaml'))['allega_materiali'] == 'true'
    if run:
        assert images_for_document(lesson, load_outline(lesson))[0]


def test_explicit_primary_and_clip_off(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Biologia',
        'principale': 'small.pdf', 'allega_materiali': 'false', 'run': 'true', 'mock': 'true',
        'auto_accept': 'true', 'with_enrichment': 'false'}, files=[
        ('materiali', ('small.pdf', pdf_bytes('SMALL'), 'application/pdf')),
        ('materiali', ('large.pdf', long_pdf(), 'application/pdf'))])
    assert response.status_code == 202
    lesson = work(rt_db)
    assert all(s.source_file == load_sources(lesson)[0].id for s in load_segments_json(lesson_path(lesson, 'segments.json')).segments)
    assert images_for_document(lesson, load_outline(lesson))[0] == {}


def test_mixed_audio_order_and_calendar_manual_link(api_client, rt_db, tmp_path, monkeypatch):
    from rt.services.calendar_service import create_template_entry, get_day_view
    from rt.services.calendar_models import CalendarTemplateEntryCreate
    isolated_workspace(tmp_path, monkeypatch)
    entry = create_template_entry(CalendarTemplateEntryCreate(day_of_week=0, start_time='09:00', end_time='10:00', materia='Biologia'))
    event = get_day_view('2026-10-12').events[0]
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Biologia',
        'mock': 'true', 'calendar_entry_id': event.key, 'calendar_date': '2026-10-12'}, files=[
        ('audio', ('z-first.wav', wav_bytes(), 'audio/wav')),
        ('audio', ('a-second.wav', wav_bytes(), 'audio/wav')),
        ('materiali', ('doc.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 202, response.text
    lesson = work(rt_db)
    sources = load_sources(lesson)
    assert [os.path.basename(s.file) for s in sources if s.tipo == 'audio'] == ['z-first.wav', 'a-second.wav']
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    assert get_day_view('2026-10-12').events[0].lesson.id == lid
    from rt.db.models import CalendarEntryState
    from rt.db.session import read_scope
    from sqlalchemy import select
    with read_scope(rt_db) as session:
        state = session.scalar(select(CalendarEntryState))
        assert state.manual_link and state.lesson_id == lid
    assert job_needs_stt('ingest_sources', {'audio': ['a.wav'], 'options': {'mock': False}})
    assert not job_needs_stt('ingest_sources', {'audio': [], 'options': {'mock': False}})
    assert not job_needs_stt('ingest_sources', {'audio': ['a.wav'], 'options': {'mock': True}})


def test_invalid_primary_and_calendar_rejected_before_creation(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Biologia',
        'principale': 'missing.pdf'}, files=[('materiali', ('doc.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 422
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Biologia',
        'appunti': 'notes', 'calendar_entry_id': 'missing'})
    assert response.status_code == 422
    assert api_client.get('/api/v1/lessons').json() == []
