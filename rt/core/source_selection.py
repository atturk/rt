"""Ordine e principale confrontati con l'ultimo aggiornamento riuscito."""
from rt.core.sources import load_sources, _save
from rt.pipeline.source_update import _read_state, _write_state
from rt.core.lesson_lock import lesson_locked
from rt.core.lesson_paths import lesson_path
from rt.storage import fs


def selection(lesson_dir):
    sources = load_sources(lesson_dir)
    state = _read_state(lesson_dir)
    ids = [s.id for s in sources]
    primary = state.get('principale')
    if primary not in ids:
        primary = next((s.id for s in sources if s.tipo == 'audio'), ids[0] if ids else '')
    # Se l'audio è principale, la prima parte ne rappresenta l'intero insieme ordinato.
    audio = [s.id for s in sources if s.tipo == 'audio']
    if primary in audio:
        primary = audio[0]
    legacy_used = ['src_000001'] if fs.isfile(lesson_path(lesson_dir, 'segments.json')) else []
    used = state.get('ordine_usato', state.get('used', legacy_used))
    used_primary = state.get('principale_usato', 'src_000001' if 'src_000001' in used else None)
    used_audio = state.get('audio_usato', [sid for sid in used if sid in audio])
    # Le fonti nuove non partecipano al confronto; una rimozione non è un riordino.
    common = set(audio) & set(used_audio)
    reordered = [sid for sid in audio if sid in common] != [sid for sid in used_audio if sid in common]
    # Riordinare l'audio cambia anche l'id che rappresenta la stessa principale audio.
    primary_changed = used_primary is not None and primary != used_primary
    if primary in audio and used_primary in used_audio:
        primary_changed = False
    if (primary in audio and not state.get("primary_explicit")
            and not any(s.tipo == "materiale" for s in sources)):
        # Compatibilità b1: dagli appunti impliciti all’audio sopraggiunto.
        primary_changed = False
    return {'principale': primary, 'ordine_usato': used, 'principale_usato': used_primary,
            'solo_ricostruzione': reordered or primary_changed}


@lesson_locked
def set_order(lesson_dir, ids):
    sources = load_sources(lesson_dir)
    if len(ids) != len(set(ids)) or set(ids) != {s.id for s in sources}:
        raise ValueError('Indica tutte le fonti, una volta sola.')
    mapping = {s.id: s for s in sources}
    ordered = [mapping[sid].model_copy(update={'ordine': i}) for i, sid in enumerate(ids, 1)]
    _save(lesson_dir, ordered)


@lesson_locked
def set_primary(lesson_dir, sid):
    if sid not in {s.id for s in load_sources(lesson_dir)}:
        raise ValueError('Fonte principale inesistente.')
    state = _read_state(lesson_dir)
    state['principale'] = sid
    state['primary_explicit'] = True
    _write_state(lesson_dir, state)


def record_used_selection(lesson_dir):
    current = selection(lesson_dir)
    sources = load_sources(lesson_dir)
    state = _read_state(lesson_dir)
    state.update(principale=current['principale'], principale_usato=current['principale'],
                 ordine_usato=[s.id for s in sources], audio_usato=[s.id for s in sources if s.tipo == 'audio'])
    _write_state(lesson_dir, state)
