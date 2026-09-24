"""Regressioni per la separazione tra archivio runtime e dati locali."""
import io
import tarfile
import pytest
from scripts.check_release import check_archive, REQUIRED


def make_archive(extra=None, omit=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for name in sorted((REQUIRED | set(extra or [])) - set(omit or [])):
            data = b'3.3.12\n' if name == 'VERSION' else b'example\n'
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
