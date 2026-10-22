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
                  allow_missing: bool = False,
                  progress: Optional[Callable[[str, int, int], None]] = None) -> BackupResult:
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
        if progress:
            progress("database", 0, 1)
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
        if progress:
            progress("database", 1, 1)

        # 2. media, incrementale per hash
        entries = []
        on_disk = _walk_media(media_dir)
        media_candidates = sorted(set(inventory) | set(on_disk))
        total_media = len(media_candidates)
        if total_media == 0 and progress:
            progress("media", 0, 0)
        for i, rel in enumerate(media_candidates, 1):
            src = os.path.join(media_dir, rel)
            if not os.path.isfile(src):
                if progress:
                    progress("media", i, total_media)
                continue
            sha = str(inventory.get(rel, {}).get("sha256") or "") or sha256_file(src)
            size = os.path.getsize(src)
            target = _store_path(dest, sha)
            if not os.path.isfile(target) or os.path.getsize(target) != size:
                _copy_atomic(src, target)
                result.media_copied += 1
                result.bytes_copied += size
            entries.append({"path": rel, "sha256": sha, "size": size, "referenced": rel in inventory})
            if progress:
                progress("media", i, total_media)
        result.media_total = len(entries)
        say(f"🎧 Media: {result.media_total} file, {result.media_copied} nuovi copiati "
            f"({result.bytes_copied / 1_048_576:.1f} MB).")

        archive_entries = []
        archive = os.path.join(paths.data_dir(), 'archivio')
        for rel in _walk_media(archive):
            src = os.path.join(archive, rel)
            sha = sha256_file(src)
            target = _store_path(dest, sha)
            if not os.path.isfile(target):
                _copy_atomic(src, target)
            archive_entries.append({'path': rel, 'sha256': sha, 'size': os.path.getsize(src)})

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
        if progress:
            progress("config", 1, 1)

        from rt.core.version import get_current_version
        manifest = {
            "format": FORMAT,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rt_version": get_current_version(paths.project_root()),
            "database": db_entry,
            "data_dir": paths.data_dir(),
            "media": entries,
            "archivio": archive_entries,
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


def export_backup(snapshot: str, target_zip: str,
                  progress: Optional[Callable[[str, int, int], None]] = None, *, segreti: bool = False) -> str:
    import zipfile
    snap = resolve_snapshot(snapshot)
    if not os.path.isdir(snap):
        raise BackupError(f"Lo snapshot {snap} non è una cartella di backup valida.")
    manifest_path = os.path.join(snap, MANIFEST)
    if not os.path.isfile(manifest_path):
        raise BackupError(f"Manifest mancante in {snap}.")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    store_root = os.path.dirname(snap)
    absent = [e["path"] for e in (manifest.get("media") or []) + (manifest.get("archivio") or [])
              if not os.path.isfile(_store_path(store_root, e["sha256"]))]
    if absent:
        store = os.path.join(store_root, STORE)
        where = (f"manca la cartella {store}" if not os.path.isdir(store)
                 else f"in {store} mancano {len(absent)} media su {len(manifest.get('media') or [])}")
        raise BackupError(f"Backup incompleto: {where} (es. {absent[0]}).")

    target_zip = os.path.abspath(os.path.expanduser(target_zip))
    if not target_zip.lower().endswith(".zip"):
        target_zip += ".zip"
    os.makedirs(os.path.dirname(target_zip), exist_ok=True)
    part_file = target_zip + ".part"

    snap_base = os.path.basename(snap)
    files_to_pack: List[tuple[str, str, int]] = []
    for root, _dirs, files in os.walk(snap):
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = os.path.relpath(full, snap).replace(os.sep, "/")
            if not segreti and rel == 'config/secrets.enc':
                continue
            arcname = f"{snap_base}/{rel}"
            files_to_pack.append((full, arcname, os.path.getsize(full)))

    seen_sha = set()
    for entry in (manifest.get("media") or []) + (manifest.get("archivio") or []):
        sha = entry["sha256"]
        if sha in seen_sha:
            continue
        seen_sha.add(sha)
        media_full = _store_path(store_root, sha)
        media_arcname = f"{STORE}/{sha[:2]}/{sha}"
        files_to_pack.append((media_full, media_arcname, os.path.getsize(media_full)))

    replacements = {}
    if not segreti:
        manifest['segreti'] = False
        replacements[f'{snap_base}/{MANIFEST}'] = json.dumps(manifest, ensure_ascii=False, indent=1).encode('utf-8')
        env_path = os.path.join(snap, 'env')
        if os.path.isfile(env_path):
            with open(env_path, encoding='utf-8') as stream:
                replacements[f'{snap_base}/env'] = _env_parts(stream.read(), secret=False).encode('utf-8')
    total_bytes = sum(len(replacements[arc]) if arc in replacements else sz for _, arc, sz in files_to_pack)
    bytes_written = 0
    if progress:
        progress("copia", 0, total_bytes)

    try:
        with zipfile.ZipFile(part_file, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for full, arcname, _size in files_to_pack:
                if arcname in replacements:
                    payload = replacements[arcname]
                    zf.writestr(arcname, payload)
                    bytes_written += len(payload)
                    if progress:
                        progress('copia', bytes_written, total_bytes)
                    continue
                with open(full, "rb") as src_f, zf.open(arcname, "w") as dst_f:
                    while True:
                        chunk = src_f.read(1024 * 1024)
                        if not chunk:
                            break
                        dst_f.write(chunk)
                        bytes_written += len(chunk)
                        if progress:
                            progress("copia", bytes_written, total_bytes)
        os.replace(part_file, target_zip)
    except Exception:
        if os.path.exists(part_file):
            try:
                os.remove(part_file)
            except OSError:
                pass
        raise
    return target_zip


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
    """Accetta una cartella rt-backup-*, un file .zip o la cartella dei backup (prende il più recente)."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        return path
    if os.path.isfile(os.path.join(path, MANIFEST)):
        return path
    found = list_backups(path)
    if found:
        return str(found[0]["path"])
    raise BackupError(f"Nessun backup di RT in {path}.")


def restore_backup(source: str, say: Callable[[str], None] = print, check_services: bool = True,
                   progress: Optional[Callable[[str, int, int], None]] = None) -> str:
    """Ripristina un backup nella cartella dati attiva. DB, config e .env attuali vengono
    prima spostati in <dati>/backups/prima-del-ripristino-<data>. Restituisce quella cartella."""
    import zipfile
    from rt.db.engine import current_database_url, reset_database_cache, sqlite_file

    snap = resolve_snapshot(source)
    tmp_restore: Optional[str] = None
    try:
        if os.path.isfile(snap) and (snap.lower().endswith(".zip") or zipfile.is_zipfile(snap)):
            inspect_backup_zip(snap)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            tmp_restore = os.path.join(paths.data_dir(), "backups", f"tmp-restore-{stamp}-{os.getpid()}")
            os.makedirs(tmp_restore, exist_ok=True)
            with zipfile.ZipFile(snap, "r") as zf:
                for member in zf.infolist():
                    name = member.filename
                    p = name.replace("\\", "/")
                    parts = [part for part in p.split("/") if part]
                    if p.startswith("/") or ":" in p or ".." in parts:
                        raise BackupError(f"Percorso non sicuro nell'archivio di backup: {name}")
                zf.extractall(tmp_restore)

            candidate_dirs = [d for d in os.listdir(tmp_restore)
                              if d.startswith(BACKUP_PREFIX) and os.path.isdir(os.path.join(tmp_restore, d))]
            if not candidate_dirs or not os.path.isfile(os.path.join(tmp_restore, candidate_dirs[0], MANIFEST)):
                raise BackupError(f"Nessun backup valido nello zip {os.path.basename(snap)}.")
            snap = os.path.join(tmp_restore, candidate_dirs[0])

        with open(os.path.join(snap, MANIFEST), encoding="utf-8") as f:
            manifest = json.load(f)
        if int(manifest.get("format", 0)) > FORMAT:
            raise BackupError("Il backup viene da una versione di RT più recente: aggiorna RT prima.")
        _validate_manifest(manifest)
        portable = manifest.get('segreti') is False
        if not os.path.isfile(os.path.join(snap, manifest['database'])):
            raise BackupError('Database mancante nel backup. Nulla è stato modificato.')
        store_root = os.path.dirname(snap)
        absent = [e["path"] for e in (manifest.get("media") or []) + (manifest.get("archivio") or [])
                  if not os.path.isfile(_store_path(store_root, e["sha256"]))]
        if absent:
            store = os.path.join(store_root, STORE)
            where = (f"manca la cartella {store}" if not os.path.isdir(store)
                     else f"in {store} mancano {len(absent)} media su {len(manifest.get('media') or [])}")
            raise BackupError(f"Backup incompleto: {where} (es. {absent[0]}). I media stanno in {STORE}/, "
                              f"accanto a {os.path.basename(snap)}: se hai copiato il backup da un altro disco, "
                              f"copia tutta la cartella che li contiene entrambi, oppure usa lo zip salvato con "
                              f"«Salva una copia». Nulla è stato modificato.")
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
        if os.path.exists(aside):
            import tempfile
            aside = tempfile.mkdtemp(prefix=f'prima-del-ripristino-{stamp}-', dir=os.path.join(data, 'backups'))
        else:
            os.makedirs(aside)

        if progress:
            progress('database', 0, 1)
        # 1. database
        if manifest["database"] == "rt.db":
            if not db_file:
                raise BackupError("Il backup contiene un database SQLite ma RT usa un altro database.")
            reset_database_cache()  # su Windows un file SQLite aperto non si può spostare
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(db_file + suffix):
                    shutil.move(db_file + suffix, os.path.join(aside, os.path.basename(db_file) + suffix))
            if portable:
                local_db = os.path.join(data, 'rt.db')
                if os.path.abspath(local_db) != os.path.abspath(db_file):
                    for suffix in ('', '-wal', '-shm'):
                        if os.path.exists(local_db + suffix):
                            shutil.move(local_db + suffix, os.path.join(aside, 'locale-rt.db' + suffix))
                db_file = local_db
                if 'RT_DATABASE_URL' in os.environ:
                    os.environ['RT_DATABASE_URL'] = 'sqlite:///' + db_file
            os.makedirs(os.path.dirname(db_file), exist_ok=True)
            shutil.copy2(os.path.join(snap, "rt.db"), db_file)
        else:
            _pg_restore(url, os.path.join(snap, "rt.pgdump"))
        reset_database_cache()
        say("🗄  Database ripristinato.")
        if progress:
            progress('database', 1, 1)

        # 2. configurazione e .env
        home = paths.config_home()
        incoming_config = os.path.join(snap, 'config')
        if os.path.isdir(incoming_config):
            current = os.path.join(home, 'config')
            if portable:
                os.makedirs(current, exist_ok=True)
                saved_config = os.path.join(aside, 'config')
                os.makedirs(saved_config, exist_ok=True)
                for name in os.listdir(current):
                    if name != 'secrets.enc':
                        shutil.move(os.path.join(current, name), os.path.join(saved_config, name))
                shutil.copytree(incoming_config, current, dirs_exist_ok=True, ignore=shutil.ignore_patterns('secrets.enc'))
            else:
                if os.path.isdir(current):
                    shutil.move(current, os.path.join(aside, 'config'))
                shutil.copytree(incoming_config, current)
        current_env = os.path.join(home, '.env')
        incoming_env = os.path.join(snap, 'env')
        if os.path.isfile(incoming_env):
            old_env = ''
            if os.path.isfile(current_env):
                with open(current_env, encoding='utf-8') as stream:
                    old_env = stream.read()
                shutil.copy2(current_env, os.path.join(aside, 'env'))
            with open(incoming_env, encoding='utf-8') as stream:
                imported_env = stream.read()
            if portable:
                imported_env = _env_parts(imported_env, secret=False).rstrip() + '\n' + _env_parts(old_env, secret=True)
            with open(current_env, 'w', encoding='utf-8') as stream:
                stream.write(imported_env)
        if portable:
            changed = _reset_imported_paths(home, data, manifest['database'] == 'rt.db')
            if changed:
                say('Percorsi ripristinati ai valori predefiniti: ' + ', '.join(changed) + '.')
        if progress:
            progress('config', 1, 1)
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
        media_entries = manifest.get('media') or []
        for index, entry in enumerate(media_entries):
            if progress:
                progress('media', index, len(media_entries))
            target = os.path.join(media_dir, entry["path"])
            if os.path.isfile(target) and os.path.getsize(target) == entry["size"] and sha256_file(target) == entry["sha256"]:
                continue
            _copy_atomic(_store_path(store_root, entry["sha256"]), target)
            copied += 1
        if progress:
            progress('media', len(media_entries), len(media_entries))
        for entry in manifest.get('archivio') or []:
            target = os.path.abspath(os.path.join(data, 'archivio', entry['path']))
            root = os.path.abspath(os.path.join(data, 'archivio'))
            if not target.startswith(root + os.sep):
                raise BackupError('Percorso archivio non valido nel backup.')
            _copy_atomic(_store_path(store_root, entry['sha256']), target)
        say(f"🎧 Media ripristinati: {copied} copiati, {len(manifest.get('media') or []) - copied} già presenti.")
        problems = verify_media(db, media_dir)
        if problems:
            say(f"⚠️  {len(problems)} media referenziati mancano ancora (es. {problems[0]}).")
        say(f"📦 I dati sostituiti sono in {aside}.")
        return aside
    finally:
        if tmp_restore and os.path.exists(tmp_restore):
            shutil.rmtree(tmp_restore, ignore_errors=True)


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


# ---------------------------------------------------------------- collezioni portabili (senza segreti)

def _secret_name(name):
    import re
    return bool(re.search(r'(?:^|_)(?:KEY|TOKEN|SECRET|PASSWORD)(?:_\d+)?$', name.upper()))


def _env_parts(text, *, secret):
    from io import StringIO
    from dotenv.parser import parse_stream
    # Il parser conserva anche i valori multilinea: togliere solo la prima riga non basta.
    return ''.join(binding.original.string for binding in parse_stream(StringIO(text))
                   if bool(binding.key and _secret_name(binding.key)) == secret)


def _validate_manifest(manifest):
    import re
    if not isinstance(manifest, dict) or not isinstance(manifest.get('format'), int) or manifest['format'] < 1:
        raise BackupError('Manifest del backup non valido.')
    if manifest['format'] > FORMAT:
        raise BackupError('Il backup viene da una versione di RT più recente: aggiorna RT prima.')
    if manifest.get('database') not in {'rt.db', 'rt.pgdump'}:
        raise BackupError('Database del backup non valido.')
    for entry in (manifest.get('media') or []) + (manifest.get('archivio') or []):
        rel = entry.get('path', '').replace('\\', '/')
        if not rel or rel.startswith('/') or ':' in rel or '..' in rel.split('/'):
            raise BackupError('Percorso non sicuro nel manifest del backup.')
        if not re.fullmatch('[a-f0-9]{64}', entry.get('sha256', '')):
            raise BackupError('Hash non valido nel manifest del backup.')


def inspect_backup_zip(source):
    """Controllo rapido prima della conferma: non estrae e non modifica la collezione."""
    import zipfile
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            for name in names:
                rel = name.replace('\\', '/')
                if rel.startswith('/') or ':' in rel or '..' in rel.split('/'):
                    raise BackupError(f'Percorso non sicuro nell’archivio di backup: {name}')
            manifests = [name for name in names if name.count('/') == 1 and name.startswith(BACKUP_PREFIX) and name.endswith('/' + MANIFEST)]
            if len(manifests) != 1:
                raise BackupError('Nessun backup valido nello zip.')
            if archive.getinfo(manifests[0]).file_size > 16 * 1024 * 1024:
                raise BackupError('Manifest del backup troppo grande.')
            manifest = json.loads(archive.read(manifests[0]))
            _validate_manifest(manifest)
            prefix = manifests[0].rsplit('/', 1)[0]
            if prefix + '/' + manifest['database'] not in names:
                raise BackupError('Database mancante nel backup.')
            if manifest['database'] == 'rt.db':
                with archive.open(prefix + '/rt.db') as stream:
                    if stream.read(16) != b'SQLite format 3\x00':
                        raise BackupError('Database SQLite del backup non valido.')
            return manifest
    except BackupError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        raise BackupError('Il file non contiene un backup valido di RT.') from exc


def export_collection(target, *, confirm=None, say=print, progress=None):
    from rt.db.engine import require_database
    from rt.services.lesson_service import configured_lessons_root
    from rt.storage.migrate import folder_lessons, migrate_storage
    db = require_database()
    folders = folder_lessons(db, configured_lessons_root())
    if folders:
        if confirm is None or not confirm(len(folders)):
            return None
        report = migrate_storage(configured_lessons_root(), backup_root=default_dest(), on_progress=say)
        if report.errors:
            raise BackupError('Migrazione delle lezioni non completata: ' + '; '.join(report.errors))
    backup = create_backup(say=say, progress=progress)
    return export_backup(backup.path, target, progress=progress, segreti=False)


def _reset_imported_paths(home, data, sqlite):
    import yaml
    from dotenv.parser import parse_stream
    from io import StringIO
    from rt.core.config import RTConfig
    defaults = RTConfig().model_dump()
    changed = []
    general = os.path.join(home, 'config', 'general.yaml')
    if os.path.isfile(general):
        with open(general, encoding='utf-8') as stream:
            config = yaml.safe_load(stream) or {}
        def reset(node, fallback, prefix=''):
            for name, value in list(node.items()):
                key = prefix + name
                default = fallback.get(name) if isinstance(fallback, dict) else None
                if isinstance(value, dict):
                    reset(value, default, key + '.')
                elif name.endswith(('_dir', '_root', '_path')) and isinstance(value, str) and value and not os.path.exists(os.path.expanduser(value)):
                    node[name] = default
                    changed.append(key)
        reset(config, defaults)
        if sqlite:
            if config.get('database_url') != 'sqlite:///' + os.path.join(data, 'rt.db'):
                changed.append('database_url')
            config['database_url'] = 'sqlite:///' + os.path.join(data, 'rt.db')
        with open(general, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
    env = os.path.join(home, '.env')
    if os.path.isfile(env):
        with open(env, encoding='utf-8') as stream:
            text = stream.read()
        lines = []
        for binding in parse_stream(StringIO(text)):
            name, value = binding.key, binding.value
            if name == 'RT_DATABASE_URL' and sqlite:
                lines.append('RT_DATABASE_URL=sqlite:///' + os.path.join(data, 'rt.db') + '\n')
                changed.append(name)
            elif name == 'RT_DATA_DIR' or (name and name.endswith(('_DIR', '_ROOT', '_PATH')) and value and not os.path.exists(os.path.expanduser(value))):
                changed.append(name)
            else:
                lines.append(binding.original.string)
        with open(env, 'w', encoding='utf-8') as stream:
            stream.write(''.join(lines))
    return changed
