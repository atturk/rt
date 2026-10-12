from rt.core.sources import add_source, load_sources
from rt.core.source_selection import selection, set_order, set_primary, record_used_selection
from tests.test_source_update import legacy, write_audio


def test_move_and_put_back_recomputes_rebuild_and_new_audio_is_ignored(tmp_path):
    legacy(tmp_path)
    lesson = str(tmp_path)
    second = add_source(lesson, 'audio', 'two.wav', (tmp_path / 'original.wav').read_bytes())
    original = load_sources(lesson)[0]
    record_used_selection(lesson)
    set_order(lesson, [second.id, original.id])
    assert selection(lesson)['solo_ricostruzione']
    set_order(lesson, [original.id, second.id])
    assert not selection(lesson)['solo_ricostruzione']
    third = add_source(lesson, 'audio', 'three.wav', (tmp_path / 'original.wav').read_bytes(), ordine=1)
    assert not selection(lesson)['solo_ricostruzione']
    note = add_source(lesson, 'appunti', 'note.txt', b'notes')
    set_primary(lesson, note.id)
    assert selection(lesson)['solo_ricostruzione']
    set_primary(lesson, original.id)
    assert not selection(lesson)['solo_ricostruzione']


def test_audio_does_not_replace_existing_notes_primary(tmp_path):
    (tmp_path / 'info.yaml').write_text('materia: Test\n')
    lesson = str(tmp_path)
    note = add_source(lesson, 'appunti', 'note.txt', b'notes')
    write_audio(tmp_path / 'incoming.wav')
    add_source(lesson, 'audio', 'audio.wav', (tmp_path / 'incoming.wav').read_bytes())
    assert selection(lesson)['principale'] == note.id


def test_order_and_primary_api_contract_and_busy(api_client, rt_db, tmp_path, monkeypatch):
    from tests.api_support import isolated_workspace, make_lesson, add_audio, run_mock_pipeline
    from tests.test_api_sources import lesson_id
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson = make_lesson(root)
    add_audio(lesson)
    run_mock_pipeline(lesson, with_review=False)
    lid = lesson_id(api_client)
    url = f'/api/v1/lessons/{lid}'
    first = load_sources(lesson)[0]
    note = add_source(lesson, 'appunti', 'note.txt', b'new')
    view = api_client.put(url + '/sources/primary', json={'id': note.id}).json()
    assert view['solo_ricostruzione']
    response = api_client.post(url + '/update', json={'mode': 'extend', 'mock': True})
    assert response.status_code == 409 and response.json()['error']['code'] == 'rebuild_required'
    view = api_client.put(url + '/sources/primary', json={'id': first.id}).json()
    assert not view['solo_ricostruzione']
    assert api_client.put(url + '/sources/order', json={'ids': [first.id]}).status_code == 422
    assert api_client.put(url + '/sources/order', json={'ids': [note.id, first.id]}).status_code == 200
    assert api_client.post(url + '/update', json={'mock': True}).status_code == 202
    response = api_client.put(url + '/sources/primary', json={'id': note.id})
    assert response.status_code == 409 and response.json()['error']['code'] == 'lesson_busy'


def test_notes_primary_drives_outline_when_audio_arrives(tmp_path):
    from rt.pipeline.source_update import prepare_source_update
    (tmp_path / 'info.yaml').write_text('materia: Test\n')
    lesson = str(tmp_path)
    note = add_source(lesson, 'appunti', 'note.txt', b'notes main')
    write_audio(tmp_path / 'incoming.wav')
    add_source(lesson, 'audio', 'audio.wav', (tmp_path / 'incoming.wav').read_bytes())
    result = prepare_source_update(lesson, mock=True)
    assert [s.text_raw for s in result['segments']] == ['notes main']
    assert result['segments'][0].source_file == note.id
