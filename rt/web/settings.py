"""Impostazioni minime della web app, salvate senza riscrivere il resto del YAML."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

import yaml


def general_config_path(project_root: Path) -> Path:
    """Usa la stessa precedenza di load_config(): config/ nella cwd, poi nel progetto."""
    local = Path.cwd() / "config"
    return (local if local.is_dir() else project_root / "config") / "general.yaml"


def save_lessons_root(raw_path: str, project_root: Path) -> str:
    """Imposta solo telegram.lessons_root e crea la cartella se necessario."""
    if not raw_path or not raw_path.strip():
        raise ValueError("Inserisci il percorso della cartella delle lezioni.")
    entered = Path(raw_path.strip()).expanduser()
    if not entered.is_absolute():
        raise ValueError("Usa un percorso assoluto, per esempio ~/RT Lezioni.")
    root = entered.resolve()
    project = project_root.resolve()
    if root == project or root.is_relative_to(project):
        raise ValueError("Scegli una cartella fuori dall'installazione di RT.")
    if root.exists() and not root.is_dir():
        raise ValueError("Il percorso indicato è un file, non una cartella.")

    config_path = general_config_path(project_root)
    original = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    try:
        data = yaml.safe_load(original) if original.strip() else {}
    except yaml.YAMLError as exc:
        raise ValueError("config/general.yaml contiene YAML non valido.") from exc
    if not isinstance(data, dict):
        raise ValueError("config/general.yaml non contiene una mappa YAML valida.")
    telegram = data.get("telegram")
    if telegram is not None and not isinstance(telegram, dict):
        raise ValueError("La sezione telegram di config/general.yaml non è modificabile dalla web app.")

    lines = original.splitlines(keepends=True)
    scalar = json.dumps(str(root), ensure_ascii=False)
    heading = next((i for i, line in enumerate(lines)
                    if re.match(r"^telegram:[ \t]*(?:#.*)?(?:\r?\n)?$", line)), None)
    if heading is None:
        if "telegram" in data:
            raise ValueError("La sezione telegram usa un formato non modificabile dalla web app.")
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.extend(["\ntelegram:\n", f"  lessons_root: {scalar}\n"])
    else:
        end = next((i for i in range(heading + 1, len(lines))
                    if re.match(r"^[A-Za-z_][\w-]*[ \t]*:", lines[i])), len(lines))
        field = next((i for i in range(heading + 1, end)
                      if re.match(r"^[ \t]+lessons_root[ \t]*:", lines[i])), None)
        if field is None:
            lines.insert(end, f"  lessons_root: {scalar}\n")
        else:
            indent = re.match(r"^([ \t]+)", lines[field]).group(1)
            lines[field] = f"{indent}lessons_root: {scalar}\n"

    updated = "".join(lines)
    try:
        parsed = yaml.safe_load(updated)
    except yaml.YAMLError as exc:
        raise ValueError("Impossibile verificare il file di configurazione aggiornato.") from exc
    if parsed.get("telegram", {}).get("lessons_root") != str(root):
        raise ValueError("Impossibile verificare la nuova cartella nel file di configurazione.")

    root.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".general-", suffix=".yaml", dir=config_path.parent)
    try:
        if config_path.exists():
            os.fchmod(fd, config_path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(root)
