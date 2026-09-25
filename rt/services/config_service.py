"""
rt.services.config_service
Lettura, validazione e scrittura atomica della configurazione (config/general.yaml e file
per-job) e dei segreti, condivise dal wizard 'rt config' (rt/tui/configure) e dalle
impostazioni web (rt/web/settings.py). Riusa rt.core.config per la precedenza dei percorsi
e per la validazione.

I segreti passano da set_secret(), che per ora li scrive nel file .env come sempre (chmod
600): RT4-C1 lo sostituirà con un archivio cifrato senza toccare i chiamanti.
"""
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

PathLike = Union[str, Path]


def config_dir(project_root: Optional[PathLike] = None) -> Path:
    """Stessa precedenza di load_config(): config/ nella cwd, poi nel progetto."""
    from rt.core.config import _default_project_root
    local = Path.cwd() / "config"
    if local.is_dir():
        return local
    return Path(project_root or _default_project_root()) / "config"


def general_config_path(project_root: Optional[PathLike] = None) -> Path:
    return config_dir(project_root) / "general.yaml"


def env_path(project_root: Optional[PathLike] = None) -> Path:
    """Il file .env accanto alla cartella config/ in uso."""
    return config_dir(project_root).parent / ".env"


def job_config_paths(project_root: Optional[PathLike] = None) -> Dict[str, str]:
    """job -> percorso del suo file .yaml (in qualunque sottocartella di config/)."""
    from rt.core.config import find_job_yaml_paths
    return find_job_yaml_paths(str(config_dir(project_root)))


def read_yaml(path: PathLike) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configurazione non valida: {path.name}.")
    return data


def write_text_atomic(path: PathLike, content: str, mode: Optional[int] = None) -> None:
    """Scrive un file di testo in modo atomico (file temporaneo nella stessa cartella +
    os.replace), conservando i permessi del file esistente se mode non è indicato."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        if mode is not None:
            os.fchmod(fd, mode) if hasattr(os, "fchmod") else None
        elif path.exists() and hasattr(os, "fchmod"):
            os.fchmod(fd, path.stat().st_mode & 0o777)
        elif hasattr(os, "fchmod"):
            os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_yaml_atomic(path: PathLike, data: Dict[str, Any]) -> None:
    write_text_atomic(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def validate_config() -> List[str]:
    """Carica e valida la configurazione in uso. Ritorna l'elenco degli errori (vuoto se ok)."""
    from pydantic import ValidationError
    from rt.core.config import load_config
    try:
        load_config()
    except ValidationError as exc:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    return []


def validate_secret(secret: str) -> None:
    if not secret or any(char in secret for char in "\r\n\0"):
        raise ValueError("La chiave non può essere vuota o contenere interruzioni di riga.")


def set_env_var(path: PathLike, key: str, value: str, quote: bool = False) -> None:
    """Aggiorna o aggiunge KEY=valore in un file .env preservando le altre righe (e il
    prefisso 'export'), in modo atomico e con permessi 600; aggiorna anche os.environ.
    quote=True scrive il valore come stringa JSON tra virgolette."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    encoded = json.dumps(value, ensure_ascii=False) if quote else value
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    found = False
    updated = []
    for line in lines:
        m = pattern.match(line)
        if m:
            updated.append(f"{m.group(1) or ''}{key}={encoded}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"{key}={encoded}")
    write_text_atomic(path, "\n".join(updated) + "\n", mode=0o600)
    os.environ[key] = value


def set_secret(name: str, value: str, project_root: Optional[PathLike] = None, path: Optional[PathLike] = None) -> None:
    """Salva un segreto (chiave API, token). Oggi: variabile nel file .env."""
    validate_secret(value)
    set_env_var(path or env_path(project_root), name, value, quote=True)
