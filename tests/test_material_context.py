from rt.core.sources import add_source
from rt.pipeline.rewrite import context_for_usage, _run_rewrite
from rt.llm.client import LLMClient
from tests.test_checkpointing import multi_unit_lesson
from tests.test_materials import pdf_bytes


def test_materials_enter_variable_prompt_not_prefix_and_are_cached(multi_unit_lesson, monkeypatch):
    lesson = multi_unit_lesson
    add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('MATERIAL CONTEXT\nUna descrizione completa illustra processi cellulari, strutture biologiche, meccanismi molecolari, funzioni fisiologiche e possibili alterazioni patologiche.'))
    captured = []
    original = LLMClient.call_structured
    def call(self, **kwargs):
        captured.append(kwargs)
        return original(self, **kwargs)
    monkeypatch.setattr(LLMClient, 'call_structured', call)
    _run_rewrite(lesson, force=True, force_mock=True)
    rewrites = [r for r in captured if r['job_name'] == 'rewrite']
    # MF1d: il testo dei materiali va nella parte variabile del prompt, mai nel prefisso in cache
    assert rewrites and all('MATERIAL CONTEXT' not in r['prompt_prefix'] for r in rewrites)
    assert any('PAGINE DEI MATERIALI ASSEGNATE A QUESTA UNITÀ:' in r['prompt'] and 'MATERIAL CONTEXT' in r['prompt'] for r in rewrites)
    assert all('image_data_url' not in r for r in rewrites)
    monkeypatch.setattr('rt.core.materials._extract', lambda _: (_ for _ in ()).throw(AssertionError('cached')))
    _run_rewrite(lesson, force=True, force_mock=True)


def test_trim_previous_before_materials_without_token_estimates():
    usage = {'prompt_tokens': 90, 'completion_tokens': 20}
    units, materials = context_for_usage(['old', 'new'], ['page1', 'page2'], 100, usage)
    assert units == ['new'] and materials == ['page1', 'page2']
    units, materials = context_for_usage([], materials, 100, usage)
    assert units == [] and materials == ['page2']
    assert context_for_usage([], materials, None, usage) == ([], materials)
    assert context_for_usage([], materials, 100, None) == ([], materials)


def test_materials_capped_before_first_call():
    from rt.pipeline.rewrite import cap_material_parts, MATERIALS_CHAR_CAP
    pages = ['x' * 25_000 for _ in range(5)]
    assert len(cap_material_parts(pages)) == MATERIALS_CHAR_CAP // 25_002
    assert cap_material_parts(pages, 30_000) == pages[:1]
    assert cap_material_parts(['a', 'b']) == ['a', 'b']


def test_notes_in_segments_not_repeated_as_context(tmp_path):
    from rt.core.materials import material_context_parts
    from rt.pipeline.source_update import _read_state, _write_state, segment_source_ids
    from rt.core.sources import load_sources
    (tmp_path / 'info.yaml').write_text('materia: Test\ndata: 2026-10-12\nfile_audio: ""\n')
    lesson = str(tmp_path)
    audio = add_source(lesson, 'audio', 'a.m4a', b'audio')
    notes = [add_source(lesson, 'appunti', f'n{i}.txt', f'NOTE {i}'.encode()) for i in range(2)]
    doc = add_source(lesson, 'materiale', 'doc.pdf', pdf_bytes('DOC TEXT'))
    state = _read_state(lesson)
    for source in notes:
        state['sources'][source.id] = {'segments': [{'text_raw': f'text {source.id}'}], 'duration': 0}
    _write_state(lesson, state)
    # Audio principale: audio e appunti nei segmenti come nella b1, solo il materiale escluso.
    assert segment_source_ids(load_sources(lesson), state, audio.id) == {audio.id, *(n.id for n in notes)}
    parts = material_context_parts(lesson, mock=True)
    assert len(parts) == 1 and 'DOC TEXT' in parts[0]
    # Principale scelta e non audio: solo lei nei segmenti, il resto è contesto una volta sola.
    state.update(principale=doc.id, primary_explicit=True)
    _write_state(lesson, state)
    assert segment_source_ids(load_sources(lesson), state, doc.id) == {doc.id}
    parts = material_context_parts(lesson, mock=True)
    assert all('DOC TEXT' not in p for p in parts)
    assert sum(f'text {notes[0].id}' in p for p in parts) == 1
