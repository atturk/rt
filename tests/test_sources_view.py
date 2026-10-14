from rt.core.sources import add_source
from rt.pipeline.source_update import run_source_update
from rt.services.sources_view import sources_view
from rt.core.update_history import undo_update
from tests.test_source_update import legacy


def test_source_measures_and_persistent_update_summary(tmp_path, monkeypatch):
    legacy(tmp_path)
    lesson = str(tmp_path)
    monkeypatch.setattr('rt.services.classifier.classify_units', lambda *a, **k: None)
    note = add_source(lesson, 'appunti', 'note.txt', b'one two three')
    view = sources_view(lesson)
    assert view['ultimo_aggiornamento'] is None
    audio, notes = view['sources']
    assert audio.nome == 'original.wav' and audio.durata_s == 2 and audio.usata
    assert notes.nome == 'Appunti' and notes.parole == 3 and not notes.usata
    run_source_update(lesson, mode='rebuild', mock=True)
    summary = sources_view(lesson)['ultimo_aggiornamento']
    assert summary['modo'] == 'rebuild' and summary['unita_nuove'] >= 1
    assert all(s.usata for s in sources_view(lesson)['sources'])
    add_source(lesson, 'appunti', 'new.txt', b'new')
    assert sources_view(lesson)['ultimo_aggiornamento'] == summary
    undo_update(lesson)
    assert sources_view(lesson)['ultimo_aggiornamento'] is None
