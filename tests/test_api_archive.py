import io
from pathlib import Path
from unittest.mock import Mock

import fitz
import pytest
from PIL import Image

from rt.core import archive
from rt.core.sources import add_source
from rt.core.materials import material_pages
from tests.api_support import isolated_workspace, make_lesson


def pdf(count=4):
    document = fitz.open()
    for n in range(count):
        page = document.new_page(width=100, height=120)
        page.insert_text((10, 30), f'Pagina {n + 1}: testo dello studio')
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def archive_lesson(api_client, rt_db, tmp_path, monkeypatch):
    root = isolated_workspace(tmp_path, monkeypatch)
    directory = make_lesson(root)
    lid = api_client.get('/api/v1/lessons').json()[0]['id']
    source = add_source(directory, 'materiale', 'Libro.pdf', pdf(), pagine=[1, 2], estrai='immagini')
    material_pages(directory, source)
    return lid, directory, source, root


def test_filters_summary_detail_and_continuation(api_client, archive_lesson):
    lid, directory, source, root = archive_lesson
    url = f'/api/v1/archive/{source.impronta}'
    listing = api_client.get('/api/v1/archive').json()
    assert len(listing) == 1 and listing[0]['da_continuare'] == '3–4'
    subject = listing[0]['materie'][0]
    assert api_client.get('/api/v1/archive', params={'materia': subject, 'tipo': 'slide', 'q': 'LIBRO'}).json() == listing
    assert api_client.get('/api/v1/archive?tipo=audio').json() == []
    assert api_client.get('/api/v1/archive?materia=Assente').json() == []
    assert api_client.get('/api/v1/archive?q=assente').json() == []
    assert api_client.get('/api/v1/archive/summary').json() == {'file': 1, 'da_continuare': 1}
    detail = api_client.get(url).json()
    assert [p['lezione_id'] for p in detail['pagine']] == [lid, lid, None, None]
    assert api_client.delete(url).status_code == 409


def test_continuation_across_lessons(api_client, archive_lesson):
    lid, directory, source, root = archive_lesson
    second = make_lesson(root, name='Seconda lezione')
    add_source(second, 'materiale', 'Libro.pdf', (Path(directory) / source.file).read_bytes(), pagine=[3])
    assert api_client.get(f'/api/v1/archive/{source.impronta}').json()['da_continuare'] == '4–4'
    # Le pagine di due lezioni, 1–18 e 19–30, su 64.
    from rt.services.archive_service import continuation
    assert continuation({'tipo': 'slide', 'pagine_totali': 64}, [{'pagine': list(range(1, 19))}, {'pagine': list(range(19, 31))}]) == '31–64'


def test_ignored_and_deleted_pages(api_client, archive_lesson):
    _, directory, source, _ = archive_lesson
    url = f'/api/v1/archive/{source.impronta}'
    response = api_client.put(url + '/ignored', json={'pagine': [1], 'ignorata': True})
    assert response.status_code == 200, response.text
    assert response.json()['pagine'][0]['ignorata']
    assert [p['numero'] for p in archive.pages_for_use(source.impronta)] == [2, 3, 4]
    api_client.put(url + '/ignored', json={'pagine': [1], 'ignorata': False})
    assert len(archive.pages_for_use(source.impronta)) == 4
    deleted = api_client.post(url + '/pages/delete', json={'pagine': [3]})
    assert [p['numero'] for p in deleted.json()['pagine']] == [1, 2, 4]
    assert not Path(archive.page_image_path(source.impronta, 'page-3-1.png')).exists()
    assert [p['numero'] for p in archive.pages_for_use(source.impronta)] == [1, 2, 4]
    assert api_client.get(url + '/pages/3.png').status_code == 404
    assert api_client.put(url + '/ignored', json={'pagine': [99], 'ignorata': True}).status_code == 422


def test_crop_both_modes_and_delete_unused(api_client, archive_lesson):
    _, _, source, _ = archive_lesson
    url = f'/api/v1/archive/{source.impronta}'
    original = Path(archive.page_image_path(source.impronta, 'page-1-1.png')).read_bytes()
    cropped = api_client.post(url + '/pages/1/crop', json={'rect': [0, 0, .5, .5]})
    assert cropped.status_code == 200, cropped.text
    new_sha = cropped.json()['impronta']
    assert new_sha != source.impronta
    assert archive.load_meta(new_sha)['ritaglio_di'] == {'sha': source.impronta, 'pagina': 1}
    assert Path(archive.page_image_path(source.impronta, 'page-1-1.png')).read_bytes() == original
    replaced = api_client.post(url + '/pages/1/crop', json={'rect': [0, 0, .5, .5], 'sostituisci': True})
    assert replaced.status_code == 200
    with Image.open(archive.page_image_path(source.impronta, 'page-1-1.png')) as image:
        assert image.size == (100, 120)
    assert api_client.delete(f'/api/v1/archive/{new_sha}').status_code == 204
    assert archive.find(new_sha) is None
    assert api_client.post(url + '/pages/1/crop', json={'rect': [0, 0, 0, .5]}).status_code == 422


def test_reuse_as_source_and_media_without_models(api_client, archive_lesson, monkeypatch):
    _, _, source, root = archive_lesson
    second = make_lesson(root, name='Seconda lezione')
    lid = next(l['id'] for l in api_client.get('/api/v1/lessons').json() if l['path'] == second)
    monkeypatch.setattr('rt.core.materials._extract', Mock(side_effect=AssertionError('estrazione')))
    monkeypatch.setattr('rt.core.materials._describe', Mock(side_effect=AssertionError('vision')))
    monkeypatch.setattr('rt.pipeline.source_update._transcribe', Mock(side_effect=AssertionError('trascrizione')))
    url = f'/api/v1/archive/{source.impronta}'
    result = api_client.post(url + '/add-to-lesson', json={'lesson_id': lid, 'pagine': [2, 4], 'uso': 'guida', 'estrai': 'immagini'})
    assert result.status_code == 201, result.text
    assert result.json()['pagine'] == [2, 4]
    assert api_client.get(f'/api/v1/lessons/{lid}/sources').json()['principale'] == result.json()['id']
    assert [p['numero'] for p in material_pages(second, __import__('rt.core.sources', fromlist=['Source']).Source.model_validate(result.json()))] == [2, 4]
    media = api_client.post(url + '/add-to-media', json={'lesson_id': lid, 'pagine': [1, 3]})
    assert media.status_code == 201, media.text
    assert len(media.json()) == 2
    assert len(list((Path(second) / 'assets/images').glob('*.png'))) == 2


def test_media_image_is_counted_as_in_use(api_client, archive_lesson):
    lid, directory, _source, _root = archive_lesson
    from rt.pipeline.add_images import save_raw_image, save_image_descriptions, compute_image_hash
    from tests.test_materials import png_bytes
    content = png_bytes()
    sha = compute_image_hash(content)
    path = save_raw_image(directory, content, sha)
    save_image_descriptions(directory, {sha: {'filename': path, 'source': 'editor:photo.png'}})
    detail = api_client.get(f'/api/v1/archive/{sha}').json()
    assert detail['usi'] == 1 and detail['lezioni'][0]['id'] == lid
    assert api_client.delete(f'/api/v1/archive/{sha}').status_code == 409


def test_text_only_preview_does_not_populate_image_cache(api_client, archive_lesson):
    _, directory, _, _ = archive_lesson
    source = add_source(directory, 'materiale', 'Testo.txt', b'Pagina di testo senza immagini')
    material_pages(directory, source)
    response = api_client.get(f'/api/v1/archive/{source.impronta}/pages/1.png')
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert list(Path(archive.entry_dir(source.impronta)).glob('*.png')) == []
    assert archive.load_meta(source.impronta)['estrai'] == 'testo'


def test_history_snapshots_are_not_counted_as_lessons(api_client, archive_lesson):
    lid, directory, source, _ = archive_lesson
    from rt.core.sources import _save
    history = Path(directory) / 'history' / 'old-version'
    history.mkdir(parents=True)
    (history / 'info.yaml').write_text('materia: Storica\ndata: 2026-01-01\n')
    _save(str(history), [source])
    response = api_client.get(f'/api/v1/archive/{source.impronta}')
    assert response.status_code == 200
    assert response.json()['usi'] == 1
    assert response.json()['lezioni'][0]['id'] == lid
