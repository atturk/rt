"""
rt.services.backup_service
'rt backup' e 'rt restore' (RT4-G1). Il backup è l'unica copia completa dei dati: dalla fase
L le lezioni vivono nel database (testi) e in media/ (audio e immagini), non più in cartelle
da copiare a mano.

Una cartella di backup (default <cartella dati>/backups, meglio un disco esterno con --dest):

    <dest>/media-store/<aa>/<sha256>     contenuto dei media, uno per hash: i backup
                                         successivi copiano solo i file nuovi (incrementale)
    <dest>/rt-backup-<data>/
        manifest.json                     versione, data, elenco media (percorso → hash)
        rt.db | rt.pgdump                 DB (API di backup di SQLite, copia coerente anche
                                          con RT in funzione; pg_dump per Postgres)
        config/                           YAML e secrets.enc (cifrato)
        env                               il file .env
        telegram-state/                   stato del bot (se c'è)

La chiave master che decifra secrets.enc NON è nel backup (sta nel portachiavi o in
RT_MASTER_KEY): va salvata a parte, altrimenti dopo un ripristino chiavi e token sono persi.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from rt.core import paths

BACKUP_PREFIX = "rt-backup-"
MANIFEST = "manifest.json"
STORE = "media-store"
FORMAT = 1


class BackupError(RuntimeError):
    pass


@dataclass
class BackupResult:
    path: str
    media_total: int = 0
    media_copied: int = 0
    bytes_copied: int = 0
    missing: List[str] = field(default_factory=list)
    folder_lessons: List[str] = field(default_factory=list)
    master_key_warning: Optional[str] = None


def default_dest() -> str:
    return os.environ.get("RT_BACKUP_DIR") or os.path.join(paths.data_dir(), "backups")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _store_path(dest: str, sha: str) -> str:
    return os.path.join(dest, STORE, sha[:2], sha)


def _copy_atomic(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


# ---------------------------------------------------------------- inventario dei media

def media_inventory(db) -> Dict[str, Dict[str, object]]:
    """media_path → {sha256, size} per i media referenziati nel DB (lesson_files)."""
    from sqlalchemy import select
    from rt.db.models import LessonFile
    from rt.db.session import read_scope
    out: Dict[str, Dict[str, object]] = {}
    with read_scope(db) as s:
        for media_path, sha, size in s.execute(
                select(LessonFile.media_path, LessonFile.sha256, LessonFile.size)
                .where(LessonFile.media_path.is_not(None))):
            out[media_path] = {"sha256": sha or "", "size": int(size or 0)}
    return out


def verify_media(db, media_dir: str, deep: bool = False) -> List[str]:
    """Media referenziati nel DB che mancano in media/ (o, con deep, con hash diverso)."""
    problems = []
    for rel, info in sorted(media_inventory(db).items()):
        path = os.path.join(media_dir, rel)
        if not os.path.isfile(path):
            problems.append(f"{rel}: file mancante")
        elif deep and info["sha256"] and sha256_file(path) != info["sha256"]:
            problems.append(f"{rel}: contenuto diverso da quello registrato")
    return problems


def _folder_lessons(db) -> List[str]:
    from sqlalchemy import select
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    with read_scope(db) as s:
        return sorted(p for p, st in s.execute(select(Lesson.path, Lesson.storage)) if st != "db")


# ---------------------------------------------------------------- backup

def create_backup(dest: Optional[str] = None, say: Callable[[str], None] = print,
                  allow_missing: bool = False) -> BackupResult:
    from rt.db.engine import require_database, sqlite_file
    from rt.storage import fs

    db = require_database()
    dest = os.path.abspath(os.path.expanduser(dest or default_dest()))
    media_dir = fs.media_dir(db)
    inventory = media_inventory(db)
    missing = [rel for rel in sorted(inventory) if not os.path.isfile(os.path.join(media_dir, rel))]
    if missing and not allow_missing:
        raise BackupError(f"{len(missing)} media referenziati nel database mancano in {media_dir} "
                          f"(es. {missing[0]}). Controlla con 'rt doctor'; per salvare comunque il "
                          "resto usa --allow-missing.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snap = os.path.join(dest, BACKUP_PREFIX + stamp)
    if os.path.exists(snap):
        raise BackupError(f"Esiste già {snap}: riprova tra un secondo.")
    tmp_snap = snap + ".partial"
    os.makedirs(tmp_snap)
    result = BackupResult(path=snap, missing=missing)
    try:
        # 1. database
        db_file = sqlite_file(db.url)
        if db_file:
            from rt.services.data_service import sqlite_copy
            sqlite_copy(db_file, os.path.join(tmp_snap, "rt.db"))
            db_entry = "rt.db"
        elif db.engine.dialect.name == "postgresql":
            _pg_dump(db.url, os.path.join(tmp_snap, "rt.pgdump"))
            db_entry = "rt.pgdump"
        else:
            raise BackupError(f"Backup non supportato per il database {db.engine.dialect.name}.")
        say(f"🗄  Database salvato ({db_entry}).")

        # 2. media, incrementale per hash
        entries = []
        on_disk = _walk_media(media_dir)
        for rel in sorted(set(inventory) | set(on_disk)):
            src = os.path.join(media_dir, rel)
            if not os.path.isfile(src):
                continue
            sha = str(inventory.get(rel, {}).get("sha256") or "") or sha256_file(src)
            size = os.path.getsize(src)
            target = _store_path(dest, sha)
            if not os.path.isfile(target) or os.path.getsize(target) != size:
                _copy_atomic(src, target)
                result.media_copied += 1
                result.bytes_copied += size
            entries.append({"path": rel, "sha256": sha, "size": size, "referenced": rel in inventory})
        result.media_total = len(entries)
        say(f"🎧 Media: {result.media_total} file, {result.media_copied} nuovi copiati "
            f"({result.bytes_copied / 1_048_576:.1f} MB).")

        # 3. configurazione, segreti cifrati, .env, stato del bot
        from rt.core.config import load_config
        home = paths.config_home()
        config_dir = os.path.join(home, "config")
        if os.path.isdir(config_dir):
            shutil.copytree(config_dir, os.path.join(tmp_snap, "config"))
        env = paths.env_file()
        if os.path.isfile(env):
            shutil.copy2(env, os.path.join(tmp_snap, "env"))
        state_dir = load_config().telegram.state_dir
        if os.path.isdir(state_dir):
            shutil.copytree(state_dir, os.path.join(tmp_snap, "telegram-state"))
        say("⚙️  Configurazione e segreti cifrati salvati.")

        from rt.core.version import get_current_version
        manifest = {
            "format": FORMAT,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rt_version": get_current_version(paths.project_root()),
            "database": db_entry,
            "data_dir": paths.data_dir(),
            "media": entries,
            "missing_media": missing,
        }
        with open(os.path.join(tmp_snap, MANIFEST), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1, ensure_ascii=False)
        os.replace(tmp_snap, snap)
    except Exception:
        shutil.rmtree(tmp_snap, ignore_errors=True)
        raise
    try:
        os.chmod(snap, 0o700)
    except OSError:
        pass
    result.folder_lessons = _folder_lessons(db)
    result.master_key_warning = master_key_warning()
    return result


def _walk_media(media_dir: str) -> List[str]:
    out = []
    if not os.path.isdir(media_dir):
        return out
    for base, _dirs, files in os.walk(media_dir):
        for name in files:
            if name.endswith((".part", ".tmp")):
                continue
            out.append(os.path.relpath(os.path.join(base, name), media_dir).replace(os.sep, "/"))
    return out


def master_key_warning() -> Optional[str]:
    """Il promemoria sulla chiave master, se esiste un archivio cifrato."""
    from rt.security.secrets import MASTER_KEY_ENV, default_store_path
    if not default_store_path().is_file():
        return None
    where = "nella variabile RT_MASTER_KEY" if os.environ.get(MASTER_KEY_ENV) else "nel portachiavi di macOS"
    return (f"🔑 La chiave master che decifra i segreti sta {where} e NON è nel backup. "
            "Salvala a parte (per esempio in un password manager): senza, dopo un ripristino "
            "chiavi API e token andranno reinseriti. Per vederla: 'rt secrets show-key'.")


def _pg_dump(url: str, target: str) -> None:
    from sqlalchemy.engine import make_url
    plain = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        subprocess.run(["pg_dump", "-Fc", "-f", target, plain], check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise BackupError("pg_dump non trovato: installa il client di PostgreSQL.") from exc
    except subprocess.CalledProcessError as exc:
        raise BackupError(f"pg_dump non riuscito: {exc.stderr.strip()}") from exc


def list_backups(dest: Optional[str] = None) -> List[Dict[str, object]]:
    dest = os.path.abspath(os.path.expanduser(dest or default_dest()))
    out = []
    if not os.path.isdir(dest):
        return out
    for name in sorted(os.listdir(dest), reverse=True):
        manifest = os.path.join(dest, name, MANIFEST)
        if name.startswith(BACKUP_PREFIX) and os.path.isfile(manifest):
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
            out.append({"path": os.path.join(dest, name), "created": data.get("created"),
                        "rt_version": data.get("rt_version"), "media": len(data.get("media") or [])})
    return out


# ---------------------------------------------------------------- ripristino

def resolve_snapshot(path: str) -> str:
    """Accetta una cartella rt-backup-* o la cartella dei backup (prende il più recente)."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(os.path.join(path, MANIFEST)):
        return path
    found = list_backups(path)
    if found:
        return str(found[0]["path"])
    raise BackupError(f"Nessun backup di RT in {path}.")


def restore_backup(source: str, say: Callable[[str], None] = print, check_services: bool = True) -> str:
    """Ripristina un backup nella cartella dati attiva. DB, config e .env attuali vengono
    prima spostati in <dati>/backups/prima-del-ripristino-<data>. Restituisce quella cartella."""
    from rt.db.engine import current_database_url, reset_database_cache, sqlite_file
    snap = resolve_snapshot(source)
    with open(os.path.join(snap, MANIFEST), encoding="utf-8") as f:
        manifest = json.load(f)
    if int(manifest.get("format", 0)) > FORMAT:
        raise BackupError("Il backup viene da una versione di RT più recente: aggiorna RT prima.")
    store_root = os.path.dirname(snap)
    for entry in manifest.get("media") or []:
        if not os.path.isfile(_store_path(store_root, entry["sha256"])):
            raise BackupError(f"Backup incompleto: manca il contenuto di {entry['path']} in {STORE}/.")
    if check_services:
        from rt.services.data_service import running_services
        busy = running_services()
        if busy:
            raise BackupError("Prima del ripristino ferma " + ", ".join(busy) + " ('rt service stop').")

    data = paths.data_dir()
    url = current_database_url()
    db_file = sqlite_file(url) if url else None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    aside = os.path.join(data, "backups", f"prima-del-ripristino-{stamp}")
    os.makedirs(aside, exist_ok=True)

    # 1. database
    if manifest["database"] == "rt.db":
        if not db_file:
            raise BackupError("Il backup contiene un database SQLite ma RT usa un altro database.")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_file + suffix):
                shutil.move(db_file + suffix, os.path.join(aside, os.path.basename(db_file) + suffix))
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        shutil.copy2(os.path.join(snap, "rt.db"), db_file)
    else:
        _pg_restore(url, os.path.join(snap, "rt.pgdump"))
    reset_database_cache()
    say("🗄  Database ripristinato.")

    # 2. configurazione e .env
    home = paths.config_home()
    if os.path.isdir(os.path.join(snap, "config")):
        current = os.path.join(home, "config")
        if os.path.isdir(current):
            shutil.move(current, os.path.join(aside, "config"))
        shutil.copytree(os.path.join(snap, "config"), current)
    if os.path.isfile(os.path.join(snap, "env")):
        current_env = os.path.join(home, ".env")
        if os.path.isfile(current_env):
            shutil.move(current_env, os.path.join(aside, "env"))
        shutil.copy2(os.path.join(snap, "env"), current_env)
    if os.path.isdir(os.path.join(snap, "telegram-state")):
        from rt.core.config import load_config
        state_dir = load_config().telegram.state_dir
        if os.path.isdir(state_dir):
            shutil.move(state_dir, os.path.join(aside, "telegram-state"))
        shutil.copytree(os.path.join(snap, "telegram-state"), state_dir)
    say("⚙️  Configurazione ripristinata.")

    # 3. media: si copiano solo quelli mancanti o diversi
    from rt.db.engine import require_database
    from rt.storage import fs
    db = require_database()  # applica anche le migrazioni se il backup è di una versione precedente
    media_dir = fs.media_dir(db)
    copied = 0
    for entry in manifest.get("media") or []:
        target = os.path.join(media_dir, entry["path"])
        if os.path.isfile(target) and os.path.getsize(target) == entry["size"] and sha256_file(target) == entry["sha256"]:
            continue
        _copy_atomic(_store_path(store_root, entry["sha256"]), target)
        copied += 1
    say(f"🎧 Media ripristinati: {copied} copiati, {len(manifest.get('media') or []) - copied} già presenti.")
    problems = verify_media(db, media_dir)
    if problems:
        say(f"⚠️  {len(problems)} media referenziati mancano ancora (es. {problems[0]}).")
    say(f"📦 I dati sostituiti sono in {aside}.")
    return aside


def _pg_restore(url: str, dump: str) -> None:
    from sqlalchemy.engine import make_url
    plain = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", "-d", plain, dump],
                       check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise BackupError("pg_restore non trovato: installa il client di PostgreSQL.") from exc
    except subprocess.CalledProcessError as exc:
        raise BackupError(f"pg_restore non riuscito: {exc.stderr.strip()}") from exc
