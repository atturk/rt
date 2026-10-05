"""Preferenze personali: persistenza, isolamento e validazione del corpo JSON."""
import pytest


def test_preferences_roundtrip(api_client, api_token):
    from rt.api.app import create_app
    from fastapi.testclient import TestClient
    from rt.db.engine import get_database
    from rt.db.repositories import SettingRepository
    from rt.db.session import session_scope
    with session_scope(get_database()) as session:
        SettingRepository(session).set('altro', {'privato': True})
    assert api_client.get('/api/v1/preferences').json() == {}
    values = {'theme': 'scuro', 'editor.shortcuts': {'bold': None}, 'audio.rate': 1.25,
              'study.rsvp': {'wpm': 300}, 'null': None, 'lista': [True, 1, 'à']}
    for name, value in values.items():
        response = api_client.put('/api/v1/preferences/' + name, json=value) if value is not None else api_client.put('/api/v1/preferences/' + name, content='null')
        assert response.status_code == 204, response.text
    fresh = TestClient(create_app())
    fresh.headers['Authorization'] = f'Bearer {api_token}'
    assert fresh.get('/api/v1/preferences').json() == values
    assert fresh.delete('/api/v1/preferences/theme').status_code == 204
    assert fresh.delete('/api/v1/preferences/theme').status_code == 204
    assert 'theme' not in api_client.get('/api/v1/preferences').json()
    with session_scope(get_database()) as session:
        assert SettingRepository(session).get('altro') == {'privato': True}


@pytest.mark.parametrize('name', ['A', 'é', '_theme', 'a' * 65, 'theme!', 'a%0A'])
def test_invalid_name(api_client, name):
    assert api_client.put('/api/v1/preferences/' + name, json='value').status_code == 422
    assert api_client.delete('/api/v1/preferences/' + name).status_code == 422


def test_body_limit_and_invalid_json(api_client):
    url = '/api/v1/preferences/test'
    for body in ['"' + 'x' * 16383 + '"', '"' + 'à' * 8192 + '"', '{', 'NaN', '']:
        assert api_client.put(url, content=body).status_code == 422
    assert api_client.put(url, content='"' + 'x' * 16382 + '"').status_code == 204


def test_preferences_require_auth(rt_db):
    from rt.api.app import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app())
    assert client.get('/api/v1/preferences').status_code == 401
    assert client.put('/api/v1/preferences/theme', json='chiaro').status_code == 401
    assert client.delete('/api/v1/preferences/theme').status_code == 401
