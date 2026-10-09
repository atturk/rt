"""Parsing delle note installate e API autenticata."""
from rt.core.changelog import parse_changelog, read_changelog, release_notes

TEXT = """# Novità

## 4.2.4b1 — 2026-10-09

### Novità
- Zen.
  Continuazione.
- Linguetta.

### Correzioni
- Frecce.

## 4.2.3 — 2026-10-08

### Cambiamenti
- Prima.

Per le versioni precedenti: [GitHub](https://github.com/atturk/rt/releases).
"""


def test_parser_keeps_order_groups_and_continuations():
    sections = parse_changelog(TEXT)
    assert sections == [
        {'version': '4.2.4b1', 'date': '2026-10-09', 'groups': [
            {'title': 'Novità', 'items': ['Zen. Continuazione.', 'Linguetta.']},
            {'title': 'Correzioni', 'items': ['Frecce.']}]},
        {'version': '4.2.3', 'date': '2026-10-08', 'groups': [{'title': 'Cambiamenti', 'items': ['Prima.']}]}]
    assert '4.2.3' not in release_notes(TEXT, '4.2.4b1')
    assert 'Per le versioni precedenti' not in release_notes(TEXT, '4.2.3')


def test_missing_and_empty_changelog(tmp_path):
    assert read_changelog(tmp_path) == []
    (tmp_path / 'CHANGELOG.md').write_text('# Novità\n', encoding='utf-8')
    assert read_changelog(tmp_path) == []


def test_changelog_api_reads_installation_and_requires_auth(api_client, tmp_path, monkeypatch):
    monkeypatch.setattr('rt.core.config._default_project_root', lambda: str(tmp_path))
    assert api_client.get('/api/v1/system/changelog').json() == []
    (tmp_path / 'CHANGELOG.md').write_text(TEXT, encoding='utf-8')
    response = api_client.get('/api/v1/system/changelog')
    assert response.status_code == 200
    assert response.json() == parse_changelog(TEXT)
    api_client.headers.pop('Authorization')
    assert api_client.get('/api/v1/system/changelog').status_code == 401
