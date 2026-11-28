"""
rt.services.data_service
La cartella dati di RT (RT4-G1, rt.core.paths): creazione per le installazioni nuove e
migrazione automatica dalla disposizione 3.x.

Disposizione 3.x: config/ e .env nella cartella d'installazione, config/secrets.enc,
stato del bot in <installazione>/.rt_telegram, DB e media/ in <lessons_root>/.rt, PID in ~/.rt.
Disposizione 4.0: tutto nella cartella dati (RT_DATA_DIR o ~/.rt):

    <dati>/rt-data.json      segna la cartella come attiva
    <dati>/config/           general.yaml, job, secrets.enc
    <dati>/.env              variabili non segrete (RT_TELEGRAM_CHAT_ID)
    <dati>/rt.db             database (SQLite)
    <dati>/media/            audio e immagini delle lezioni
    <dati>/.rt_telegram/     log delle notifiche Telegram ed esempi del recall
    <dati>/logs/             log dei servizi
    <dati>/backups/          backup ('rt backup') e copie di sicurezza delle migrazioni

La migrazione copia config e segreti, copia il DB con l'API di backup di SQLite (copia
coerente), sposta media/ e solo alla fine attiva la cartella. Gli originali restano
rinominati (*.migrato-<data>): niente viene cancellato. Si rifiuta se API o worker
sono attivi, perché scriverebbero nel DB vecchio.
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from rt.core import paths

SUBDIRS = ("config", "media", "logs", "backups", "archivio")


class DataDirError(RuntimeError):
    pass


@dataclass
class MigrationStep:
    what: str
    source: str
    target: str
    action: str  # copy | move | sqlite-backup


@dataclass
class MigrationPlan:
    data_dir: str
    steps: List[MigrationStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    already_active: bool = False
    # la cartella dati resta dove sono già DB e media (<lessons_root>/.rt): ~/.rt rimanda lì
    redirect_from: Optional[str] = None

    @property
    def needed(self) -> bool:
        return not self.already_active


# ---------------------------------------------------------------- nuova installazione

def init_data_dir(path: Optional[str] = None, say: Callable[[str], None] = print) -> str:
    """Crea la cartella dati (idempotente): sottocartelle, config/ da config.example/, .env da
    .env.example e il file che la attiva. Non sovrascrive mai file esistenti."""
    target = os.path.abspath(os.path.expanduser(path or paths.default_data_dir()))
    root = paths.project_root()
    os.makedirs(target, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    for name in SUBDIRS:
        os.makedirs(os.path.join(target, name), exist_ok=True)
    example = os.path.join(root, "config.example")
    config = os.path.join(target, "config")
    if os.path.isdir(example):
        fresh = not os.path.exists(os.path.join(config, "general.yaml"))
        _copy_missing(example, config)
        if fresh:
            _fallback_engine(os.path.join(config, "general.yaml"))
    env = os.path.join(target, ".env")
    if not os.path.exists(env):
        with open(env, "w", encoding="utf-8") as f:
            f.write("# RT: variabili non segrete. Chiavi e token stanno cifrati in config/secrets.enc\n")
        os.chmod(env, 0o600)
    if not paths.is_initialized(target):
        paths.write_marker(target, created=_now(), from_layout="new")
        say(f"📁 Cartella dati creata: {target}")
    return target


def _fallback_engine(general: str) -> None:
    """La nuova configurazione parte con macparakeet sul Mac (più preciso e veloce di ONNX) e
    dove onnx-asr manca (es. Python 3.15 senza ruote di onnxruntime)."""
    import sys
    from rt.core import onnx_stt
    if sys.platform != "darwin" and onnx_stt.available():
        return
    try:
        with open(general, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    fixed = text.replace('engine: "parakeet"', 'engine: "macparakeet"', 1)
    if fixed != text:
        with open(general, "w", encoding="utf-8") as f:
            f.write(fixed)


def _copy_missing(src: str, dst: str) -> None:
    """Copia src in dst senza toccare i file che esistono già (config dell'utente)."""
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        out = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out, exist_ok=True)
        for name in files:
            target = os.path.join(out, name)
            if not os.path.exists(target):
                shutil.copy2(os.path.join(base, name), target)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- migrazione dalla 3.x

def _legacy_config():
    from rt.core.config import load_config
    root = paths.project_root()
    config_dir = os.path.join(root, "config")
    if os.path.isdir(config_dir):
        from rt.core.config import _load_config_dir, _resolve_telegram_state_dir
        return _resolve_telegram_state_dir(_load_config_dir(config_dir), root)
    return load_config()


def plan_migration(target: Optional[str] = None) -> MigrationPlan:
    """Cosa farebbe la migrazione dalla disposizione 3.x alla cartella dati.

    Se DB e media 3.x stanno in <lessons_root>/.rt (anche su un disco esterno) e la cartella
    dati non è stata scelta con RT_DATA_DIR, restano lì: diventa quella la cartella dati e
    ~/.rt/rt-data.json rimanda lì. Si copiano solo config, .env e stato del bot. Con
    RT_DATA_DIR (o target) il DB viene copiato e media/ spostata nella cartella scelta."""
    default = paths.default_data_dir()
    chosen = os.path.abspath(os.path.expanduser(target)) if target else None
    if chosen is None and paths.is_initialized(default):
        return MigrationPlan(data_dir=paths.active_data_dir() or default, already_active=True)
    if chosen is not None and paths.is_initialized(chosen):
        return MigrationPlan(data_dir=chosen, already_active=True)
    plan = MigrationPlan(data_dir=chosen or default)
    root = paths.project_root()
    try:
        cfg = _legacy_config()
    except Exception as exc:
        plan.notes.append(f"Configurazione 3.x illeggibile ({exc}): migro solo i file.")
        cfg = None

    old_db = None
    if cfg is not None:
        explicit_url = os.environ.get("RT_DATABASE_URL") or getattr(cfg, "database_url", None)
        if explicit_url:
            plan.notes.append("database_url è impostato a mano: il database resta dov'è.")
        else:
            from rt.db.engine import default_sqlite_path
            candidate = os.path.abspath(default_sqlite_path(cfg.telegram.lessons_root))
            if os.path.isfile(candidate):
                old_db = candidate
    if old_db and chosen is None and not paths.explicit_data_dir() and os.path.dirname(old_db) != default:
        plan.redirect_from = default
        plan.data_dir = os.path.dirname(old_db)
        old_db = None  # resta dov'è
    target_dir = plan.data_dir

    for name, what in (("config", "configurazione (YAML e secrets.enc)"), (".env", "file .env")):
        src = os.path.join(root, name)
        if os.path.exists(src) and not os.path.exists(os.path.join(target_dir, name)):
            plan.steps.append(MigrationStep(what, src, os.path.join(target_dir, name), "copy"))
    if cfg is not None:
        state_dir = cfg.telegram.state_dir
        dest = os.path.join(target_dir, os.path.basename(state_dir))
        if os.path.isdir(state_dir) and _inside(state_dir, root) and not os.path.exists(dest):
            plan.steps.append(MigrationStep("stato del bot Telegram", state_dir, dest, "copy"))
    if old_db:
        new_db = os.path.join(target_dir, "rt.db")
        if old_db == os.path.abspath(new_db):
            pass
        elif os.path.exists(new_db):
            plan.notes.append(f"Esiste già {new_db}: il database vecchio ({old_db}) non viene copiato.")
        else:
            plan.steps.append(MigrationStep("database", old_db, new_db, "sqlite-backup"))
            old_media = os.path.join(os.path.dirname(old_db), "media")
            if os.path.isdir(old_media) and not os.path.exists(os.path.join(target_dir, "media")):
                plan.steps.append(MigrationStep("media delle lezioni (audio e immagini)", old_media,
                                                os.path.join(target_dir, "media"), "move"))
    if plan.redirect_from:
        plan.notes.append(f"Database e media restano in {plan.data_dir}: diventa la cartella dati "
                          f"({plan.redirect_from} rimanda lì).")
    return plan


def _inside(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(parent)]) == os.path.abspath(parent)
    except ValueError:
        return False


def running_services() -> List[str]:
    """Processi di RT che scrivono nel DB adesso: worker e API. Vuota se nessuno."""
    out = []
    try:
        from rt.db.engine import get_database
        from rt.services.jobs import DbJobQueue
        db = get_database()
        if db is not None and DbJobQueue(db).live_workers():
            out.append("worker")
    except Exception:
        pass
    from rt.services.service_manager import api_is_up
    if api_is_up():
        out.append("API/web")
    return out


def migrate(target: Optional[str] = None, dry_run: bool = False, say: Callable[[str], None] = print,
            check_services: bool = True) -> MigrationPlan:
    """Esegue plan_migration(). Idempotente: con la cartella già attiva non fa nulla."""
    plan = plan_migration(target)
    if plan.already_active:
        return plan
    if dry_run:
        return plan
    if check_services:
        busy = running_services()
        if busy:
            raise DataDirError("Prima della migrazione ferma " + ", ".join(busy)
                               + " ('rt service stop' o Ctrl+C dove li hai avviati).")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    done: List[MigrationStep] = []
    os.makedirs(plan.data_dir, exist_ok=True)
    try:
        for step in plan.steps:
            say(f"➡️  {step.what}: {step.source} → {step.target}")
            if step.action == "copy":
                if os.path.isdir(step.source):
                    shutil.copytree(step.source, step.target, symlinks=True)
                else:
                    shutil.copy2(step.source, step.target)
            elif step.action == "sqlite-backup":
                sqlite_copy(step.source, step.target)
            elif step.action == "move":
                shutil.move(step.source, step.target)
            done.append(step)
    except Exception as exc:
        _rollback(done, say)
        raise DataDirError(f"Migrazione non riuscita, nulla è cambiato: {exc}") from exc
    init_data_dir(plan.data_dir, say=lambda _m: None)
    paths.write_marker(plan.data_dir, created=_now(), from_layout="3.x",
                       migrated=[{"what": s.what, "from": s.source} for s in done])
    if plan.redirect_from:
        paths.write_marker(plan.redirect_from, created=_now(), location=plan.data_dir)
    # Gli originali copiati restano, rinominati: chi lancia rt dalla cartella d'installazione
    # non deve ritrovare la config vecchia (config/ nella cwd vince sulla cartella dati).
    for step in done:
        if step.action in ("copy", "sqlite-backup") and os.path.exists(step.source):
            _rename_legacy(step.source, stamp)
            if step.action == "sqlite-backup":
                for suffix in ("-wal", "-shm"):
                    if os.path.exists(step.source + suffix):
                        _rename_legacy(step.source + suffix, stamp)
    from rt.db.engine import reset_database_cache
    reset_database_cache()
    return plan


def _rename_legacy(path: str, stamp: str) -> None:
    try:
        os.replace(path, f"{path}.migrato-{stamp}")
    except OSError:
        pass


def _rollback(done: List[MigrationStep], say: Callable[[str], None]) -> None:
    for step in reversed(done):
        try:
            if step.action == "move":
                shutil.move(step.target, step.source)
            elif os.path.isdir(step.target):
                shutil.rmtree(step.target)
            elif os.path.exists(step.target):
                os.remove(step.target)
        except OSError as exc:
            say(f"⚠️  Ripristino di {step.target} non riuscito: {exc}")


def sqlite_copy(source: str, target: str) -> None:
    """Copia coerente di un DB SQLite (anche aperto da altri processi) con l'API di backup,
    poi verifica l'integrità della copia."""
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    tmp = target + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise DataDirError(f"Copia del database non integra: {ok}")
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(tmp, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def auto_migrate(say: Callable[[str], None] = print) -> Optional[MigrationPlan]:
    """Per 'rt -u' e l'installer: attiva la cartella dati se non lo è, migrando la 3.x se c'è.
    Con RT_DATA_DIR esplicita la cartella è già "attiva": si migra comunque se è vuota."""
    if paths.is_initialized(paths.default_data_dir()):
        return None
    plan = migrate(say=say)
    if not plan.steps and not plan.redirect_from:
        init_data_dir(plan.data_dir, say=say)
    else:
        say(f"✅ Cartella dati in uso: {plan.data_dir}")
    return plan


def _convert_folder_lessons(say: Callable[[str], None]) -> bool:
    """Chi aggiorna dalla 3.x (o da una 4.0 con lezioni a cartelle) le ritrova nella web app:
    le converte nel database e in media/ dopo un backup, come 'rt db migrate-storage'."""
    from rt.core.config import load_config
    from rt.db.engine import get_database
    from rt.storage.migrate import folder_lessons, migrate_storage
    db = get_database()
    root = load_config().telegram.lessons_root
    if db is None:
        return True
    try:
        pending = folder_lessons(db, root)
    except OSError as exc:  # es. macOS nega l'accesso alla Scrivania: RT parte lo stesso
        say(f"⚠️  Non riesco a controllare le lezioni a cartelle in {root}: {exc}")
        return False
    if not pending:
        return True
    say("📦 Converto le lezioni a cartelle nel database (con backup)...")
    try:
        report = migrate_storage(root, on_progress=say)
    except Exception as exc:  # la conversione si può sempre rilanciare a mano
        say(f"⚠️  Conversione non riuscita: {exc}. Rilancia con 'rt db migrate-storage'.")
        return False
    say(f"✅ Lezioni convertite: {len(report.migrated)}. Backup in {report.backup_dir}")
    for err in report.errors:
        say(f"  ⚠️  {err}")
    return not report.errors


def _restart_services(sm, say: Callable[[str], None]) -> bool:
    try:
        sm.install(sm.installed(), start=True, say=lambda _m: None)
    except sm.ServiceError as exc:
        say(f"⚠️  Servizi non riavviati: {exc}")
        return False
    say("▶️  Servizi aggiornati e riavviati.")
    return True


def _prefix_variants(old_dir: str) -> List[str]:
    """Varianti normalizzate del vecchio prefisso (percorso assoluto e percorso reale),
    ordinate dalla più lunga alla più corta."""
    raw = [os.path.abspath(old_dir), os.path.realpath(old_dir)]
    out: List[str] = []
    for item in raw:
        cleaned = item.rstrip("/\\")
        if cleaned and cleaned not in out:
            out.append(cleaned)
    out.sort(key=len, reverse=True)
    return out


def _rewrite_path_prefix(value: str, old_prefixes: Sequence[str], new_dir: str,
                         allow_tilde: bool = False) -> str:
    """Sostituisce il vecchio prefisso di cartella dati con new_dir rispettando il confine di
    percorso (es. non tocca ~/.rt-dev quando si sposta ~/.rt)."""
    if not value:
        return value
    if value.startswith("sqlite:///"):
        inner = value[len("sqlite:///"):]
        rewritten = _rewrite_path_prefix(inner, old_prefixes, new_dir, allow_tilde=allow_tilde)
        return ("sqlite:///" + rewritten) if rewritten != inner else value
    candidates = list(old_prefixes)
    if allow_tilde:
        home_legacy = os.path.abspath(os.path.expanduser("~/.rt")).rstrip("/\\")
        if any(os.path.normcase(p) == os.path.normcase(home_legacy) for p in old_prefixes):
            candidates.append("~/.rt")
    norm_val = os.path.normcase(value)
    for prefix in candidates:
        norm_pref = os.path.normcase(prefix)
        if norm_val == norm_pref:
            return new_dir
        if norm_val.startswith(norm_pref + "/") or norm_val.startswith(norm_pref + "\\"):
            return new_dir + value[len(prefix):]
    return value


def _rewrite_yaml_node(node, old_prefixes: Sequence[str], new_dir: str):
    if isinstance(node, dict):
        changed = False
        out = {}
        for k, v in node.items():
            nv, c = _rewrite_yaml_node(v, old_prefixes, new_dir)
            out[k] = nv
            changed = changed or c
        return out, changed
    if isinstance(node, list):
        changed = False
        out = []
        for item in node:
            ni, c = _rewrite_yaml_node(item, old_prefixes, new_dir)
            out.append(ni)
            changed = changed or c
        return out, changed
    if isinstance(node, str):
        rewritten = _rewrite_path_prefix(node, old_prefixes, new_dir, allow_tilde=True)
        return rewritten, rewritten != node
    return node, False


def _write_atomic_bytes(path: str, data: bytes, mode: Optional[int] = None) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    if mode is not None:
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
    os.replace(tmp, path)


_ENV_LINE_RE = re.compile(r"^(\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*)(.*)$")


def _rewrite_config_and_env(new_dir: str, old_prefixes: Sequence[str],
                            saved_files_rel: Dict[str, bytes]) -> None:
    import yaml
    config_root = os.path.join(new_dir, "config")
    if os.path.isdir(config_root):
        for base, _dirs, files in os.walk(config_root):
            for name in sorted(files):
                if not name.endswith((".yaml", ".yml")):
                    continue
                path = os.path.join(base, name)
                with open(path, "rb") as f:
                    raw_bytes = f.read()
                parsed = yaml.safe_load(raw_bytes.decode("utf-8"))
                if not isinstance(parsed, (dict, list)):
                    continue
                rewritten, changed = _rewrite_yaml_node(parsed, old_prefixes, new_dir)
                if not changed:
                    continue
                rel = os.path.relpath(path, new_dir)
                saved_files_rel[rel] = raw_bytes
                dumped = yaml.safe_dump(rewritten, sort_keys=False, allow_unicode=True, width=10000)
                _write_atomic_bytes(path, dumped.encode("utf-8"))

    env_path = os.path.join(new_dir, ".env")
    if os.path.isfile(env_path):
        with open(env_path, "rb") as f:
            raw_bytes = f.read()
        text = raw_bytes.decode("utf-8")
        lines = text.splitlines(keepends=True)
        out_lines: List[str] = []
        env_changed = False
        for line in lines:
            eol = ""
            body = line
            if body.endswith("\r\n"):
                body, eol = body[:-2], "\r\n"
            elif body.endswith("\n"):
                body, eol = body[:-1], "\n"
            stripped = body.lstrip()
            if not stripped or stripped.startswith("#"):
                out_lines.append(line)
                continue
            m = _ENV_LINE_RE.match(body)
            if not m:
                out_lines.append(line)
                continue
            prefix_part, rhs = m.group(1), m.group(2)
            quote = rhs[0] if len(rhs) >= 2 and rhs[0] == rhs[-1] and rhs[0] in ('"', "'") else ""
            inner = rhs[1:-1] if quote else rhs
            new_inner = _rewrite_path_prefix(inner, old_prefixes, new_dir, allow_tilde=True)
            if new_inner != inner:
                env_changed = True
                out_lines.append(f"{prefix_part}{quote}{new_inner}{quote}{eol}")
            else:
                out_lines.append(line)
        if env_changed:
            saved_files_rel[".env"] = raw_bytes
            _write_atomic_bytes(env_path, "".join(out_lines).encode("utf-8"), mode=0o600)


def _reset_downloading_components(new_dir: str, saved_files_rel: Dict[str, bytes]) -> None:
    models_dir = os.path.join(new_dir, "models")
    for lock_name in (".lock", ".macparakeet.lock", ".browser.lock", ".libreoffice.lock"):
        lpath = os.path.join(models_dir, lock_name)
        if os.path.exists(lpath):
            try:
                os.remove(lpath)
            except OSError:
                pass
    comp_path = os.path.join(models_dir, "components.json")
    if not os.path.isfile(comp_path):
        return
    with open(comp_path, "rb") as f:
        raw_bytes = f.read()
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    changed = False
    for entry in data.values():
        if isinstance(entry, dict) and entry.get("state") == "downloading":
            entry["state"] = "not_downloaded"
            entry["auto_resume"] = False
            entry["pid"] = None
            entry["helper_pid"] = None
            entry["detached_pid"] = None
            entry["eta_seconds"] = None
            entry["eta_label"] = None
            entry["error"] = None
            changed = True
    if changed:
        saved_files_rel[os.path.join("models", "components.json")] = raw_bytes
        encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _write_atomic_bytes(comp_path, encoded)


def _db_path_columns() -> List[Tuple[type, object]]:
    """Ispeziona i modelli SQLAlchemy e restituisce (Modello, attributo) per ogni colonna
    stringa path, lesson_path, *_path (e active_lesson)."""
    from sqlalchemy import String
    from rt.db.models import Base
    targets: List[Tuple[type, object]] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        for prop in mapper.column_attrs:
            col = prop.columns[0]
            if not isinstance(col.type, String):
                continue
            if (col.name == "path" or col.name == "lesson_path"
                    or col.name.endswith("_path") or col.name == "active_lesson"):
                targets.append((cls, getattr(cls, prop.key)))
    return targets


def _rewrite_db_paths(db_url: str, old_prefixes: Sequence[str], new_dir: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from rt.db.engine import create_db_engine, current_revision, head_revision, upgrade_database
    from rt.db.models import StateDocument

    eng = create_db_engine(db_url)
    try:
        if current_revision(eng) != head_revision():
            upgrade_database(db_url, eng)
        with Session(eng) as session, session.begin():
            for model_cls, col_attr in _db_path_columns():
                for row in session.scalars(select(model_cls).where(col_attr.is_not(None))):
                    val = getattr(row, col_attr.key)
                    if isinstance(val, str):
                        updated = _rewrite_path_prefix(val, old_prefixes, new_dir)
                        if updated != val:
                            setattr(row, col_attr.key, updated)
            for doc in list(session.scalars(select(StateDocument))):
                updated_key = _rewrite_path_prefix(doc.key, old_prefixes, new_dir)
                if updated_key != doc.key:
                    if session.get(StateDocument, updated_key) is None:
                        doc.key = updated_key
                    else:
                        session.delete(doc)
    finally:
        eng.dispose()


def _has_live_running_jobs(db_url: Optional[str]) -> bool:
    if not db_url:
        return False
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session
    from rt.db.engine import create_db_engine, sqlite_file
    from rt.db.models import Job, utcnow

    db_file = sqlite_file(db_url)
    if db_file and not os.path.isfile(db_file):
        return False
    eng = create_db_engine(db_url)
    try:
        with Session(eng) as session:
            live = session.scalar(
                select(Job.id)
                .where(
                    Job.state == "running",
                    Job.lease_until.is_not(None),
                    Job.lease_until >= utcnow(),
                )
                .limit(1)
            )
            return live is not None
    except SQLAlchemyError:
        return False
    finally:
        eng.dispose()


def _suspend_open_log_streams(root_dir: str) -> List[Tuple[str, str]]:
    """Su Windows (pythonw) stdout/stderr possono essere file aperti dentro la cartella dati:
    vanno chiusi prima di os.rename() per non avere PermissionError e riaperti dopo."""
    suspended: List[Tuple[str, str]] = []
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        name = getattr(stream, "name", None)
        if not isinstance(name, str) or not _inside(name, root_dir):
            continue
        rel = os.path.relpath(name, root_dir)
        try:
            stream.flush()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        setattr(sys, attr, None)
        suspended.append((attr, rel))
    return suspended


def _reopen_log_streams(suspended: Sequence[Tuple[str, str]], target_dir: str) -> None:
    for attr, rel in suspended:
        path = os.path.join(target_dir, rel)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            setattr(sys, attr, open(path, "a", encoding="utf-8", buffering=1, newline="\n"))
        except OSError:
            pass


_ALREADY_MOVED = "già nella cartella di sistema"


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(os.path.expanduser(a))) == \
        os.path.normcase(os.path.abspath(os.path.expanduser(b)))


def _drop_inherited_legacy_data_dir() -> None:
    """Fino alla 4.3.10b5 i servizi (LaunchAgents) ricevevano RT_DATA_DIR=~/.rt e l'app riaperta
    dopo un aggiornamento la ereditava: non è una scelta dell'utente (l'app non usa RT_DATA_DIR)
    e bloccava lo spostamento. Solo per l'app installata (bundle.kind() non None)."""
    explicit = paths.explicit_data_dir()
    if explicit and _same_path(explicit, paths.legacy_data_dir()) \
            and not _same_path(paths.legacy_data_dir(), paths.platform_data_dir()):
        os.environ.pop(paths.DATA_DIR_ENV, None)


def _platform_move_skip_reason() -> Optional[str]:
    """None se ~/.rt va spostata nella cartella di sistema, altrimenti il motivo per non farlo."""
    explicit = paths.explicit_data_dir()
    if explicit:
        if _same_path(explicit, paths.platform_data_dir()):
            return _ALREADY_MOVED  # servizi installati dopo lo spostamento
        return f"scelta con RT_DATA_DIR ({explicit})"
    old_dir = paths.legacy_data_dir()
    new_dir = paths.platform_data_dir()
    if _same_path(old_dir, new_dir) or paths.is_initialized(new_dir):
        return _ALREADY_MOVED
    if not paths.is_initialized(old_dir):
        return _ALREADY_MOVED  # installazione nuova o disposizione 3.x non ancora migrata
    location = paths.read_marker(old_dir).get("location")
    if location and not _same_path(location, old_dir):
        if _same_path(location, new_dir):
            return _ALREADY_MOVED
        return f"{old_dir} rimanda a {location}, che resta dov'è"
    return None


def platform_move_pending() -> bool:
    """True se l'app installata deve ancora spostare ~/.rt nella cartella di sistema e niente
    la blocca in modo permanente: l'app ritenta a ogni apertura, non solo dopo un aggiornamento."""
    from rt.core import bundle
    if bundle.kind() not in (bundle.MACOS, bundle.WINDOWS):
        return False
    explicit = paths.explicit_data_dir()
    if explicit and _same_path(explicit, paths.legacy_data_dir()):
        explicit = None  # ereditata dai servizi: verrà tolta
    if explicit:
        return False
    saved = os.environ.pop(paths.DATA_DIR_ENV, None)
    try:
        if _platform_move_skip_reason() is not None:
            return False
    finally:
        if saved is not None:
            os.environ[paths.DATA_DIR_ENV] = saved
    new_dir = paths.platform_data_dir()
    return not os.path.lexists(new_dir) or (os.path.isdir(new_dir) and not os.listdir(new_dir))


def _migrate_platform_data_dir(say: Callable[[str], None],
                               installed_services: Sequence[str] = ()) -> bool:
    """Sposta la cartella dati dell'app desktop da ~/.rt ad Application Support (macOS) o
    %LOCALAPPDATA%\\RT (Windows). Restituisce False se lo spostamento è rimandato o fallito."""
    from rt.core import bundle
    from rt.core.config import _cached_config
    from rt.db.engine import current_database_url, reset_database_cache, sqlite_file
    from rt.services import service_manager as sm

    if bundle.kind() not in (bundle.MACOS, bundle.WINDOWS):
        return True
    _drop_inherited_legacy_data_dir()
    reason = _platform_move_skip_reason()
    if reason:
        if reason != _ALREADY_MOVED:
            say(f"ℹ️  Cartella dati non spostata: {reason}.")
        return True
    old_dir = paths.legacy_data_dir()
    new_dir = paths.platform_data_dir()
    say(f"📦 Sposto la cartella dati da {old_dir} a {new_dir}...")
    if os.path.isdir(new_dir) and not os.path.islink(new_dir) and not os.listdir(new_dir):
        try:
            os.rmdir(new_dir)  # cartella vuota creata da altri: non deve bloccare per sempre lo spostamento
        except OSError:
            pass
    if os.path.lexists(new_dir):
        say(f"⚠️  Spostamento della cartella dati rimandato al prossimo avvio: {new_dir} esiste già.")
        return False

    reset_database_cache()
    _cached_config.cache_clear()
    db_url = current_database_url()
    if _has_live_running_jobs(db_url):
        say("⏳ Spostamento della cartella dati rimandato al prossimo avvio: ci sono elaborazioni in corso.")
        return False

    marker_path = os.path.join(old_dir, paths.DATA_MARKER)
    with open(marker_path, "rb") as f:
        original_marker_bytes = f.read()

    db_file = sqlite_file(db_url) if db_url else None
    if db_file and not _inside(db_file, old_dir):
        db_file = None
    elif db_file is None and db_url is None and os.path.isfile(os.path.join(old_dir, "rt.db")):
        # RT_DATABASE_URL=off nei test che non usano DB: nessun backup o riscrittura DB
        db_file = None

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_rel = os.path.join("backups", f"prima-dello-spostamento-{stamp}.db")
    old_backup: Optional[str] = None
    if db_file and os.path.isfile(db_file):
        old_backup = os.path.join(old_dir, backup_rel)
        try:
            sqlite_copy(db_file, old_backup)
        except Exception as exc:
            tmp_bak = old_backup + ".tmp"
            if os.path.exists(tmp_bak):
                try:
                    os.remove(tmp_bak)
                except OSError:
                    pass
            say(f"⚠️  Spostamento della cartella dati rimandato al prossimo avvio: {exc}")
            return False

    old_prefixes = _prefix_variants(old_dir)
    closed_streams = _suspend_open_log_streams(old_dir)
    try:
        os.makedirs(os.path.dirname(new_dir), exist_ok=True)
        os.rename(old_dir, new_dir)
    except OSError as exc:
        _reopen_log_streams(closed_streams, old_dir)
        if old_backup and os.path.isfile(old_backup):
            try:
                os.remove(old_backup)
            except OSError:
                pass
        say(f"⚠️  Spostamento della cartella dati rimandato al prossimo avvio: {exc}")
        return False

    _reopen_log_streams(closed_streams, new_dir)
    redirect_created = False
    saved_files_rel: Dict[str, bytes] = {}
    new_db_file = os.path.join(new_dir, os.path.relpath(db_file, old_dir)) if db_file else None
    try:
        paths.write_marker(old_dir, location=new_dir, moved_at=_now())
        redirect_created = True
        reset_database_cache()
        _cached_config.cache_clear()

        _rewrite_config_and_env(new_dir, old_prefixes, saved_files_rel)
        _reset_downloading_components(new_dir, saved_files_rel)
        _cached_config.cache_clear()
        if new_db_file and os.path.isfile(new_db_file):
            new_db_url = current_database_url() or ("sqlite:///" + new_db_file)
            _rewrite_db_paths(new_db_url, old_prefixes, new_dir)
        if sm.supported() and installed_services:
            sm.install(installed_services, start=False, data_dir=new_dir, say=lambda _m: None)
    except Exception as exc:
        reset_database_cache()
        _cached_config.cache_clear()
        rollback_streams = _suspend_open_log_streams(new_dir)
        if redirect_created and os.path.isdir(old_dir):
            shutil.rmtree(old_dir, ignore_errors=True)
        try:
            if os.path.isdir(new_dir) and not os.path.exists(old_dir):
                os.rename(new_dir, old_dir)
        except OSError as rename_exc:
            _reopen_log_streams(rollback_streams or closed_streams, new_dir if os.path.isdir(new_dir) else old_dir)
            say(f"❌ Spostamento della cartella dati non riuscito e ripristino fallito ({rename_exc}): {exc}")
            return False
        with open(os.path.join(old_dir, paths.DATA_MARKER), "wb") as f:
            f.write(original_marker_bytes)
        for rel, content in saved_files_rel.items():
            with open(os.path.join(old_dir, rel), "wb") as f:
                f.write(content)
        if old_backup and os.path.isfile(old_backup) and db_file:
            for suffix in ("-wal", "-shm"):
                if os.path.exists(db_file + suffix):
                    try:
                        os.remove(db_file + suffix)
                    except OSError:
                        pass
            shutil.copy2(old_backup, db_file)
            try:
                os.remove(old_backup)
            except OSError:
                pass
        _reopen_log_streams(rollback_streams or closed_streams, old_dir)
        if sm.supported() and installed_services:
            try:
                sm.install(installed_services, start=False, data_dir=old_dir, say=lambda _m: None)
            except Exception:
                pass
        reset_database_cache()
        _cached_config.cache_clear()
        bundle.apply_env()
        say(f"❌ Spostamento della cartella dati non riuscito, ripristinato tutto in {old_dir}: {exc}")
        return False

    reset_database_cache()
    _cached_config.cache_clear()
    bundle.apply_env()
    say(f"📦 Cartella dati spostata in {new_dir} (rimando lasciato in {old_dir}).")
    return True


def post_update(say: Callable[[str], None] = print,
                confirm: Optional[Callable[[str], bool]] = None) -> bool:
    """Ultimo passo di 'rt -u' e dell'installer, con il codice nuovo: cartella dati (migrazione
    dalla 3.x o spostamento nella cartella di sistema), database migrato e lezioni importate,
    proposta di cifrare le chiavi, servizi aggiornati e riavviati. Idempotente. False se qualcosa
    va sistemato a mano."""
    from rt.core import bundle
    from rt.services import service_manager as sm
    ok = True
    had_services = sm.supported() and bool(sm.installed())
    installed_before = sm.installed() if had_services else []
    if had_services:
        sm.stop()
    plan = None
    from_3x = False
    try:
        if not _migrate_platform_data_dir(say=say, installed_services=installed_before):
            ok = False
        try:
            plan = auto_migrate(say=say)
        except DataDirError as exc:
            say(f"⚠️  {exc}")
            ok = False
        from_3x = plan is not None and bool(plan.steps or plan.redirect_from)
        from rt.core.config import _cached_config, load_env_file
        from rt.db.bootstrap import ensure_database
        from rt.db.engine import DatabaseUnavailable, reset_database_cache
        reset_database_cache()
        _cached_config.cache_clear()
        bundle.apply_env()
        load_env_file(override=True)
        try:
            ensure_database()
            say("🗄  Database aggiornato.")
        except DatabaseUnavailable as exc:
            say(f"❌ {exc}")
            ok = False
        else:
            ok = _convert_folder_lessons(say) and ok
        _offer_secrets_migration(say, confirm)
    finally:
        # i servizi fermati qui sopra ripartono anche se un passo solleva
        if had_services:
            ok = _restart_services(sm, say) and ok
    if not had_services and from_3x and sm.supported() and os.environ.get("RT_NO_SERVICES") != "1":
        # dalla 3.x alla 4.0: API, worker e bot diventano servizi in background (rt web li trova)
        try:
            sm.install(say=say)
        except sm.ServiceError as exc:
            say(f"⚠️  Servizi non installati: {exc} (riprova con 'rt service install').")
    return ok


def _offer_secrets_migration(say: Callable[[str], None], confirm: Optional[Callable[[str], bool]]) -> None:
    """Chi viene dalla 3.x ha le chiavi in chiaro in .env: le cifra se confirm() dice sì
    (terminale interattivo), altrimenti dice come farlo."""
    from rt.services import secrets_service
    env = paths.env_file()
    if not secrets_service.env_needs_migration(env, os.path.join(paths.config_dir(), "general.yaml")):
        return
    if confirm is None:
        say("🔐 Le chiavi API sono ancora in chiaro nel file .env: per cifrarle esegui "
            "'rt secrets init' e poi 'rt secrets migrate'.")
        return
    if not confirm("🔐 Le chiavi API sono in chiaro nel file .env. Le cifro ora (chiave nel portachiavi)?"):
        say("Va bene: puoi farlo quando vuoi con 'rt secrets init' e 'rt secrets migrate'.")
        return
    from rt.security.secrets import SecretStoreError
    try:
        if not secrets_service.store().exists():
            res = secrets_service.init_store()
            if res.master_key_to_show:
                say(f"🔑 Chiave master (salvala in un posto sicuro): {res.master_key_to_show}")
        res = secrets_service.migrate_env(env, secrets_service.secret_names_from_config(), strip_env=True)
        say("✅ Chiavi cifrate in config/secrets.enc e tolte da .env"
            + (f" (copia del vecchio .env: {res.backup_path})." if res.backup_path else "."))
    except SecretStoreError as exc:
        say(f"⚠️  Cifratura non riuscita: {exc}")
