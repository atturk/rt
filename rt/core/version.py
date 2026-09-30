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

from rt.core.spa_release import update_spa

OFFICIAL_GIT_URL = "https://github.com/atturk/rt.git"
OFFLINE_ENV = "RT_UPDATE_OFFLINE"
RELEASES_API = "https://api.github.com/repos/atturk/rt/releases"

# Canali di aggiornamento: "stable" segue solo le release normali (releases/latest, che GitHub
# calcola escludendo le prerelease); "beta" segue anche le prerelease (es. 4.1.0b1).
STABLE, BETA = "stable", "beta"
CHANNELS = (STABLE, BETA)
CHANNEL_FILE = "update-channel"

_VERSION_RE = re.compile(
    r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(a|alpha|b|beta|c|rc)[-.]?(\d*))?$", re.IGNORECASE)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2}
_FINAL_RANK = 3


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


def parse_version(version_str: str) -> Optional[Tuple[int, int, int, int, int]]:
    """Come parse_semver, ma ordina anche le prerelease PEP 440: 4.1.0a1 < 4.1.0b1 < 4.1.0rc1
    < 4.1.0. Ritorna (major, minor, patch, rango, numero) o None se non è una versione."""
    if not version_str:
        return None
    m = _VERSION_RE.match(format_version(version_str))
    if not m:
        return None
    major, minor, patch = (int(g) if g is not None else 0 for g in m.group(1, 2, 3))
    if m.group(4) is None:
        return (major, minor, patch, _FINAL_RANK, 0)
    return (major, minor, patch, _PRE_RANK[m.group(4).lower()], int(m.group(5) or 0))


def is_prerelease(version_str: str) -> bool:
    parsed = parse_version(version_str)
    return parsed is not None and parsed[3] != _FINAL_RANK


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


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RT-Updater",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            return None
        return json.loads(response.read().decode("utf-8"))


def get_latest_remote_version(project_root: str, timeout: float = 5.0,
                              channel: str = STABLE) -> Optional[str]:
    """
    Interroga l'API pubblica di GitHub Releases per la versione più recente di RT.
    Canale "stable": /releases/latest, che esclude prerelease e bozze.
    Canale "beta": la versione più alta fra le release pubblicate, prerelease comprese.
    Ritorna:
    - None in caso di offline, errore di connessione, o timeout.
    - "" (stringa vuota) se non esiste ancora nessuna Release pubblicata (HTTP 404).
    - la stringa di versione (es. '3.3.8' o '4.1.0b1') se disponibile.
    """
    url = f"{RELEASES_API}?per_page=50" if channel == BETA else f"{RELEASES_API}/latest"
    try:
        data = _get_json(url, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if data is None:
        return None
    if channel != BETA:
        if isinstance(data, dict) and not _assets_ready(data):
            # release appena pubblicata: il workflow non ha ancora allegato i file
            try:
                listed = _get_json(f"{RELEASES_API}?per_page=50", timeout)
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                return None
            return _highest_ready(listed, include_prerelease=False)
        tag_name = data.get("tag_name", "") if isinstance(data, dict) else ""
        return format_version(tag_name) if tag_name else ""
    return _highest_ready(data, include_prerelease=True)


def _assets_ready(release: dict) -> bool:
    """False se la release elenca i suoi file e fra questi manca ancora SHA256SUMS: il workflow
    di release li allega qualche minuto dopo la pubblicazione (prima 'rt -u' installava una
    versione senza web app)."""
    assets = release.get("assets")
    if not isinstance(assets, list):
        return True
    return any(isinstance(a, dict) and a.get("name") == "SHA256SUMS" for a in assets)


def _highest_ready(data, include_prerelease: bool) -> Optional[str]:
    if not isinstance(data, list):
        return None
    versions = [format_version(r.get("tag_name", "")) for r in data
                if isinstance(r, dict) and not r.get("draft") and _assets_ready(r)
                and (include_prerelease or not r.get("prerelease"))]
    versions = [v for v in versions if parse_version(v) is not None]
    return max(versions, key=parse_version) if versions else ""


def channel_file() -> str:
    """Il canale scelto sta nella cartella dati (~/.rt o RT_DATA_DIR): sopravvive agli
    aggiornamenti del codice e non tocca rt-data.json (che attiva la cartella dati)."""
    from rt.core import paths
    return os.path.join(paths.data_dir(), CHANNEL_FILE)


def get_update_channel() -> str:
    try:
        with open(channel_file(), encoding="utf-8") as f:
            value = f.read().strip().lower()
    except OSError:
        return STABLE
    return value if value in CHANNELS else STABLE


def set_update_channel(channel: str) -> None:
    if channel not in CHANNELS:
        raise ValueError(f"Canale di aggiornamento sconosciuto: {channel}")
    path = channel_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(channel + "\n")


def run_version(project_root: str) -> None:
    """
    Verifica e stampa a video la versione corrente di RT e l'eventuale disponibilità
    di un aggiornamento sul repository remoto, secondo il canale scelto (stabile o beta).
    """
    current_ver = get_current_version(project_root)
    channel = get_update_channel()
    latest_ver = get_latest_remote_version(project_root, channel=channel)
    label = f"RT versione {current_ver}" + (" (canale beta)" if channel == BETA else "")

    if latest_ver is None:
        print(f"{label} (impossibile verificare aggiornamenti — controlla la connessione)")
        return
    if latest_ver == "":
        print(f"{label} (nessuna versione pubblicata ancora sul repository)")
        return

    curr_parsed = parse_version(current_ver)
    lat_parsed = parse_version(latest_ver)

    if curr_parsed is not None and lat_parsed is not None and curr_parsed >= lat_parsed:
        print(f"{label} — sei aggiornato ✅")
    else:
        print(f"{label} — è disponibile la versione {latest_ver}")
        print("Esegui 'rt -u' per aggiornare")
    if channel == STABLE:
        _print_beta_hint(project_root, max(filter(None, (curr_parsed, lat_parsed)), default=None))


def _print_beta_hint(project_root: str, newest_known) -> None:
    """Sul canale stabile segnala una beta più recente, senza installarla."""
    beta = get_latest_remote_version(project_root, channel=BETA)
    beta_parsed = parse_version(beta or "")
    if beta_parsed is None or not is_prerelease(beta):
        return
    if newest_known is None or beta_parsed > newest_known:
        print(f"🧪 È disponibile la beta {beta}: per provarla 'rt -u --beta' "
              "(per tornare alle versioni stabili 'rt -u --stable').")


def _is_update_excluded(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    top = parts[0]
    if top in ("config", ".venv", ".git", ".rt_telegram", ".agents", ".agent", ".claude"):
        return True
    if top == ".env" or top.startswith(".env."):
        return True
    if top == "install.log":
        return True
    if parts[:2] == ["rt", "spa"]:  # web app compilata: la installa rt.core.spa_release
        return True
    return False


def _is_managed_code(rel_path: str) -> bool:
    """Solo queste directory appartengono al distributore, mai i dati dell'utente."""
    return rel_path.replace("\\", "/").split("/")[0] in (
        "rt", "bin", "config.example", "docs",
    )


def _install_runtime_requirements(project_root: str) -> bool:
    """Installa le dipendenze nel venv di RT e rende visibile qualsiasi errore. Gradio
    (requirements-web.txt) serve solo a 'rt web --legacy' e non viene più installato."""
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


def _stop_services(project_root: str) -> List[str]:
    """Fase G: ferma i servizi launchd prima di sostituire il codice (ripartono dopo)."""
    try:
        from rt.services import service_manager as sm
        if sm.supported() and sm.installed():
            stopped = sm.stop()
            if stopped:
                print(f"⏸  Servizi fermati per l'aggiornamento: {', '.join(stopped)}")
            return stopped
    except Exception as exc:
        print(f"⚠️  Servizi non fermati: {exc}", file=sys.stderr)
    return []


def _post_update(project_root: str) -> bool:
    """Fase G: con il codice NUOVO (processo separato) completa l'aggiornamento: cartella dati
    (migrazione dalla 3.x), migrazioni del DB e import delle lezioni, segreti, servizi."""
    venv_python = os.path.join(project_root, ".venv", "bin", "python3")
    python = venv_python if os.path.isfile(venv_python) else sys.executable
    try:
        result = subprocess.run([python, os.path.join(project_root, "bin", "rt"), "data", "post-update"],
                                cwd=project_root, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"❌ Completamento dell'aggiornamento non riuscito: {exc}", file=sys.stderr)
        return False
    return result.returncode == 0


def run_update(project_root: str, channel: Optional[str] = None) -> int:
    """'rt -u' segue il canale salvato (stabile se mai scelto); 'rt -u --beta' e
    'rt -u --stable' cambiano canale in modo permanente e poi aggiornano."""
    if channel is not None:
        previous = get_update_channel()
        try:
            set_update_channel(channel)
        except OSError as exc:
            print(f"❌ Impossibile salvare il canale di aggiornamento: {exc}", file=sys.stderr)
            return 1
        if channel == BETA and previous != BETA:
            print("🧪 Canale beta attivo: 'rt -u' installerà anche le versioni di prova (beta). "
                  "Per tornare alle versioni stabili: 'rt -u --stable'.")
        elif channel == STABLE and previous != STABLE:
            print("✅ Canale stabile attivo: 'rt -u' installerà solo le versioni stabili.")
    if os.environ.get(OFFLINE_ENV) == "1":
        # riparazione senza rete (CI dell'installer): dipendenze, web app locale, dati e servizi
        _stop_services(project_root)
        ok = (_install_runtime_requirements(project_root)
              and update_spa(project_root, get_current_version(project_root))
              and _post_update(project_root))
        return 0 if ok else 1
    return _run_update(project_root, get_update_channel())


def _run_update(project_root: str, channel: str = STABLE) -> int:
    """
    Esegue l'aggiornamento automatico sicuro di RT tramite GitHub Releases:
    1. Verifica disponibilità di una versione più recente via API GitHub.
    2. Scarica il tarball sorgente in una directory temporanea (mai in project_root).
    3. Estrae l'archivio nella directory temporanea.
    4. Sincronizza il codice estratto dentro project_root preservando configurazioni utente.
    5. Pulisce la directory temporanea.
    6. Installa le dipendenze nel virtualenv e la web app compilata della release (rt/spa).
    7. Scrive VERSION solo dopo l'installazione riuscita.
    Restituisce il codice di uscita per la CLI (0 = ok o già aggiornato, 1 = errore).
    """
    git_checkout = os.path.exists(os.path.join(project_root, ".git"))
    if git_checkout and not _git_checkout_is_safe_to_update(project_root):
        return 1

    latest_ver = get_latest_remote_version(project_root, channel=channel)
    if latest_ver is None:
        print("❌ Impossibile verificare gli aggiornamenti remoti (errore di connessione).", file=sys.stderr)
        return 1
    if latest_ver == "":
        print("Nessuna versione pubblicata ancora sul repository.")
        return 0

    curr_ver = get_current_version(project_root)
    curr_parsed = parse_version(curr_ver)
    lat_parsed = parse_version(latest_ver)

    if curr_parsed is not None and lat_parsed is not None and curr_parsed >= lat_parsed:
        # stessa versione: 'rt -u' ripara (dipendenze, web app, dati, servizi)
        if curr_parsed == lat_parsed:
            _stop_services(project_root)
            if not (_install_runtime_requirements(project_root) and update_spa(project_root, latest_ver)
                    and _post_update(project_root)):
                return 1
            print(f"Sei già aggiornato all'ultima versione ({curr_ver}).")
        elif channel == STABLE and is_prerelease(curr_ver):
            # niente downgrade: la beta può aver già aggiornato il database a uno schema nuovo
            print(f"Hai la beta {curr_ver}, più recente dell'ultima versione stabile ({latest_ver}): "
                  "resta installata e 'rt -u' passerà alla prossima versione stabile appena esce.")
        else:
            print(f"Sei già aggiornato all'ultima versione ({curr_ver}).")
        return 0

    if is_prerelease(latest_ver):
        print(f"🧪 Versione beta {latest_ver}: è una versione di prova, può contenere errori.")
    _stop_services(project_root)
    if git_checkout:
        if not _update_git_checkout(project_root, latest_ver):
            return 1
        if not _install_runtime_requirements(project_root) or not update_spa(project_root, latest_ver):
            return 1
        if not _post_update(project_root):
            return 1
        print(f"✅ RT aggiornato: {curr_ver} → {latest_ver}")
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
        if not _install_runtime_requirements(project_root) or not update_spa(project_root, latest_ver):
            return 1
        new_version_src = os.path.join(extracted_root, "VERSION")
        if os.path.isfile(new_version_src):
            shutil.copy2(new_version_src, os.path.join(project_root, "VERSION"))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if not _post_update(project_root):
        return 1
    new_ver = get_current_version(project_root)
    print(f"✅ RT aggiornato: {curr_ver} → {new_ver}")
    return 0
