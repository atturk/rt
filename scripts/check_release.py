"""Verifica l'archivio Git distribuito, senza includere file locali del checkout."""
import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rt.core.changelog import release_notes


REQUIRED = {
    'VERSION', 'CHANGELOG.md', 'README.md', 'requirements.txt', 'requirements-web.txt', 'constraints.txt',
    'install.sh', 'bootstrap.sh', 'bin/rt', 'rt/cli.py', '.env.example',
    'config.example/general.yaml',
}
ALLOWED_ROOT_FILES = {
    'VERSION', 'CHANGELOG.md', 'README.md', 'requirements.txt', 'requirements-web.txt', 'constraints.txt',
    'install.sh', 'bootstrap.sh', '.env.example',
}
ALLOWED_DIRS = {'rt', 'bin', 'config.example', 'docs'}
FORBIDDEN_PARTS = {
    '.git', '.agents', '.agent', '.claude', '.env', '.venv', 'config',
    '.rt_telegram', '__pycache__', '.DS_Store', 'tests', 'scratch',
}


def check_archive(payload: bytes, expected_version: str) -> str:
    """Rifiuta contenuti privati, file di sviluppo e distribuzioni incomplete."""
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        names = set()
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or len(path.parts) < 2:
                if member.isdir() and len(path.parts) == 1:
                    continue
                raise ValueError(f'Percorso non valido: {member.name}')
            rel = PurePosixPath(*path.parts[1:])
            if FORBIDDEN_PARTS.intersection(rel.parts):
                raise ValueError(f'File locale nella release: {rel}')
            if not member.isdir() and not member.isfile():
                raise ValueError(f'Tipo di file non ammesso: {rel}')
            if member.isdir():
                continue
            name = str(rel)
            if rel.parts[0] not in ALLOWED_DIRS and name not in ALLOWED_ROOT_FILES:
                raise ValueError(f'File non previsto nella distribuzione: {rel}')
            if rel.suffix in {'.pyc', '.pyo', '.log', '.wav', '.mp3', '.m4a'}:
                raise ValueError(f'Artefatto generato o privato: {rel}')
            names.add(name)
        missing = REQUIRED - names
        if missing:
            raise ValueError(f'File runtime mancanti: {sorted(missing)}')
        prefix = archive.getmembers()[0].name.split('/')[0]
        version_file = archive.extractfile(f'{prefix}/VERSION')
        if version_file.read().decode().strip() != expected_version:
            raise ValueError('VERSION non corrisponde alla release')
        changelog = archive.extractfile(f'{prefix}/CHANGELOG.md').read().decode('utf-8')
        notes = release_notes(changelog, expected_version)
        for name in ('bin/rt', 'install.sh', 'bootstrap.sh'):
            if not archive.getmember(f'{prefix}/{name}').mode & 0o111:
                raise ValueError(f'Permesso eseguibile mancante: {name}')

        return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', help='Tag di release: deve coincidere con VERSION')
    parser.add_argument('--output', type=Path, help='Salva archivio e SHA256SUMS')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = subprocess.check_output(['git', 'show', 'HEAD:VERSION'], cwd=root, text=True).strip()
    # stabile (4.0.1) o prerelease PEP 440 (4.1.0b1, 4.1.0rc1): la pubblica come beta release.yml;
    # la quarta cifra è un fix urgente della versione precedente (4.2.2.1, 4.2.3b1.1), anche in beta
    # (4.2.3.2b1)
    if not re.fullmatch(r'\d+\.\d+\.\d+(((a|b|rc)\d+)?(\.\d+)?|\.\d+(a|b|rc)\d+)', version):
        raise SystemExit('VERSION deve contenere major.minor.patch, con eventuale aN/bN/rcN e .N di fix')
    if args.tag and args.tag != f'v{version}':
        raise SystemExit(f'Tag {args.tag} diverso da VERSION ({version})')
    archive = subprocess.check_output(
        ['git', 'archive', '--format=tar.gz', f'--prefix=rt-{version}/', 'HEAD'], cwd=root,
    )
    try:
        notes = check_archive(archive, version)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'release-notes.md').write_text(notes, encoding='utf-8')
        filename = f'rt-{version}.tar.gz'
        (args.output / filename).write_bytes(archive)
        checksum = hashlib.sha256(archive).hexdigest()
        (args.output / 'SHA256SUMS').write_text(f'{checksum}  {filename}\n')
    print(f'Archivio RT {version}: contenuti e versione verificati.')


if __name__ == '__main__':
    main()
