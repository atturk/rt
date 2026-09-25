"""
rt.services.secrets_service
Gestione dell'archivio segreti cifrato (RT4-C2), condivisa da 'rt secrets', dal wizard
'rt config' e dalle impostazioni web. Nessun input(): le conferme le chiede l'adattatore
(rt/cli.py). Nessuna funzione restituisce o stampa valori di segreti, salvo la chiave master
appena generata, che init_store restituisce una sola volta perché l'utente la conservi.
"""
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from rt.security.secrets import (
    EXTRA_SECRET_NAMES,
    MASTER_KEY_ENV,
    EncryptedFileSecretStore,
    SecretStoreError,
    default_store_path,
    generate_master_key,
    keyring_get_master_key,
    keyring_set_master_key,
    resolve_master_key,
)

PathLike = Union[str, Path]


@dataclass
class InitResult:
    path: Path
    key_in_keyring: bool
    # Valorizzata solo se la chiave non è finita nel portachiavi o se è stata chiesta la stampa:
    # va mostrata una volta e poi dimenticata.
    master_key_to_show: Optional[str] = None


@dataclass
class MigrationPlan:
    env_path: Path
    to_store: List[str] = field(default_factory=list)       # da scrivere nello store
    already_stored: List[str] = field(default_factory=list)  # stesso valore già nello store
    conflicts: List[str] = field(default_factory=list)       # valore diverso: vince lo store

    @property
    def removable(self) -> List[str]:
        return self.to_store + self.already_stored + self.conflicts


@dataclass
class MigrationResult:
    plan: MigrationPlan
    backup_path: Optional[Path] = None
    stripped: List[str] = field(default_factory=list)


def store(path: Optional[PathLike] = None) -> EncryptedFileSecretStore:
    return EncryptedFileSecretStore(Path(path) if path else default_store_path())


def is_ready(path: Optional[PathLike] = None) -> bool:
    """True se l'archivio esiste e la chiave master è disponibile."""
    s = store(path)
    return s.exists() and bool(resolve_master_key())


def init_store(path: Optional[PathLike] = None, use_keyring: bool = True, show_key: bool = False) -> InitResult:
    """Genera la chiave master, la salva nel portachiavi (se possibile) e crea un archivio vuoto.

    Se RT_MASTER_KEY è già impostata la riusa (nessuna chiave nuova da mostrare)."""
    s = store(path)
    if s.exists():
        raise SecretStoreError(f"L'archivio {s.path} esiste già: usa 'rt secrets rotate' per cambiare chiave.")
    existing = os.environ.get(MASTER_KEY_ENV, "").strip()
    if existing:
        s = EncryptedFileSecretStore(s.path, master_key=existing)
        s.initialize()
        return InitResult(path=s.path, key_in_keyring=False)
    key = generate_master_key()
    in_keyring = False
    if use_keyring:
        try:
            keyring_set_master_key(key)
            in_keyring = keyring_get_master_key() == key
        except SecretStoreError:
            in_keyring = False
    s = EncryptedFileSecretStore(s.path, master_key=key)
    s.initialize()
    return InitResult(path=s.path, key_in_keyring=in_keyring,
                      master_key_to_show=key if (show_key or not in_keyring) else None)


def rotate_key(path: Optional[PathLike] = None, use_keyring: Optional[bool] = None) -> InitResult:
    """Ricifra l'archivio con una chiave nuova.

    Con il portachiavi: salva prima "nuova,vecchia" (così un'interruzione non rende illeggibile
    nulla), ricifra, poi lascia solo la nuova. Con RT_MASTER_KEY la chiave nuova va mostrata e
    l'utente deve aggiornare la variabile."""
    s = store(path)
    if not s.exists():
        raise SecretStoreError(f"Nessun archivio in {s.path}: esegui prima 'rt secrets init'.")
    old = resolve_master_key()
    if not old:
        raise SecretStoreError("Chiave master attuale non disponibile: impossibile ricifrare.")
    from_env = bool(os.environ.get(MASTER_KEY_ENV, "").strip())
    if use_keyring is None:
        use_keyring = not from_env
    new = generate_master_key()
    if use_keyring:
        keyring_set_master_key(f"{new},{old}")
    s = EncryptedFileSecretStore(s.path, master_key=old)
    before = s.get_all()
    s.rotate(new)
    if EncryptedFileSecretStore(s.path, master_key=new).get_all() != before:
        raise SecretStoreError("Verifica dopo la rotazione fallita: la chiave vecchia resta valida.")
    if use_keyring:
        keyring_set_master_key(new)
        return InitResult(path=s.path, key_in_keyring=True)
    return InitResult(path=s.path, key_in_keyring=False, master_key_to_show=new)


def list_secrets(path: Optional[PathLike] = None) -> Dict[str, Dict[str, str]]:
    """Nomi e data di modifica, mai valori."""
    return store(path).metadata()


def set_secret(name: str, value: str, path: Optional[PathLike] = None) -> None:
    s = store(path)
    if not s.exists():
        raise SecretStoreError("Archivio non inizializzato: esegui prima 'rt secrets init'.")
    s.set(name, value)
    os.environ[name] = value.strip()


def unset_secret(name: str, path: Optional[PathLike] = None) -> bool:
    removed = store(path).delete(name)
    if removed:
        from rt.security.secrets import source_of
        if source_of(name) == "store":
            os.environ.pop(name, None)
    return removed


# ---------------------------------------------------------------------------
# Migrazione da .env
# ---------------------------------------------------------------------------

def secret_names_from_config(general_yaml: Optional[PathLike] = None) -> List[str]:
    """Variabili dichiarate in 'credentials:' di general.yaml + token Telegram e chiave STT."""
    import yaml
    from rt.services.config_service import general_config_path
    names = list(EXTRA_SECRET_NAMES)
    path = Path(general_yaml) if general_yaml else general_config_path()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    for cred in data.get("credentials") or []:
        if isinstance(cred, dict) and cred.get("env_var"):
            env_var = str(cred["env_var"]).strip()
            if env_var and env_var not in names:
                names.append(env_var)
    return names


def plan_migration(env_path: PathLike, names: List[str], path: Optional[PathLike] = None) -> MigrationPlan:
    from dotenv import dotenv_values
    env_path = Path(env_path)
    plan = MigrationPlan(env_path=env_path)
    values = dotenv_values(env_path) if env_path.is_file() else {}
    stored = store(path).get_all()
    for name in names:
        val = (values.get(name) or "").strip()
        if not val:
            continue
        if name not in stored:
            plan.to_store.append(name)
        elif stored[name] == val:
            plan.already_stored.append(name)
        else:
            plan.conflicts.append(name)
    return plan


def migrate_env(env_path: PathLike, names: List[str], strip_env: bool,
                path: Optional[PathLike] = None, now: Optional[datetime] = None) -> MigrationResult:
    """Copia i segreti da .env allo store; se strip_env li toglie da .env.

    Idempotente e senza perdite: scrive nello store, rilegge l'archivio con un'istanza nuova e
    confronta ogni valore; solo dopo crea il backup .env.bak-<data> (600) e riscrive .env."""
    from dotenv import dotenv_values
    s = store(path)
    if not s.exists():
        raise SecretStoreError("Archivio non inizializzato: esegui prima 'rt secrets init'.")
    env_path = Path(env_path)
    plan = plan_migration(env_path, names, path)
    values = dotenv_values(env_path) if env_path.is_file() else {}
    for name in plan.to_store:
        s.set(name, values[name].strip())

    reread = EncryptedFileSecretStore(s.path).get_all()
    for name in plan.to_store + plan.already_stored:
        if reread.get(name) != (values.get(name) or "").strip():
            raise SecretStoreError(f"Verifica fallita per {name}: .env lasciato intatto.")
    for name in plan.conflicts:
        if not reread.get(name):
            raise SecretStoreError(f"Verifica fallita per {name}: .env lasciato intatto.")

    result = MigrationResult(plan=plan)
    if not strip_env or not plan.removable:
        return result
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = env_path.with_name(f"{env_path.name}.bak-{stamp}")
    shutil.copy2(env_path, backup)
    os.chmod(backup, 0o600)
    result.backup_path = backup
    result.stripped = _strip_env_vars(env_path, plan.removable)
    return result


def _strip_env_vars(env_path: Path, names: List[str]) -> List[str]:
    import re
    from rt.services.config_service import write_text_atomic
    patterns = {n: re.compile(rf"^\s*(export\s+)?{re.escape(n)}\s*=") for n in names}
    kept, removed = [], []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        hit = next((n for n, p in patterns.items() if p.match(line)), None)
        if hit:
            removed.append(hit)
        else:
            kept.append(line)
    write_text_atomic(env_path, "\n".join(kept) + ("\n" if kept else ""), mode=0o600)
    return removed


def env_needs_migration(env_path: PathLike, general_yaml: Optional[PathLike] = None) -> bool:
    """True se .env contiene segreti noti e l'archivio cifrato non esiste ancora."""
    from dotenv import dotenv_values
    env_path = Path(env_path)
    if store().exists() or not env_path.is_file():
        return False
    values = dotenv_values(env_path)
    for name in secret_names_from_config(general_yaml):
        val = (values.get(name) or "").strip()
        if val and not _looks_like_placeholder(val):
            return True
    return False


def _looks_like_placeholder(value: str) -> bool:
    """I valori di esempio di .env.example (your_api_key_here, 123456:ABC-your-bot-token)."""
    return "your" in value.lower() or len(value) < 8
