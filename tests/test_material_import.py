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
def test_import_only_materials_defaults_first_and_records_import(api_client, rt_db, tmp_path, monkeypatch, run):
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
    assert view['principale'] == sources[0].id and view['principale_usato'] == sources[0].id
    assert [s['pagine_totali'] for s in view['sources']] == [1, 2]
    assert all(s.source_file == sources[0].id for s in load_segments_json(lesson_path(lesson, 'segments.json')).segments)
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
        'mock': 'true', 'unisci': 'false', 'calendar_entry_id': event.key, 'calendar_date': '2026-10-12'}, files=[
        ('audio', ('z-first.wav', wav_bytes(), 'audio/wav')),
        ('audio', ('a-second.wav', wav_bytes(), 'audio/wav')),
        ('materiali', ('doc.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 202, response.text
    lesson = work(rt_db)
    sources = load_sources(lesson)
    assert [os.path.basename(s.file) for s in sources if s.tipo == 'audio'] == ['z-first.m4a', 'a-second.m4a']
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


def test_import_multiple_audio_merged_with_parts(api_client, rt_db, tmp_path, monkeypatch):
    isolated_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr("rt.pipeline.source_update._duration", lambda path: 120.0 if "part1" in path else 60.0)
    monkeypatch.setattr("rt.pipeline.setup.merge_audio_for_transcription",
                        lambda audios, out: open(out, "wb").write(b"fake-merged"))
    response = api_client.post('/api/v1/lessons', data={
        'date': '2026-10-12', 'materia': 'Biologia', 'mock': 'true', 'unisci': 'true'
    }, files=[
        ('audio', ('part1.wav', wav_bytes(), 'audio/wav')),
        ('audio', ('part2.wav', wav_bytes(), 'audio/wav')),
    ])
    assert response.status_code == 202, response.text
    lesson = work(rt_db)
    sources = load_sources(lesson)
    audio_sources = [s for s in sources if s.tipo == 'audio']
    assert len(audio_sources) == 1
    merged = audio_sources[0]
    assert merged.file.endswith('audio completo.m4a')
    assert merged.parti is not None
    assert len(merged.parti) == 2
    assert merged.parti[0].nome == 'part1.wav'
    assert merged.parti[0].durata == '2 min'
    assert merged.parti[1].nome == 'part2.wav'
    assert merged.parti[1].durata == '1 min'
    # Verify GET /sources returns parti
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    view = api_client.get(f'/api/v1/lessons/{lid}/sources').json()
    assert view['principale'] == merged.id
    view_audio = [s for s in view['sources'] if s['tipo'] == 'audio'][0]
    assert len(view_audio['parti']) == 2



def test_merged_audio_with_materials_keeps_the_player(api_client, rt_db, tmp_path, monkeypatch):
    # L'audio unito sta in sources/<id>/: il player (has_audio e /audio) deve trovarlo anche
    # quando il manifest non lo riporta.
    isolated_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr("rt.pipeline.source_update._duration", lambda path: 60.0)
    response = api_client.post('/api/v1/lessons', data={
        'date': '2026-10-12', 'materia': 'Biologia', 'mock': 'true', 'unisci': 'true', 'run': 'true',
        'auto_accept': 'true', 'with_enrichment': 'false'
    }, files=[('audio', ('part1.wav', wav_bytes(), 'audio/wav')), ('audio', ('part2.wav', wav_bytes(), 'audio/wav')),
              ('materiali', ('d.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 202, response.text
    work(rt_db)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    assert api_client.get(f'/api/v1/lessons/{lid}').json()['has_audio'] is True
    assert api_client.get(f'/api/v1/lessons/{lid}/audio').status_code == 200


def test_followed_hour_without_lesson_is_importable(api_client, rt_db, tmp_path, monkeypatch):
    from rt.services import calendar_service as calendar
    from rt.services import calendar_models as schemas
    isolated_workspace(tmp_path, monkeypatch)
    tpl = calendar.create_template_entry(schemas.CalendarTemplateEntryCreate(valid_from='2026-10-01',
        day_of_week=0, start_time='09:00', end_time='10:00', materia='Prova'))
    key = f'tpl_{tpl.id}'
    calendar.set_entry_state(schemas.CalendarEntryStateSet(date='2026-10-12', entry_key=key, status='seguita'))
    response = api_client.post('/api/v1/lessons', data={'date': '2026-10-12', 'materia': 'Prova', 'mock': 'true',
        'calendar_entry_id': key, 'calendar_date': '2026-10-12'}, files=[('materiali', ('doc.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 202, response.text
    work(rt_db)
    event = calendar.get_day_view('2026-10-12').events[0]
    assert event.lesson is not None and event.is_recorded and event.status == 'seguita'


def test_export_only_sources_single_and_group(api_client, rt_db, tmp_path, monkeypatch):
    import zipfile as zf_mod
    isolated_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr("rt.pipeline.source_update._duration", lambda path: 60.0)
    response = api_client.post('/api/v1/lessons', data={
        'date': '2026-10-12', 'materia': 'Biologia', 'mock': 'true', 'unisci': 'true'
    }, files=[('audio', ('part1.wav', wav_bytes(), 'audio/wav')), ('audio', ('part2.wav', wav_bytes(), 'audio/wav')),
              ('materiali', ('slide.pdf', pdf_bytes(), 'application/pdf'))])
    assert response.status_code == 202, response.text
    work(rt_db)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    single = api_client.get(f'/api/v1/lessons/{lid}/export?format=zip&scope=sources')
    assert single.status_code == 200, single.text
    assert 'fonti.zip' in single.headers['content-disposition']
    with zf_mod.ZipFile(io.BytesIO(single.content)) as archive:
        names = sorted(n.split('/', 1)[1] for n in archive.namelist())
    # Un solo audio (quello unito della lezione) e il PDF col suo nome; niente documento o stato.
    assert names == ['audio completo.m4a', 'slide.pdf']
    accepted = api_client.post('/api/v1/lesson-exports', json={'ids': [lid], 'format': 'sources', 'name': 'oggi'}).json()
    assert Worker(DbJobQueue(rt_db)).run_once() is not None
    group = api_client.get(f"/api/v1/lesson-exports/{accepted['job_id']}/file")
    assert group.status_code == 200
    with zf_mod.ZipFile(io.BytesIO(group.content)) as archive:
        assert sorted(n.split('/', 1)[1] for n in archive.namelist()) == ['audio completo.m4a', 'slide.pdf']
