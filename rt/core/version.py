"""
Gestione della versione e dell'aggiornamento automatico di RT tramite GitHub Releases.
Nessuna dipendenza da git per l'utente finale.
"""
import os
import re
import sys
import json
import shutil
import tempfile
import tarfile
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Tuple, List

OFFICIAL_GIT_URL = "https://github.com/atturk/rt.git"


def parse_semver(version_str: str) -> Optional[Tuple[int, int, int]]:
    """
    Estrae la tupla (major, minor, patch) da una stringa di versione (es. 'v2.4.0', '2.4.0', 'v2.10.1').
    Ritorna None se la stringa non è un formato semver valido numerico.
    """
    if not version_str:
        return None
    s = version_str.strip()
    if s.startswith(("v", "V")):
        s = s[1:]
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$", s)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) is not None else 0
    patch = int(m.group(3)) if m.group(3) is not None else 0
    return (major, minor, patch)


def format_version(version_str: str) -> str:
    """Formatta la versione per l'output utente (rimuove prefisso 'v'/'V' se presente)."""
    s = version_str.strip()
    if (s.startswith("v") or s.startswith("V")) and len(s) > 1 and s[1].isdigit():
        return s[1:]
    return s


def get_current_version(project_root: str) -> str:
    """
    Legge il file VERSION alla radice di project_root.
    Se non esiste o è vuoto/non valido, ritorna 'sconosciuta'.
    """
    version_file = os.path.join(project_root, "VERSION")
    if not os.path.isfile(version_file):
        return "sconosciuta"
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return "sconosciuta"
        return format_version(content)
    except OSError:
        return "sconosciuta"


def get_latest_remote_version(project_root: str, timeout: float = 5.0) -> Optional[str]:
    """
    Esegue una chiamata HTTP GET all'API pubblica di GitHub Releases per determinare
    la versione più recente pubblicata di RT (es. '3.3.8').
    Ritorna:
    - None in caso di offline, errore di connessione, o timeout.
    - "" (stringa vuota) se non esiste ancora nessuna Release pubblicata (HTTP 404).
    - la stringa di versione (es. '3.3.8') se disponibile.
    """
    url = "https://api.github.com/repos/atturk/rt/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RT-Updater",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))
            tag_name = data.get("tag_name", "")
            if not tag_name:
                return ""
            return format_version(tag_name)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def run_version(project_root: str) -> None:
    """
    Verifica e stampa a video la versione corrente di RT e l'eventuale disponibilità
    di un aggiornamento sul repository remoto.
    """
    current_ver = get_current_version(project_root)
    latest_ver = get_latest_remote_version(project_root)

    if latest_ver is None:
        print(f"RT versione {current_ver} (impossibile verificare aggiornamenti — controlla la connessione)")
        return
    if latest_ver == "":
        print(f"RT versione {current_ver} (nessuna versione pubblicata ancora sul repository)")
        return

    curr_parsed = parse_semver(current_ver)
    lat_parsed = parse_semver(latest_ver)

    if curr_parsed is not None and lat_parsed is not None:
        if curr_parsed >= lat_parsed:
            print(f"RT versione {current_ver} — sei aggiornato ✅")
        else:
            print(f"RT versione {current_ver} — è disponibile la versione {latest_ver}")
            print("Esegui 'rt -u' per aggiornare")
    else:
        print(f"RT versione {current_ver} — è disponibile la versione {latest_ver}")
        print("Esegui 'rt -u' per aggiornare")


def _is_update_excluded(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    top = parts[0]
    if top in ("config", ".venv", ".git", ".rt_telegram", ".agents", ".agent", ".claude"):
        return True
    if top == ".env" or top.startswith(".env."):
        return True
    if top == "install.log":
        return True
    return False


def _is_managed_code(rel_path: str) -> bool:
    """Solo queste directory appartengono al distributore, mai i dati dell'utente."""
    return rel_path.replace("\\", "/").split("/")[0] in (
        "rt", "bin", "config.example", "docs",
    )


def _install_runtime_requirements(project_root: str) -> bool:
    """Installa le dipendenze nel venv di RT e rende visibile qualsiasi errore."""
    req_file = os.path.join(project_root, "requirements-web.txt")
    if not os.path.isfile(req_file):
        req_file = os.path.join(project_root, "requirements.txt")
    if not os.path.isfile(req_file):
        return True

    venv_python = os.path.join(project_root, ".venv", "bin", "python3")
    if not os.path.isfile(venv_python):
        print("❌ Ambiente Python di RT assente: esegui install.sh per ripristinarlo.", file=sys.stderr)
        return False

    print("Verifica e installazione delle dipendenze Python...")
    try:
        result = subprocess.run(
            [venv_python, "-m", "pip", "install", "-r", req_file, "--quiet"],
            cwd=project_root,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"❌ Installazione delle dipendenze fallita: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(
            f"❌ Installazione delle dipendenze fallita (codice {result.returncode}). "
            "Controlla l'errore di pip qui sopra e riprova con 'rt -u'.",
            file=sys.stderr,
        )
        return False
    return True


def _git_checkout_is_safe_to_update(project_root: str) -> bool:
    """Un aggiornamento Git è ammesso solo sul main senza modifiche tracciate."""
    checks = (
        (["git", "rev-parse", "--abbrev-ref", "HEAD"], "main", "RT deve trovarsi sul branch main."),
        (["git", "status", "--porcelain", "--untracked-files=no"], "", "Il checkout ha modifiche locali ai file tracciati."),
    )
    for command, expected, message in checks:
        try:
            result = subprocess.run(command, cwd=project_root, capture_output=True, text=True, check=False)
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"❌ Impossibile verificare il checkout Git: {exc}", file=sys.stderr)
            return False
        if result.returncode != 0 or result.stdout.strip() != expected:
            print(f"❌ {message} Aggiornamento interrotto senza modificare i file.", file=sys.stderr)
            return False
    return True


def _update_git_checkout(project_root: str, latest_ver: str) -> bool:
    """Porta un checkout pulito al tag ufficiale, senza riscrivere la cronologia."""
    print(f"Aggiornamento Git alla release {latest_ver}...")
    commands = (
        ["git", "fetch", "--no-tags", OFFICIAL_GIT_URL, f"refs/tags/v{latest_ver}"],
        ["git", "merge", "--ff-only", "FETCH_HEAD"],
    )
    for command in commands:
        try:
            result = subprocess.run(command, cwd=project_root, check=False)
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"❌ Aggiornamento Git fallito: {exc}", file=sys.stderr)
            return False
        if result.returncode != 0:
            print("❌ Impossibile aggiornare senza perdere modifiche o riscrivere la cronologia Git.", file=sys.stderr)
            return False
    if get_current_version(project_root) != latest_ver:
        print("❌ La versione del checkout non coincide con la release richiesta.", file=sys.stderr)
        return False
    return True


def _print_secrets_migration_hint(project_root: str) -> None:
    """RT4-C2: dopo l'aggiornamento suggerisce 'rt secrets migrate' se .env contiene chiavi in
    chiaro e l'archivio cifrato non esiste. Non migra da solo e non blocca mai l'update."""
    try:
        from rt.services.secrets_service import env_needs_migration
        if env_needs_migration(os.path.join(project_root, ".env"),
                               os.path.join(project_root, "config", "general.yaml")):
            print("🔐 Le chiavi API sono ancora in chiaro nel file .env: per cifrarle esegui "
                  "'rt secrets init' e poi 'rt secrets migrate'.")
    except Exception:
        pass


def run_update(project_root: str) -> int:
    """
    Esegue l'aggiornamento automatico sicuro di RT tramite GitHub Releases:
    1. Verifica disponibilità di una versione più recente via API GitHub.
    2. Scarica il tarball sorgente in una directory temporanea (mai in project_root).
    3. Estrae l'archivio nella directory temporanea.
    4. Sincronizza il codice estratto dentro project_root preservando configurazioni utente.
    5. Pulisce la directory temporanea.
    6. Installa le dipendenze CLI e web nel virtualenv.
    7. Scrive VERSION solo dopo l'installazione riuscita.
    Restituisce il codice di uscita per la CLI (0 = ok o già aggiornato, 1 = errore).
    """
    git_checkout = os.path.exists(os.path.join(project_root, ".git"))
    if git_checkout and not _git_checkout_is_safe_to_update(project_root):
        return 1

    latest_ver = get_latest_remote_version(project_root)
    if latest_ver is None:
        print("❌ Impossibile verificare gli aggiornamenti remoti (errore di connessione).", file=sys.stderr)
        return 1
    if latest_ver == "":
        print("Nessuna versione pubblicata ancora sul repository.")
        return 0

    curr_ver = get_current_version(project_root)
    curr_parsed = parse_semver(curr_ver)
    lat_parsed = parse_semver(latest_ver)

    if curr_parsed is not None and lat_parsed is not None and curr_parsed >= lat_parsed:
        if curr_parsed == lat_parsed and not _install_runtime_requirements(project_root):
            return 1
        print(f"Sei già aggiornato all'ultima versione ({curr_ver}).")
        return 0

    if git_checkout:
        if not _update_git_checkout(project_root, latest_ver):
            return 1
        if not _install_runtime_requirements(project_root):
            return 1
        print(f"✅ RT aggiornato: {curr_ver} → {latest_ver}")
        _print_secrets_migration_hint(project_root)
        return 0

    print(f"Aggiornamento in corso ({curr_ver} → {latest_ver})...")
    temp_dir = tempfile.mkdtemp(prefix="rt-update-")
    try:
        tarball_url = f"https://github.com/atturk/rt/archive/refs/tags/v{latest_ver}.tar.gz"
        archive_path = os.path.join(temp_dir, "release.tar.gz")
        req = urllib.request.Request(
            tarball_url,
            headers={"User-Agent": "RT-Updater"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp, open(archive_path, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)
        except Exception as exc:
            print(f"❌ Impossibile scaricare l'aggiornamento: {exc}", file=sys.stderr)
            return 1

        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=temp_dir)
        except Exception as exc:
            print(f"❌ Impossibile estrarre l'archivio di aggiornamento: {exc}", file=sys.stderr)
            return 1

        extracted_dirs = [
            d for d in os.listdir(temp_dir)
            if os.path.isdir(os.path.join(temp_dir, d)) and d != "__MACOSX" and not d.startswith(".")
        ]
        if not extracted_dirs:
            print("❌ Archivio di aggiornamento non valido o vuoto.", file=sys.stderr)
            return 1

        extracted_root = os.path.join(temp_dir, extracted_dirs[0])

        # Copia file estratti sovrascrivendo l'equivalente in project_root (escludendo
        # config/.env/.venv/install.log). VERSION è copiato per ultimo, fuori da questo
        # loop (vedi sotto): l'ordine di os.walk() non è garantito, e se il processo
        # venisse interrotto a metà sincronizzazione dopo aver già scritto il nuovo
        # VERSION ma prima di tutti gli altri file, un successivo 'rt -u' vedrebbe
        # l'installazione già aggiornata (VERSION combacia) e non la risincronizzerebbe
        # mai più, lasciandola permanentemente inconsistente.
        for root, dirs, files in os.walk(extracted_root):
            for f in files:
                src_file = os.path.join(root, f)
                rel_path = os.path.relpath(src_file, extracted_root)
                if rel_path == "VERSION" or _is_update_excluded(rel_path):
                    continue
                dst_file = os.path.join(project_root, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                shutil.copy2(src_file, dst_file)

        # Rimuovi soltanto codice orfano nelle directory gestite. File e directory
        # sconosciuti alla release possono essere dati locali e vanno preservati.
        for root, dirs, files in os.walk(project_root, topdown=False):
            rel_dir = os.path.relpath(root, project_root)
            if rel_dir != "." and _is_update_excluded(rel_dir):
                continue
            for f in files:
                p_file = os.path.join(root, f)
                rel_path = os.path.relpath(p_file, project_root)
                if _is_update_excluded(rel_path) or not _is_managed_code(rel_path):
                    continue
                extracted_file = os.path.join(extracted_root, rel_path)
                if not os.path.exists(extracted_file):
                    try:
                        os.remove(p_file)
                    except OSError:
                        pass
            if rel_dir != "." and _is_managed_code(rel_dir):
                extracted_dir = os.path.join(extracted_root, rel_dir)
                if not os.path.exists(extracted_dir):
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass

        # VERSION per ultimo, dopo la sincronizzazione e le dipendenze. Un errore
        # di pip lascia la vecchia versione per consentire un nuovo tentativo.
        if not _install_runtime_requirements(project_root):
            return 1
        new_version_src = os.path.join(extracted_root, "VERSION")
        if os.path.isfile(new_version_src):
            shutil.copy2(new_version_src, os.path.join(project_root, "VERSION"))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    new_ver = get_current_version(project_root)
    print(f"✅ RT aggiornato: {curr_ver} → {new_ver}")
    _print_secrets_migration_hint(project_root)
    return 0
