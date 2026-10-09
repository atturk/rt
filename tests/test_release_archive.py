"""Regressioni per la separazione tra archivio runtime e dati locali."""
import io
import tarfile
import pytest
from scripts.check_release import check_archive, REQUIRED


def make_archive(extra=None, omit=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for name in sorted((REQUIRED | set(extra or [])) - set(omit or [])):
            data = b'3.3.12\n' if name == 'VERSION' else '## 3.3.12 — 2026-10-09\n\n### Novità\n\n- Esempio.\n'.encode('utf-8') if name == 'CHANGELOG.md' else b'example\n'
            info = tarfile.TarInfo('rt-3.3.12/' + name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_runtime_archive_is_accepted():
    check_archive(make_archive(), '3.3.12')


@pytest.mark.parametrize('name', ['.agents/notes.md', '.env', 'config/general.yaml',
                                 '.rt_telegram/registry.json', 'tests/test_x.py',
                                 'rt/__pycache__/x.pyc', 'scratch/notes.md'])
def test_private_and_development_files_are_rejected(name):
    with pytest.raises(ValueError):
        check_archive(make_archive(extra=[name]), '3.3.12')


def test_incomplete_archive_is_rejected():
    with pytest.raises(ValueError):
        check_archive(make_archive(omit=['constraints.txt']), '3.3.12')


def test_version_mismatch_is_rejected():
    with pytest.raises(ValueError):
        check_archive(make_archive(), '3.3.13')


def test_prerelease_archive_is_accepted():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for name in sorted(REQUIRED):
            data = b'4.1.0b1\n' if name == 'VERSION' else '## 4.1.0b1 — 2026-10-09\n\n### Novità\n\n- Beta.\n'.encode('utf-8') if name == 'CHANGELOG.md' else b'example\n'
            info = tarfile.TarInfo('rt-4.1.0b1/' + name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    check_archive(buffer.getvalue(), '4.1.0b1')


def test_changelog_is_required_and_notes_are_extracted():
    with pytest.raises(ValueError, match='CHANGELOG.md'):
        check_archive(make_archive(omit=['CHANGELOG.md']), '3.3.12')
    assert check_archive(make_archive(), '3.3.12') == '### Novità\n\n- Esempio.\n'


def test_missing_version_section_is_rejected():
    from rt.core.changelog import release_notes
    with pytest.raises(ValueError, match='manca la sezione della versione 4.2.4b1'):
        release_notes('## 4.2.4b2 — 2026-10-09\n- Altro', '4.2.4b1')
