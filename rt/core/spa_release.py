"""
rt.core.spa_release
Installa la web app compilata (SPA, RT4-F8) dalla GitHub Release della versione di RT.

La release allega `rt-spa-<versione>.tar.gz` (build di frontend/) e `SHA256SUMS`. Il pacchetto
viene verificato con lo sha256, estratto in una cartella temporanea accanto alla destinazione e
poi scambiato con `rt/spa` in un colpo solo: una SPA a metà non viene mai servita. `rt/spa/VERSION`
ricorda la versione installata, così 'rt -u' non riscarica la stessa build.

install.sh chiama main(); 'rt -u' chiama update_spa().
"""
import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from typing import Callable, Optional

RELEASE_URL = "https://github.com/atturk/rt/releases/download/v{version}/{name}"
SPA_REL_DIR = os.path.join("rt", "spa")
VERSION_FILE = "VERSION"


class SpaReleaseMissing(Exception):
    """La release non allega la SPA (release precedenti alla fase F)."""


def spa_dir(project_root: str) -> str:
    return os.path.join(project_root, SPA_REL_DIR)


def installed_version(project_root: str) -> Optional[str]:
    try:
        with open(os.path.join(spa_dir(project_root), VERSION_FILE), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _download(url: str, opener: Optional[Callable]) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "RT-Updater"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=60.0) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SpaReleaseMissing(url) from exc
        raise


def _expected_sha(sums: str, name: str) -> Optional[str]:
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    return None


def _extract(data: bytes, target: str) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = os.path.normpath(member.name)
            if os.path.isabs(name) or name.startswith(".."):
                raise ValueError(f"percorso non ammesso nel pacchetto della web app: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"tipo di file non ammesso nel pacchetto della web app: {member.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(target, filter="data")
        else:  # pragma: no cover - Python senza i filtri di estrazione
            tar.extractall(target)
    if not os.path.isfile(os.path.join(target, "index.html")):
        raise ValueError("pacchetto della web app senza index.html")


def install_spa(project_root: str, version: str, opener: Optional[Callable] = None,
                force: bool = False) -> bool:
    """Scarica e installa la SPA della versione data in rt/spa. True se l'ha installata, False
    se c'era già. Solleva SpaReleaseMissing se la release non la allega, altre eccezioni per
    rete, sha256 o pacchetto non validi (rt/spa resta com'era)."""
    if not force and installed_version(project_root) == version:
        return False
    name = f"rt-spa-{version}.tar.gz"
    sums = _download(RELEASE_URL.format(version=version, name="SHA256SUMS"), opener).decode("utf-8")
    expected = _expected_sha(sums, name)
    if expected is None:
        raise SpaReleaseMissing(name)
    data = _download(RELEASE_URL.format(version=version, name=name), opener)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"sha256 di {name} diverso da SHA256SUMS: download corrotto")

    target = spa_dir(project_root)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".spa-new-", dir=parent)
    try:
        _extract(data, staging)
        with open(os.path.join(staging, VERSION_FILE), "w", encoding="utf-8") as f:
            f.write(version + "\n")
        old = None
        if os.path.exists(target):
            old = tempfile.mkdtemp(prefix=".spa-old-", dir=parent)
            os.rmdir(old)
            os.replace(target, old)
        os.replace(staging, target)
        if old:
            shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return True


def update_spa(project_root: str, version: str, opener: Optional[Callable] = None) -> bool:
    """Per 'rt -u' e install.sh: installa la SPA della versione e dice cosa è successo.
    False solo per errori veri (rete, sha256): una release senza SPA è un avviso."""
    try:
        if install_spa(project_root, version, opener):
            print(f"✅ Web app {version} installata.")
        return True
    except SpaReleaseMissing:
        print(f"⚠️ La release {version} non contiene la web app compilata: 'rt web' resterà senza "
              "interfaccia finché non aggiorni (l'API funziona).", file=sys.stderr)
        return True
    except Exception as exc:  # rete, sha256, pacchetto: rt/spa resta com'era
        print(f"❌ Installazione della web app fallita: {exc}. Riprova con 'rt -u'.", file=sys.stderr)
        return False


def main(project_root: str) -> int:
    """Installa la SPA della versione di RT in project_root; codice di uscita per install.sh."""
    from rt.core.version import get_current_version
    root = os.path.abspath(project_root)
    version = get_current_version(root)
    if version == "sconosciuta":
        print("⚠️ Versione di RT sconosciuta: web app non installata.", file=sys.stderr)
        return 0
    return 0 if update_spa(root, version) else 1
