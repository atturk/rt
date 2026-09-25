"""
rt.security.secrets
Archivio dei segreti (chiavi API, token Telegram) con cifratura a riposo (RT4-C1).

Porta SecretStore (get, set, delete, list_names) con due implementazioni:
- EnvSecretStore: comportamento storico, sola lettura da os.environ (già popolato da .env).
- EncryptedFileSecretStore: config/secrets.enc, JSON cifrato con Fernet (AES-128-CBC +
  HMAC-SHA256), permessi 600, scrittura atomica. Più chiavi master (separate da virgola, la
  prima è quella attiva) vengono lette con MultiFernet, così la rotazione non perde nulla.
  Una futura DbSecretStore (fase B) implementerà la stessa porta.

Chiave master, in ordine: variabile RT_MASTER_KEY, portachiavi di sistema via keyring
(servizio "rt", voce "master_key"), altrimenti SecretStoreError con le istruzioni.

Priorità di risoluzione di un segreto: variabile d'ambiente esplicita > store cifrato > .env
(deprecato quando lo store esiste). apply_to_environ() riversa lo store in os.environ senza
scavalcare i valori impostati a mano nell'ambiente: il resto del codice continua a leggere
os.environ come prima. Senza secrets.enc non succede nulla: tutto funziona come oggi.

Nessun valore di un segreto compare in messaggi d'errore, log o repr.
"""
import base64
import json
import logging
import os
import tempfile
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

MASTER_KEY_ENV = "RT_MASTER_KEY"
SECRETS_FILE_ENV = "RT_SECRETS_FILE"
KEYRING_SERVICE = "rt"
KEYRING_USERNAME = "master_key"
SECRETS_FILENAME = "secrets.enc"
FILE_FORMAT_VERSION = 1

# Segreti che non passano da 'credentials:' in config/general.yaml ma vanno comunque trattati
# come tali (migrazione, redazione).
EXTRA_SECRET_NAMES = ("RT_TELEGRAM_BOT_TOKEN", "RT_STT_API_KEY")


class SecretStoreError(Exception):
    """Errore dell'archivio segreti. Il messaggio non contiene mai valori di segreti."""


class SecretStore(ABC):
    """Porta comune a tutte le sorgenti di segreti."""

    read_only: bool = False

    @abstractmethod
    def get(self, name: str) -> Optional[str]:
        ...

    @abstractmethod
    def set(self, name: str, value: str) -> None:
        ...

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Rimuove il segreto; True se esisteva."""

    @abstractmethod
    def list_names(self) -> List[str]:
        ...

    def metadata(self) -> Dict[str, Dict[str, str]]:
        """Metadati non segreti per nome (es. updated_at). Mai i valori."""
        return {name: {} for name in self.list_names()}


class EnvSecretStore(SecretStore):
    """Sola lettura da os.environ (dove load_env_file ha già caricato .env)."""

    read_only = True

    def get(self, name: str) -> Optional[str]:
        val = os.environ.get(name)
        return val.strip() if val and val.strip() else None

    def set(self, name: str, value: str) -> None:
        raise SecretStoreError("EnvSecretStore è in sola lettura: usa 'rt secrets set' o il file .env.")

    def delete(self, name: str) -> bool:
        raise SecretStoreError("EnvSecretStore è in sola lettura.")

    def list_names(self) -> List[str]:
        return sorted(os.environ)


# ---------------------------------------------------------------------------
# Chiave master
# ---------------------------------------------------------------------------

def generate_master_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")


def _split_keys(raw: str) -> List[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def validate_master_key(raw: str) -> List[str]:
    """Controlla il formato (una o più chiavi Fernet separate da virgola) senza mai citarne il valore."""
    keys = _split_keys(raw or "")
    if not keys:
        raise SecretStoreError("Chiave master vuota.")
    for i, key in enumerate(keys, 1):
        try:
            decoded = base64.urlsafe_b64decode(key.encode("ascii"))
        except Exception:
            decoded = b""
        if len(decoded) != 32:
            raise SecretStoreError(
                f"Chiave master non valida (chiave n. {i}): serve una chiave Fernet, "
                "cioè 32 byte in base64 url-safe, come quella generata da 'rt secrets init'."
            )
    return keys


def keyring_get_master_key() -> Optional[str]:
    """Legge la chiave dal portachiavi di sistema; None se keyring manca o non ha la voce."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or None
    except Exception as exc:  # nessun backend, portachiavi bloccato, pacchetto assente
        logger.debug("Portachiavi non disponibile: %s", type(exc).__name__)
        return None


def keyring_set_master_key(value: str) -> None:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)
    except Exception as exc:
        raise SecretStoreError(
            f"Impossibile salvare la chiave master nel portachiavi di sistema ({type(exc).__name__}). "
            f"Usa la variabile {MASTER_KEY_ENV}."
        ) from None


def resolve_master_key() -> Optional[str]:
    """RT_MASTER_KEY, poi portachiavi. None se nessuna delle due è impostata."""
    env_val = os.environ.get(MASTER_KEY_ENV, "").strip()
    if env_val:
        return env_val
    return keyring_get_master_key()


def _missing_key_message(path: Path) -> str:
    return (
        f"Trovato l'archivio segreti cifrato {path} ma nessuna chiave master: imposta la variabile "
        f"{MASTER_KEY_ENV} oppure salva la chiave nel portachiavi di sistema (servizio "
        f"'{KEYRING_SERVICE}', voce '{KEYRING_USERNAME}'). Se la chiave è persa, sposta il file "
        "e reinserisci le chiavi con 'rt secrets set'."
    )


# ---------------------------------------------------------------------------
# Archivio cifrato su file
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class EncryptedFileSecretStore(SecretStore):
    """Segreti in un file JSON cifrato. La chiave master si risolve solo quando serve."""

    def __init__(self, path: PathLike, master_key: Optional[str] = None):
        self.path = Path(path)
        self._master_key = master_key

    def __repr__(self) -> str:
        return f"EncryptedFileSecretStore(path={str(self.path)!r})"

    # -- chiave -----------------------------------------------------------
    def _fernet(self):
        from cryptography.fernet import Fernet, MultiFernet
        raw = self._master_key or resolve_master_key()
        if not raw:
            raise SecretStoreError(_missing_key_message(self.path))
        keys = validate_master_key(raw)
        return MultiFernet([Fernet(k.encode("ascii")) for k in keys])

    # -- lettura/scrittura del file ---------------------------------------
    def exists(self) -> bool:
        return self.path.is_file()

    def _load(self) -> Dict[str, Dict[str, str]]:
        if not self.exists():
            return {}
        from cryptography.fernet import InvalidToken
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            token = envelope["token"]
            if envelope.get("version") != FILE_FORMAT_VERSION or not isinstance(token, str):
                raise ValueError
        except Exception:
            raise SecretStoreError(
                f"Archivio segreti {self.path} illeggibile o danneggiato. Ripristina un backup "
                "oppure spostalo e reinserisci le chiavi con 'rt secrets set'."
            ) from None
        fernet = self._fernet()
        try:
            plain = fernet.decrypt(token.encode("ascii"))
        except InvalidToken:
            raise SecretStoreError(
                f"Impossibile decifrare {self.path}: la chiave master non è quella giusta "
                "oppure il file è stato alterato."
            ) from None
        try:
            data = json.loads(plain.decode("utf-8"))
            secrets = data["secrets"]
            if not isinstance(secrets, dict):
                raise ValueError
        except Exception:
            raise SecretStoreError(f"Archivio segreti {self.path} decifrato ma con contenuto non valido.") from None
        return {str(k): dict(v) for k, v in secrets.items() if isinstance(v, dict) and isinstance(v.get("value"), str)}

    def _save(self, secrets: Dict[str, Dict[str, str]], fernet=None) -> None:
        fernet = fernet or self._fernet()
        plain = json.dumps({"secrets": secrets}, sort_keys=True).encode("utf-8")
        token = fernet.encrypt(plain).decode("ascii")
        envelope = {"version": FILE_FORMAT_VERSION, "cipher": "fernet", "token": token}
        _write_atomic(self.path, (json.dumps(envelope, indent=2) + "\n").encode("utf-8"))
        _invalidate_cache()

    def initialize(self) -> None:
        """Crea un archivio vuoto (cifrato con la chiave corrente) se non esiste."""
        if not self.exists():
            self._save({})

    # -- porta SecretStore -------------------------------------------------
    def get(self, name: str) -> Optional[str]:
        entry = self._load().get(name)
        return entry["value"] if entry else None

    def get_all(self) -> Dict[str, str]:
        return {name: entry["value"] for name, entry in self._load().items()}

    def set(self, name: str, value: str) -> None:
        if not name or not name.strip():
            raise SecretStoreError("Nome del segreto vuoto.")
        if value is None or not str(value).strip():
            raise SecretStoreError(f"Valore vuoto per {name}.")
        secrets = self._load()
        secrets[name.strip()] = {"value": str(value).strip(), "updated_at": _now_iso()}
        self._save(secrets)

    def delete(self, name: str) -> bool:
        secrets = self._load()
        if name not in secrets:
            return False
        del secrets[name]
        self._save(secrets)
        return True

    def list_names(self) -> List[str]:
        return sorted(self._load())

    def metadata(self) -> Dict[str, Dict[str, str]]:
        return {name: {"updated_at": entry.get("updated_at", "")} for name, entry in sorted(self._load().items())}

    def rotate(self, new_key: str) -> None:
        """Ricifra con new_key. La chiave attuale deve essere ancora risolvibile."""
        from cryptography.fernet import Fernet, MultiFernet
        new_keys = validate_master_key(new_key)
        secrets = self._load()  # con la chiave vecchia
        self._save(secrets, fernet=MultiFernet([Fernet(k.encode("ascii")) for k in new_keys]))
        self._master_key = new_key


# ---------------------------------------------------------------------------
# Posizione dell'archivio e integrazione con os.environ
# ---------------------------------------------------------------------------

def default_store_path(project_root: Optional[PathLike] = None) -> Path:
    """RT_SECRETS_FILE, altrimenti secrets.enc nella cartella config/ in uso (stessa precedenza
    di load_config: config/ nella cwd, poi nella project root)."""
    explicit = os.environ.get(SECRETS_FILE_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    local = Path.cwd() / "config"
    if local.is_dir():
        return local / SECRETS_FILENAME
    if project_root is None:
        from rt.core.config import _default_project_root
        project_root = _default_project_root()
    return Path(project_root) / "config" / SECRETS_FILENAME


def store_path_for_env_file(env_file: PathLike) -> Path:
    """Archivio che accompagna un file .env: <cartella del .env>/config/secrets.enc
    (RT_SECRETS_FILE ha sempre la precedenza)."""
    explicit = os.environ.get(SECRETS_FILE_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path(env_file).parent / "config" / SECRETS_FILENAME


def is_initialized(project_root: Optional[PathLike] = None) -> bool:
    return default_store_path(project_root).is_file()


_lock = threading.RLock()
_cache: Dict[str, object] = {}          # path -> (mtime_ns, size, {name: value})
_injected: Dict[str, str] = {}          # nomi messi in os.environ dallo store
_warned: set = set()


def _invalidate_cache() -> None:
    with _lock:
        _cache.clear()


def _read_cached(store: EncryptedFileSecretStore) -> Dict[str, str]:
    st = store.path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    key = str(store.path.resolve())
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    values = store.get_all()
    with _lock:
        _cache[key] = (stamp, values)
    return values


def _warn_once(key: str, message: str) -> None:
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message)


def apply_to_environ(dotenv_values: Optional[Dict[str, Optional[str]]] = None,
                     project_root: Optional[PathLike] = None) -> None:
    """Riversa i segreti dello store cifrato in os.environ.

    Un nome viene scritto solo se in os.environ manca, oppure contiene il valore arrivato da
    .env, oppure quello già messo dallo store: così una variabile esportata a mano vince sempre
    (priorità: ambiente esplicito > store > .env). Senza secrets.enc non fa nulla. Se il file
    esiste ma non si può leggere, avvisa una volta e lascia l'ambiente com'è (.env resta attivo).
    """
    path = default_store_path(project_root)
    if not path.is_file():
        return
    try:
        values = _read_cached(EncryptedFileSecretStore(path))
    except SecretStoreError as exc:
        _warn_once(f"load:{path}", f"Segreti cifrati non caricati: {exc}")
        return
    dotenv_values = dotenv_values or {}
    with _lock:
        for name, value in values.items():
            current = os.environ.get(name)
            if current is None or current == dotenv_values.get(name) or current == _injected.get(name):
                os.environ[name] = value
                _injected[name] = value
        for name, value in dotenv_values.items():
            if value and name not in values and _is_known_secret_name(name) and os.environ.get(name) == value:
                _warn_once(
                    f"dotenv:{name}",
                    f"{name} è ancora in chiaro nel file .env: spostalo nell'archivio cifrato con "
                    "'rt secrets migrate'.",
                )


def _is_known_secret_name(name: str) -> bool:
    if name in EXTRA_SECRET_NAMES:
        return True
    try:
        from rt.llm.credentials import GLOBAL_CREDENTIALS
        return name in GLOBAL_CREDENTIALS.registered_env_vars()
    except Exception:
        return False


def injected_secret_values() -> List[str]:
    """Valori caricati dallo store cifrato, per la redazione in sanitize_secrets."""
    with _lock:
        return list(_injected.values())


def source_of(name: str) -> str:
    """'store' se il valore corrente di os.environ[name] viene dallo store, altrimenti 'env'."""
    with _lock:
        injected = _injected.get(name)
    if injected is not None and os.environ.get(name) == injected:
        return "store"
    return "env" if name in os.environ else "missing"


def _reset_for_tests() -> None:
    with _lock:
        _cache.clear()
        _injected.clear()
        _warned.clear()
