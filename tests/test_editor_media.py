"""Caricamento dall'editor, riferimenti relativi ed export con i media."""
import io
import os
import zipfile

from PIL import Image
import pytest

from tests.api_support import isolated_workspace, make_lesson, run_mock_pipeline


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    path = make_lesson(root)
    run_mock_pipeline(path)
    return path


def _image(fmt):
    stream = io.BytesIO()
    first = Image.new('RGB', (12, 12), 'red')
    if fmt == 'GIF':
        first.save(stream, format=fmt, save_all=True, append_images=[Image.new('RGB', (12, 12), 'blue')], duration=100, loop=0)
    else:
        first.save(stream, format=fmt)
    return stream.getvalue()


def _id(client):
    return client.get('/api/v1/lessons').json()[0]['id']


@pytest.mark.parametrize('fmt,extension', [('PNG', '.png'), ('JPEG', '.jpg'), ('GIF', '.gif')])
@pytest.mark.parametrize('storage', ['folder', 'db'])
def test_uploaded_images_survive_document_and_exports(api_client, lesson, fmt, extension, storage):
    from rt.storage import fs
    if storage == 'db':
        from rt.storage.migrate import migrate_storage
        assert migrate_storage(os.path.dirname(lesson)).errors == []
    lid = _id(api_client)
    data = _image(fmt)
    response = api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('../../[slide].fake', data, 'application/octet-stream')})
    assert response.status_code == 201, response.text
    image = response.json()
    assert image['path'].startswith('assets/images/') and image['path'].endswith(extension)
    assert image['alt_text'] == 'slide'
    assert api_client.get(image['url']).content == data
    assert fs.isfile(os.path.join(lesson, image['path']))
    again = api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('other.png', data, 'image/png')})
    assert again.json()['path'] == image['path']
    assert len(api_client.get(f'/api/v1/lessons/{lid}/images').json()['images']) == 1
    document = api_client.get(f'/api/v1/lessons/{lid}/document').json()['markdown']
    markdown = document + f"\n\n![slide]({image['path']})\n"
    saved = api_client.put(f'/api/v1/lessons/{lid}/document/draft', json={'markdown': markdown})
    assert saved.status_code == 200, saved.text
    exported = api_client.get(f'/api/v1/lessons/{lid}/export?format=markdown').text
    assert f"![slide]({image['path']})" in exported
    assert '/api/v1/' not in exported and 'data:image/' not in exported
    for scope in ('final', 'all'):
        response = api_client.get(f'/api/v1/lessons/{lid}/export?format=zip&scope={scope}')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            target = next(n for n in archive.namelist() if n.endswith('/' + image['path']))
            assert archive.read(target) == data
            assert any(image['path'] in archive.read(n).decode() for n in archive.namelist() if n.endswith('.md'))


@pytest.mark.parametrize('payload', [b'', b'not an image', b'GIF89a broken', _image('WEBP')])
def test_rejects_invalid_or_unsupported_images(api_client, lesson, payload):
    lid = _id(api_client)
    response = api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('image.png', payload, 'image/png')})
    assert response.status_code == 422
    assert api_client.get(f'/api/v1/lessons/{lid}/images').json()['images'] == []


def test_upload_limit_and_locks(api_client, lesson, monkeypatch, rt_db):
    from rt.services import editor_media_service
    from rt.services.jobs import DbJobQueue
    lid = _id(api_client)
    data = _image('PNG')
    monkeypatch.setattr(editor_media_service, 'MAX_IMAGE_BYTES', len(data) - 1)
    response = api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('image.png', data)})
    assert response.status_code == 413
    monkeypatch.setattr(editor_media_service, 'MAX_IMAGE_BYTES', len(data))
    lease = api_client.post(f'/api/v1/lessons/{lid}/document/lease').json()['token']
    assert api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('image.png', data)}).status_code == 409
    assert api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('image.png', data)}, data={'lease_token': lease}).status_code == 201
    api_client.delete(f'/api/v1/lessons/{lid}/document/lease?token={lease}')
    job = DbJobQueue(rt_db).enqueue('run_phase', lesson, {'phase': 'rewrite'})
    response = api_client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('image.png', data)})
    assert response.status_code == 409 and response.json()['error']['details']['job_id'] == job


def test_upload_requires_authentication(api_client, lesson):
    from fastapi.testclient import TestClient
    from rt.api.app import create_app
    lid = _id(api_client)
    client = TestClient(create_app())
    assert client.post(f'/api/v1/lessons/{lid}/media/images', files={'file': ('image.png', _image('PNG'))}).status_code == 401
