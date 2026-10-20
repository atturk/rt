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
    set_primary(lesson, note.id)
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
    set_primary(lesson, note.id)
    write_audio(tmp_path / 'incoming.wav')
    add_source(lesson, 'audio', 'audio.wav', (tmp_path / 'incoming.wav').read_bytes())
    result = prepare_source_update(lesson, mock=True)
    assert [s.text_raw for s in result['segments']] == ['notes main']
    assert result['segments'][0].source_file == note.id


def test_removed_used_sources_are_not_new_and_can_be_put_back(tmp_path):
    from rt.core.sources import remove_source
    from rt.core.source_selection import restore_removed_used
    from rt.pipeline.source_update import sources_pending, _read_state, _write_state
    from rt.core.update_history import record_version, restore_version
    legacy(tmp_path)
    lesson = str(tmp_path)
    note = add_source(lesson, 'appunti', 'note.txt', b'appunti usati')
    record_used_selection(lesson)
    state = _read_state(lesson)
    state['used'] = state['ordine_usato']
    _write_state(lesson, state)
    version = record_version(lesson, 'import')
    remove_source(lesson, note.id)
    assert not sources_pending(lesson)
    assert selection(lesson)['fonti_tolte_usate'] == [note.id]
    assert selection(lesson)['solo_ricostruzione']
    assert (tmp_path / note.file).read_bytes() == b'appunti usati'
    # Aggiunta e riordino non devono perdere la fonte tolta nel registro.
    fresh = add_source(lesson, 'appunti', 'fresh.txt', b'nuovi')
    set_order(lesson, [s.id for s in load_sources(lesson)])
    assert next(s for s in load_sources(lesson, include_removed=True) if s.id == note.id).rimossa_il
    remove_source(lesson, fresh.id)
    assert not sources_pending(lesson)
    restore_removed_used(lesson)
    assert [s.id for s in load_sources(lesson)] == state['used']
    assert not selection(lesson)['solo_ricostruzione']
    assert next(s for s in load_sources(lesson, include_removed=True) if s.id == fresh.id).rimossa_il
    remove_source(lesson, note.id)
    record_version(lesson, 'rebuild')
    restore_version(lesson, version)
    assert note.id in [s.id for s in load_sources(lesson)]
    assert not selection(lesson)['solo_ricostruzione']


def test_removing_unused_source_never_requires_update(tmp_path):
    from rt.core.sources import remove_source
    from rt.pipeline.source_update import sources_pending
    legacy(tmp_path)
    lesson = str(tmp_path)
    note = add_source(lesson, 'appunti', 'new.txt', b'appunti nuovi')
    remove_source(lesson, note.id)
    assert not sources_pending(lesson)
    assert selection(lesson)['fonti_tolte_usate'] == []
    assert not selection(lesson)['solo_ricostruzione']


def test_legacy_used_integra_requires_rebuild_without_saved_uses(tmp_path):
    from rt.pipeline.source_update import _read_state, _write_state
    from rt.core.sources import update_source
    legacy(tmp_path)
    lesson = str(tmp_path)
    source = add_source(lesson, 'appunti', 'old.txt', b'Fonte usata come contesto', uso='integra')
    state = _read_state(lesson)
    state['used'] = [s.id for s in load_sources(lesson)]
    _write_state(lesson, state)
    assert selection(lesson)['solo_ricostruzione']
    update_source(lesson, source.id, uso='contesto')
    assert not selection(lesson)['solo_ricostruzione']


def test_prepare_records_uses_without_materials(tmp_path):
    from rt.pipeline.source_update import prepare_source_update, _read_state
    from rt.core.sources import update_source
    legacy(tmp_path)
    lesson = str(tmp_path)
    source = add_source(lesson, 'appunti', 'extra.txt', b'Argomento aggiuntivo', uso='integra')
    prepare_source_update(lesson)
    assert _read_state(lesson)['usi_usati'] == {'src_000001': None, source.id: 'integra'}
    update_source(lesson, source.id, uso='contesto')
    assert selection(lesson)['solo_ricostruzione']


def test_change_to_integra_preserves_legacy_used_selection(tmp_path):
    from rt.core.sources import update_source
    from rt.pipeline.source_update import _read_state, _write_state
    legacy(tmp_path)
    lesson = str(tmp_path)
    source = add_source(lesson, 'appunti', 'old.txt', b'Appunti gia usati')
    state = _read_state(lesson)
    state['used'] = [s.id for s in load_sources(lesson)]
    _write_state(lesson, state)
    assert 'ordine_usato' not in state and 'usi_usati' not in state
    update_source(lesson, source.id, uso='integra')
    assert selection(lesson)['solo_ricostruzione']
    update_source(lesson, source.id, uso='contesto')
    assert not selection(lesson)['solo_ricostruzione']
