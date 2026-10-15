"""Arricchimento: stesso mapping dei materiali, senza riscrivere o perdere immagini."""
import json
import os
from pathlib import Path

import fitz
import pytest

from rt.core.idempotency import compute_file_sha256, compute_source_fingerprint, record_phase_fingerprint
from rt.core.lesson_paths import lesson_path
from rt.core.models import Draft, DraftUnit, Outline, OutlineMacro, OutlineUnit, Segment, SegmentsData
from rt.core.update_history import record_version, restore_version
from rt.llm.client import LLMClient
from rt.llm.prompts import ImageDescription
from rt.pipeline.add_images import (compute_image_hash, load_image_descriptions, run_add_images,
                                    save_image_descriptions, save_raw_image, _mock_png)
from rt.pipeline.image_placement import load_image_placement, save_image_placement, images_for_document
from rt.pipeline.outline import save_outline, load_outline
from rt.pipeline.rewrite import save_draft
from tests.test_add_images import _synthetic_lesson


@pytest.fixture
def lesson(tmp_path):
    root = _synthetic_lesson(tmp_path, build=False)
    topics = [('Mitocondri', 'Mitocondri membrana respirazione cellulare ATP energia'),
              ('Cloroplasti', 'Cloroplasti fotosintesi clorofilla vegetale luce')]
    units, segments, drafts = [], [], []
    for i, (title, text) in enumerate(topics, 1):
        sid, uid = f'seg_{i:06d}', f'1.{i}'
        units.append(OutlineUnit(id=uid, title=title, start_segment_id=sid, end_segment_id=sid))
        segments.append(Segment(id=sid, index=i, start_seconds=i, end_seconds=i+1,
                                start_formatted=f'00:{i:02d}', end_formatted=f'00:{i+1:02d}', text_raw=text))
        drafts.append(DraftUnit(unit_id=uid, title=title, start_segment_id=sid, end_segment_id=sid,
                                source_segment_ids=[sid], content=text))
    save_outline(Outline(lesson_title='Cellule', macro_sections=[OutlineMacro(id='1', title='Organelli', units=units)]), root)
    Path(lesson_path(root, 'segments.json')).write_text(SegmentsData(segments=segments).model_dump_json())
    save_draft(Draft(units=drafts), root)
    for phase in ['prepare', 'outline', 'rewrite']:
        record_phase_fingerprint(root, phase, compute_source_fingerprint(root, phase), {})
    return root


def pdf(path, texts):
    with fitz.open() as document:
        for text in texts:
            page = document.new_page(width=500, height=240)
            if text:
                page.insert_text((30, 60), text)
        document.save(path)
    return str(path)


def test_pdf_text_mapping_preserves_every_placement_context_and_history(lesson, tmp_path, monkeypatch):
    from rt.pipeline import material_mapping as mapping
    existing = {}
    for name, source in [('material', 'material:src_old:1'), ('manual', 'manual:old'),
                         ('web', 'websearch:old'), ('previous', 'pdf:previous.pdf#1')]:
        data = name.encode()
        h = compute_image_hash(data)
        existing[h] = {'filename': save_raw_image(lesson, data, h), 'source': source, 'alt_text': name}
    save_image_descriptions(lesson, existing)
    hashes = list(existing)
    save_image_placement(lesson, {'1': hashes[:3]}, False, units={'1.2': [hashes[3]]})
    context = Path(lesson_path(lesson, mapping.STATE_FILE))
    context.write_text(json.dumps({'pages_by_unit': {'1.1': [{'text': 'Non cambiare'}]}, 'pages_by_macro': {}}))
    untouched = {name: Path(lesson_path(lesson, name)).read_bytes()
                 for name in ['draft.json', 'segments.json', mapping.STATE_FILE]}
    version = record_version(lesson, 'import')
    history = Path(lesson) / 'history' / version
    old_snapshot = {p: p.read_bytes() for p in history.rglob('*') if p.is_file()}
    path = pdf(tmp_path / 'organelli.pdf', [
        'Mitocondri membrana respirazione cellulare ATP energia',
        'Cloroplasti fotosintesi clorofilla vegetale luce',
        'Astronomia orbite galassie pianeti',
    ])
    def no_vision(*args, **kwargs):
        pytest.fail('Un PDF con testo non deve chiamare Vision')
    monkeypatch.setattr(LLMClient, 'call_structured', no_vision)
    real = mapping.classify_material_page
    calls = []
    def classify(page, candidates, source, *args, **kwargs):
        calls.append((page['numero'], [c.unit_id for c in candidates], source.id))
        return real(page, candidates, source, *args, **kwargs)
    monkeypatch.setattr(mapping, 'classify_material_page', classify)
    result = run_add_images(lesson, input_path=path, force_mock=True)
    assert result['images_added'] == 2
    assert calls == [(1, ['1.1'], compute_file_sha256(path)), (2, ['1.2'], compute_file_sha256(path)),
                     (3, [], compute_file_sha256(path))]
    descriptions = load_image_descriptions(lesson)
    by_page = {d['source']: h for h, d in descriptions.items() if d['source'].startswith('pdf:organelli')}
    placement = load_image_placement(lesson)
    assert placement['macros'] == {'1': hashes[:3]}
    assert placement['units']['1.1'] == [by_page['pdf:organelli.pdf#1']]
    assert placement['units']['1.2'] == [hashes[3], by_page['pdf:organelli.pdf#2']]
    assert by_page['pdf:organelli.pdf#3'] not in {h for hs in placement['units'].values() for h in hs}
    for source, h in by_page.items():
        assert descriptions[h]['alt_text'] == f"organelli.pdf, pagina {source.rsplit('#', 1)[1]}"
    cache = Path(lesson_path(lesson, mapping.CACHE_FILE)).read_bytes()
    run_add_images(lesson, input_path=path, force_mock=True)
    assert load_image_placement(lesson) == placement
    assert Path(lesson_path(lesson, mapping.CACHE_FILE)).read_bytes() == cache
    for name, content in untouched.items():
        assert Path(lesson_path(lesson, name)).read_bytes() == content
    assert all(path.read_bytes() == content for path, content in old_snapshot.items())
    restore_version(lesson, version)
    assert load_image_descriptions(lesson) == existing
    assert load_image_placement(lesson)['units'] == {'1.2': [hashes[3]]}
    for image in images_for_document(lesson, load_outline(lesson)).by_macro['1']:
        assert Path(lesson, image['filename']).is_file()


def test_blank_pdf_and_single_photo_use_vision_and_keep_unassigned_media(lesson, tmp_path, monkeypatch):
    calls = []
    def describe(self, *args, **kwargs):
        calls.append(kwargs['job_name'])
        return ImageDescription(slide_title='Mitocondri', ocr_text='Mitocondri membrana respirazione ATP', alt_text='Vision')
    monkeypatch.setattr(LLMClient, 'call_structured', describe)
    blank = pdf(tmp_path / 'senza-testo.pdf', [''])
    run_add_images(lesson, input_path=blank, force_mock=True)
    photo = tmp_path / 'foto.png'
    photo.write_bytes(_mock_png('photo'))
    run_add_images(lesson, input_path=str(photo), force_mock=True)
    assert calls == ['image_description', 'image_description']
    descriptions = load_image_descriptions(lesson)
    assert {d['alt_text'] for d in descriptions.values()} == {'senza-testo.pdf, pagina 1', 'foto.png, pagina 1'}
    assert len(load_image_placement(lesson)['units']['1.1']) == 2
    run_add_images(lesson, input_path=str(photo), force_mock=True)
    assert len(calls) == 2


def test_multiple_pdfs_and_photos_are_all_read(lesson, tmp_path, monkeypatch):
    batch = tmp_path / 'batch'
    batch.mkdir()
    pdf(batch / 'a.pdf', ['Mitocondri respirazione ATP'])
    pdf(batch / 'b.pdf', ['Cloroplasti fotosintesi clorofilla'])
    (batch / 'foto.png').write_bytes(_mock_png('batch-photo'))
    monkeypatch.setattr(LLMClient, 'call_structured', lambda *a, **k: ImageDescription(
        slide_title='Estranea', ocr_text='Astronomia orbite galassie', alt_text='Estranea'))
    run_add_images(lesson, input_path=str(batch), force_mock=True)
    descriptions = load_image_descriptions(lesson)
    assert {d['source'] for d in descriptions.values()} == {'pdf:a.pdf#1', 'pdf:b.pdf#1', 'folder:foto.png'}
    placed = {h for hashes in load_image_placement(lesson)['units'].values() for h in hashes}
    assert len(placed) == 2 and len(descriptions) == 3


def test_rejected_page_remains_in_media_without_placement(lesson, tmp_path, monkeypatch):
    calls = []
    def reject(page, candidates, *args, **kwargs):
        calls.append([c.unit_id for c in candidates])
        return [], []
    monkeypatch.setattr('rt.pipeline.material_mapping.classify_material_page', reject)
    path = pdf(tmp_path / 'rifiutata.pdf', ['Mitocondri respirazione membrana ATP'])
    result = run_add_images(lesson, input_path=path, force_mock=True)
    assert calls == [['1.1']]
    assert result['images_added'] == 0
    assert len(load_image_descriptions(lesson)) == 1
    assert load_image_placement(lesson)['units'] == {}
    assert load_image_placement(lesson)['macros'] == {}


def test_web_provenance_places_each_unit_without_macro_judge(lesson, monkeypatch):
    def no_judge(*args, **kwargs):
        pytest.fail('Le immagini trovate per una sottounità non passano dal giudice macro')
    monkeypatch.setattr('rt.pipeline.add_images.judge_images_by_macro', no_judge)
    result = run_add_images(lesson, web_search_count=2, force_mock=True)
    placement = load_image_placement(lesson)
    assert placement['macros'] == {}
    assert {uid: len(hashes) for uid, hashes in placement['units'].items()} == {'1.1': 2, '1.2': 2}
    descriptions = load_image_descriptions(lesson)
    for uid, hashes in placement['units'].items():
        assert all(descriptions[h]['origin_unit_ids'] == [uid] for h in hashes)
    assert result['images_added'] == 4
    run_add_images(lesson, web_search_count=2, force_mock=True)
    assert load_image_placement(lesson) == placement


def test_web_without_origin_keeps_macro_judge_and_existing_placements(lesson, monkeypatch):
    from rt.core.image_extract import ExtractedImage
    from rt.pipeline import add_images
    known, unknown = _mock_png('known'), _mock_png('unknown')
    monkeypatch.setattr(add_images, 'fetch_web_images', lambda **kwargs: ([
        ExtractedImage(known, 'websearch:known', unit_id='1.2'),
        ExtractedImage(unknown, 'websearch:unknown'),
    ], {'1.2': 1}))
    real_judge = add_images.judge_images_by_macro
    calls = []
    def judge(*args, **kwargs):
        calls.append(kwargs['image_hashes'])
        return real_judge(*args, **kwargs)
    monkeypatch.setattr(add_images, 'judge_images_by_macro', judge)
    run_add_images(lesson, web_search_count=1, force_mock=True)
    assert calls == [[compute_image_hash(unknown)]]
    placement = load_image_placement(lesson)
    assert placement['units'] == {'1.2': [compute_image_hash(known)]}
    assert placement['macros'] == {'1': [compute_image_hash(unknown)]}
