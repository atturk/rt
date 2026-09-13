"""
Gestione della versione e dell'aggiornamento automatico di RT.
Tutte le operazioni git sono incapsulate ed eseguite rispetto alla project_root.
L'utente finale non vede comandi o terminologia git grezza.
"""
import os
import re
import subprocess
import sys
from typing import Optional, Tuple, List


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
    Esegue `git describe --tags --abbrev=0` per ottenere il tag più recente su HEAD.
    Se non ci sono tag o git fallisce, ritorna 'sconosciuta'.
    """
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return format_version(res.stdout.strip())
        return "sconosciuta"
    except (subprocess.SubprocessError, OSError):
        return "sconosciuta"


def get_latest_remote_version(project_root: str, timeout: float = 5.0) -> Optional[str]:
    """
    Esegue `git ls-remote --tags origin` per elencare i tag disponibili sul remote,
    estrae e ordina semanticamente le versioni, e ritorna la più recente (es. '2.4.0').
    Ritorna None in caso di offline, errore o timeout. Ritorna stringa vuota "" (non None)
    se il comando riesce ma il remote non ha ancora nessun tag pubblicato: è uno stato
    diverso da un problema di connessione e va comunicato diversamente all'utente.
    """
    try:
        res = subprocess.run(
            ["git", "ls-remote", "--tags", "origin"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if res.returncode != 0:
            return None

        candidates: List[Tuple[Tuple[int, int, int], str]] = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            ref = parts[1]
            if not ref.startswith("refs/tags/"):
                continue
            tag = ref[len("refs/tags/"):]
            if tag.endswith("^{}"):
                tag = tag[:-3]

            parsed = parse_semver(tag)
            if parsed is not None:
                candidates.append((parsed, format_version(tag)))

        if not candidates:
            return ""

        candidates.sort(key=lambda x: x[0])
        return candidates[-1][1]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
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


def run_update(project_root: str) -> None:
    """
    Esegue l'aggiornamento automatico sicuro di RT:
    1. Verifica assenza modifiche locali non salvate
    2. Verifica branch main
    3. Recupera aggiornamenti (fetch)
    4. Confronta HEAD con origin/main
    5. Fast-forward merge se disponibile
    6. Re-installa requirements.txt nel virtualenv
    7. Mostra versione aggiornata
    """
    # 1. Verifica modifiche locali non salvate su file tracciati
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print("❌ Errore durante il controllo dello stato locale.", file=sys.stderr)
            sys.exit(1)
        if res.stdout.strip():
            print("⚠️ Ci sono modifiche locali non salvate nel codice, impossibile aggiornare in sicurezza.")
            sys.exit(1)
    except (subprocess.SubprocessError, OSError):
        print("❌ Errore durante l'esecuzione dei comandi di controllo locale.", file=sys.stderr)
        sys.exit(1)

    # 2. Verifica di essere sul branch main
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        current_branch = res.stdout.strip()
        if res.returncode != 0 or current_branch != "main":
            print("⚠️ Non sei sul branch 'main', impossibile aggiornare automaticamente.")
            sys.exit(1)
    except (subprocess.SubprocessError, OSError):
        print("❌ Impossibile determinare il branch corrente.", file=sys.stderr)
        sys.exit(1)

    # 3. git fetch origin
    try:
        res = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print("❌ Impossibile verificare gli aggiornamenti remoti (errore di connessione a origin).", file=sys.stderr)
            sys.exit(1)
    except (subprocess.SubprocessError, OSError):
        print("❌ Impossibile verificare gli aggiornamenti remoti (errore di connessione a origin).", file=sys.stderr)
        sys.exit(1)

    # 4. Confronta HEAD con origin/main
    try:
        res_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        res_remote = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_head.returncode != 0 or res_remote.returncode != 0:
            print("❌ Impossibile confrontare lo stato locale con origin/main.", file=sys.stderr)
            sys.exit(1)

        head_sha = res_head.stdout.strip()
        remote_sha = res_remote.stdout.strip()

        if head_sha == remote_sha:
            curr_ver = get_current_version(project_root)
            print(f"Sei già aggiornato all'ultima versione ({curr_ver}).")
            sys.exit(0)
    except (subprocess.SubprocessError, OSError):
        print("❌ Errore durante il confronto delle versioni.", file=sys.stderr)
        sys.exit(1)

    # 5. Se origin/main è avanti, fast-forward merge
    old_ver = get_current_version(project_root)
    print("Aggiornamento in corso...")
    try:
        res_merge = subprocess.run(
            ["git", "merge", "--ff-only", "origin/main"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_merge.returncode != 0:
            print(
                "❌ Impossibile completare l'aggiornamento automatico (la cronologia locale diverge da origin/main).\n"
                "Contatta chi mantiene il progetto per assistenza.",
                file=sys.stderr,
            )
            sys.exit(1)
    except (subprocess.SubprocessError, OSError):
        print("❌ Impossibile completare l'aggiornamento automatico. Contatta chi mantiene il progetto per assistenza.", file=sys.stderr)
        sys.exit(1)

    # 6. Reinstalla le dipendenze nel venv
    venv_python = os.path.join(project_root, ".venv", "bin", "python3")
    py_exec = venv_python if os.path.isfile(venv_python) else sys.executable
    req_file = os.path.join(project_root, "requirements.txt")
    if os.path.isfile(req_file):
        try:
            subprocess.run(
                [py_exec, "-m", "pip", "install", "-r", req_file, "--quiet"],
                cwd=project_root,
                capture_output=True,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            pass

    # 7. Ricalcola versione e stampa esito
    new_ver = get_current_version(project_root)
    print(f"✅ RT aggiornato: {old_ver} → {new_ver}")
    sys.exit(0)
