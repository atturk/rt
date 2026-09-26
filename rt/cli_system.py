"""
rt.cli_system
Comandi di installazione e manutenzione (fase G): 'rt data', 'rt service', 'rt backup',
'rt restore', 'rt doctor', 'rt uninstall'. La logica sta in rt.services.data_service,
service_manager, backup_service e doctor_service.
"""
import argparse
import json
import os
import shutil
import sys

from rt.core import paths


def _fail(message: str, code: int = 1) -> None:
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(code)


def _ask_yes(question: str) -> bool:
    return input(f"{question} [S/n] ").strip().lower() not in ("n", "no")


# ---------------------------------------------------------------- rt data

def configure_data_parser(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="data_command", required=False, title="Sottocomandi")
    sub.add_parser("status", help="Mostra dove stanno configurazione, segreti, database e media (default)")
    p_init = sub.add_parser("init", help="Crea la cartella dati (RT_DATA_DIR o ~/.rt)")
    p_init.add_argument("--path", default=None, help="Cartella da usare (default: RT_DATA_DIR o ~/.rt)")
    p_mig = sub.add_parser("migrate", help="Sposta i dati di un'installazione 3.x nella cartella dati")
    p_mig.add_argument("--dry-run", action="store_true", help="Mostra cosa verrebbe spostato, senza toccare nulla")
    sub.add_parser("post-update", help=argparse.SUPPRESS)  # chiamato da 'rt -u' con il codice nuovo


def cmd_data(args: argparse.Namespace) -> None:
    from rt.services import data_service
    command = getattr(args, "data_command", None) or "status"
    if command == "init":
        target = data_service.init_data_dir(args.path)
        print(f"✅ Cartella dati pronta: {target}")
        return
    if command == "post-update":
        interactive = sys.stdin.isatty() and os.environ.get("RT_NONINTERACTIVE") != "1"
        sys.exit(0 if data_service.post_update(confirm=_ask_yes if interactive else None) else 1)
    if command == "migrate":
        try:
            plan = data_service.migrate(dry_run=args.dry_run)
        except data_service.DataDirError as exc:
            _fail(str(exc))
        if plan.already_active:
            print(f"✅ La cartella dati {plan.data_dir} è già in uso: niente da migrare.")
            return
        for note in plan.notes:
            print(f"ℹ️  {note}")
        if args.dry_run:
            if not plan.steps:
                print(f"Niente da spostare: 'rt data migrate' creerà solo la cartella dati {plan.data_dir}.")
            for step in plan.steps:
                verb = {"copy": "copia", "move": "sposta", "sqlite-backup": "copia coerente"}[step.action]
                print(f"• {step.what}: {verb} {step.source} → {step.target}")
            return
        if not plan.steps:
            data_service.init_data_dir(plan.data_dir)
        print(f"✅ Cartella dati in uso: {plan.data_dir}")
        return
    from rt.db.engine import current_database_url, sqlite_file
    from rt.security.secrets import default_store_path
    active = paths.active_data_dir()
    url = current_database_url()
    print(f"Cartella dati:   {active or 'nessuna (disposizione 3.x: esegui rt data migrate)'}")
    print(f"Configurazione:  {paths.config_dir()}")
    print(f"File .env:       {paths.env_file()}")
    print(f"Segreti cifrati: {default_store_path()}")
    print(f"Database:        {(sqlite_file(url) or url.split('@')[-1]) if url else 'disattivato'}")
    if url:
        from rt.db.engine import get_database
        from rt.storage import fs
        db = get_database()
        if db is not None:
            print(f"Media:           {fs.media_dir(db)}")
    print(f"Log dei servizi: {os.path.join(paths.data_dir(), 'logs')}")


# ---------------------------------------------------------------- rt service

def configure_service_parser(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="service_command", required=False, title="Sottocomandi")
    for name, text in (("status", "Stato dei servizi (default)"), ("install", "Installa e avvia i servizi launchd"),
                       ("uninstall", "Ferma e rimuove i servizi"), ("start", "Avvia i servizi installati"),
                       ("stop", "Ferma i servizi (ripartono al prossimo login)"), ("restart", "Riavvia i servizi")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("names", nargs="*", metavar="servizio", help="api, worker, bot (default: tutti)")
        if name == "install":
            sp.add_argument("--no-bot", action="store_true", help="Non installare il servizio del bot Telegram")
            sp.add_argument("--no-start", action="store_true", help="Scrive i file ma non avvia i servizi")


def cmd_service(args: argparse.Namespace) -> None:
    from rt.services import service_manager as sm
    command = getattr(args, "service_command", None) or "status"
    names = list(getattr(args, "names", None) or [])
    unknown = [n for n in names if n not in sm.SERVICES]
    if unknown:
        _fail(f"Servizi sconosciuti: {', '.join(unknown)} (disponibili: {', '.join(sm.SERVICES)})", 2)
    try:
        if command == "status":
            if not sm.supported():
                print("I servizi launchd esistono solo su macOS (su Linux: docker compose, docs/SELF_HOSTING.md).")
            for name in (names or sm.SERVICES):
                st = sm.status(name)
                state = ("attivo" + (f", pid {st.pid}" if st.pid else "")) if st.running else (
                    "caricato, fermo" if st.loaded else ("installato, fermo" if st.installed else "non installato"))
                print(f"{name:<7} {sm.DESCRIPTIONS[name]:<16} {state}")
            print(f"\nWeb app: http://127.0.0.1:{sm.api_port()} "
                  + ("(risponde)" if sm.api_is_up() else "(non risponde)"))
            return
        if command == "install":
            chosen = names or [n for n in sm.SERVICES if not (n == "bot" and args.no_bot)]
            sm.install(chosen, start=not args.no_start)
            return
        if command == "uninstall":
            if not sm.uninstall(names or None):
                print("Nessun servizio installato.")
            return
        done = {"start": sm.start, "stop": sm.stop, "restart": sm.restart}[command](names or None)
        verb = {"start": "avviati", "stop": "fermati", "restart": "riavviati"}[command]
        print(f"✅ Servizi {verb}: {', '.join(done)}" if done else "Nessun servizio da gestire.")
    except sm.ServiceError as exc:
        _fail(str(exc))


# ---------------------------------------------------------------- rt backup / restore

def configure_backup_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dest", default=None,
                   help="Cartella dei backup (default: RT_BACKUP_DIR o <cartella dati>/backups; meglio un disco esterno)")
    p.add_argument("--list", action="store_true", help="Elenca i backup nella cartella")
    p.add_argument("--allow-missing", action="store_true",
                   help="Salva anche se alcuni media referenziati nel database mancano")


def cmd_backup(args: argparse.Namespace) -> None:
    from rt.services import backup_service as bs
    if args.list:
        found = bs.list_backups(args.dest)
        if not found:
            print(f"Nessun backup in {args.dest or bs.default_dest()}.")
        for b in found:
            print(f"{b['path']}  ({b['created']}, RT {b['rt_version']}, {b['media']} media)")
        return
    try:
        res = bs.create_backup(args.dest, allow_missing=args.allow_missing)
    except bs.BackupError as exc:
        _fail(str(exc))
    print(f"✅ Backup completo: {res.path}")
    if res.missing:
        print(f"⚠️  {len(res.missing)} media referenziati mancavano e non sono nel backup.")
    if res.folder_lessons:
        print(f"⚠️  {len(res.folder_lessons)} lezioni sono ancora in cartella e non sono nel backup: "
              "spostale nel database con 'rt db migrate-storage'.")
    if res.master_key_warning:
        print(res.master_key_warning)


def configure_restore_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", help="Cartella rt-backup-<data>, o la cartella dei backup (usa il più recente)")
    p.add_argument("--yes", action="store_true", help="Non chiedere conferma")


def cmd_restore(args: argparse.Namespace) -> None:
    from rt.services import backup_service as bs
    try:
        snap = bs.resolve_snapshot(args.source)
    except bs.BackupError as exc:
        _fail(str(exc))
    if not args.yes:
        if not sys.stdin.isatty():
            _fail("Conferma richiesta: rilancia con --yes.")
        answer = input(f"Ripristino {snap}: database, configurazione e .env attuali vengono messi da parte. "
                       "Continuare? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sì", "y", "yes"):
            print("Annullato.")
            return
    try:
        bs.restore_backup(snap)
    except bs.BackupError as exc:
        _fail(str(exc))
    print("✅ Ripristino completato. Riavvia i servizi con 'rt service start'.")
    warning = bs.master_key_warning()
    if warning:
        print("🔑 Se questo Mac è nuovo, reimposta la chiave master (RT_MASTER_KEY o portachiavi) "
              "per leggere i segreti ripristinati.")


# ---------------------------------------------------------------- rt doctor

def configure_doctor_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="Output JSON")


def cmd_doctor(args: argparse.Namespace) -> None:
    from rt.services.doctor_service import FAIL, OK, WARN, run_checks, summary
    checks = run_checks()
    worst = summary(checks)
    if args.json:
        print(json.dumps({"status": worst or OK, "checks": [c.as_dict() for c in checks]}, ensure_ascii=False, indent=2))
    else:
        icons = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
        for c in checks:
            print(f"{icons[c.status]} {c.name}: {c.message}")
            if c.fix and c.status != OK:
                print(f"   → {c.fix}")
        print()
        print({None: "Tutto a posto.", WARN: "Funziona, con qualche avviso.",
               FAIL: "Ci sono problemi da sistemare (vedi →)."}[worst])
    if worst == FAIL:
        sys.exit(1)


# ---------------------------------------------------------------- rt uninstall

def configure_uninstall_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--purge-data", action="store_true",
                   help="Elimina anche la cartella dati (database, media, configurazione; restano i backup)")
    p.add_argument("--yes", action="store_true", help="Non chiedere conferma")


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Rimuove servizi, ambiente Python e web app compilata; dati, lezioni e backup restano
    (salvo --purge-data, che conserva comunque <cartella dati>/backups)."""
    from rt.services import service_manager as sm
    root = paths.project_root()
    data = paths.active_data_dir()
    if not args.yes:
        if not sys.stdin.isatty():
            _fail("Conferma richiesta: rilancia con --yes.")
        what = "servizi, ambiente Python (.venv) e web app"
        if args.purge_data:
            what += f", e la cartella dati {data} (database, media, configurazione)"
        answer = input(f"Rimuovo {what}. Continuare? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sì", "y", "yes"):
            print("Annullato.")
            return
        if args.purge_data and input("Scrivi ELIMINA per cancellare database e media: ").strip() != "ELIMINA":
            print("Annullato.")
            return
    sm.uninstall(say=print)
    _remove_path_line()
    for rel in ("rt/spa", ".venv"):
        target = os.path.join(root, rel)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
            print(f"🗑  Rimosso {target}")
    if args.purge_data and data:
        for name in os.listdir(data):
            if name != "backups":
                target = os.path.join(data, name)
                if os.path.isdir(target) and not os.path.islink(target):
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    os.remove(target)
        print(f"🗑  Cartella dati svuotata (restano i backup in {os.path.join(data, 'backups')}).")
    print("\n✅ RT disinstallato.")
    if data and not args.purge_data:
        print(f"   Restano i tuoi dati: {data} (database, media, configurazione, backup).")
    print(f"   Resta il codice in {root}: puoi cancellare la cartella a mano.")
    print("   Per reinstallare: rilancia il comando di installazione, ritrova i dati com'erano.")


def _remove_path_line() -> None:
    """Toglie da ~/.zshrc e ~/.bash_profile le righe aggiunte da install.sh."""
    bin_dir = os.path.join(paths.project_root(), "bin")
    for profile in (os.path.expanduser("~/.zshrc"), os.path.expanduser("~/.bash_profile")):
        if not os.path.isfile(profile):
            continue
        with open(profile, encoding="utf-8") as f:
            lines = f.readlines()
        kept = [line for line in lines if bin_dir not in line and line.strip() != "# Aggiunto da RT install.sh"]
        if kept != lines:
            with open(profile, "w", encoding="utf-8") as f:
                f.writelines(kept)
            print(f"🗑  Tolto RT dal PATH in {profile}")
