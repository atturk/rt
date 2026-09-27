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
    <dati>/.rt_telegram/     stato del bot
    <dati>/logs/             log dei servizi
    <dati>/backups/          backup ('rt backup') e copie di sicurezza delle migrazioni

La migrazione copia config e segreti, copia il DB con l'API di backup di SQLite (copia
coerente), sposta media/ e solo alla fine attiva la cartella. Gli originali restano
rinominati (*.migrato-<data>): niente viene cancellato. Si rifiuta se API, worker o bot
sono attivi, perché scriverebbero nel DB vecchio.
"""
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from rt.core import paths

SUBDIRS = ("config", "media", "logs", "backups")


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
        _copy_missing(example, config)
    env = os.path.join(target, ".env")
    if not os.path.exists(env):
        with open(env, "w", encoding="utf-8") as f:
            f.write("# RT: variabili non segrete. Chiavi e token stanno cifrati in config/secrets.enc\n")
        os.chmod(env, 0o600)
    if not paths.is_initialized(target):
        paths.write_marker(target, created=_now(), from_layout="new")
        say(f"📁 Cartella dati creata: {target}")
    return target


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
    """Processi di RT che scrivono nel DB adesso: bot, worker, API. Vuota se nessuno."""
    out = []
    if _bot_pid() is not None:
        out.append("bot Telegram")
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


def _bot_pid() -> Optional[int]:
    """PID del bot Telegram vivo (stesso file di rt.telegram.daemon_status, che il service
    layer non importa)."""
    try:
        with open(os.path.join(paths.data_dir(), "telegram_daemon.pid"), encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except PermissionError:
        return pid
    except (OSError, ValueError):
        return None


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


def post_update(say: Callable[[str], None] = print,
                confirm: Optional[Callable[[str], bool]] = None) -> bool:
    """Ultimo passo di 'rt -u' e dell'installer, con il codice nuovo: cartella dati (migrazione
    dalla 3.x), database migrato e lezioni importate, proposta di cifrare le chiavi, servizi
    aggiornati e riavviati. Idempotente. False se qualcosa va sistemato a mano."""
    from rt.services import service_manager as sm
    ok = True
    had_services = sm.supported() and bool(sm.installed())
    if had_services:
        sm.stop()
    plan = None
    try:
        plan = auto_migrate(say=say)
    except DataDirError as exc:
        say(f"⚠️  {exc}")
        ok = False
    from_3x = plan is not None and bool(plan.steps or plan.redirect_from)
    from rt.core.config import load_env_file
    from rt.db.bootstrap import ensure_database
    from rt.db.engine import DatabaseUnavailable, reset_database_cache
    reset_database_cache()
    load_env_file(override=True)
    try:
        ensure_database(on_progress=say)
        say("🗄  Database aggiornato.")
    except DatabaseUnavailable as exc:
        say(f"❌ {exc}")
        ok = False
    _offer_secrets_migration(say, confirm)
    if had_services:
        try:
            sm.install(sm.installed(), start=True, say=lambda _m: None)
            say("▶️  Servizi aggiornati e riavviati.")
        except sm.ServiceError as exc:
            say(f"⚠️  Servizi non riavviati: {exc}")
            ok = False
    elif from_3x and sm.supported() and os.environ.get("RT_NO_SERVICES") != "1":
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
