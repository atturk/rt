"""
rt.cli_secrets
Adattatore CLI di 'rt secrets' (RT4-C2): argomenti, conferme e stampa. La logica sta in
rt.services.secrets_service. I valori dei segreti non vengono mai stampati né accettati come
argomento (resterebbero nella cronologia della shell): 'set' li chiede senza eco o li legge
da stdin con --stdin.
"""
import argparse
import getpass
import sys

from rt.security.secrets import MASTER_KEY_ENV, SecretStoreError


def configure_secrets_parser(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="secrets_command", required=True, title="Sottocomandi")

    p_init = sub.add_parser("init", help="Crea la chiave master e l'archivio cifrato config/secrets.enc")
    p_init.add_argument("--print-key", action="store_true",
                        help=f"Mostra la chiave master una volta (per {MASTER_KEY_ENV}) anche se è nel portachiavi")
    p_init.add_argument("--no-keyring", action="store_true",
                        help=f"Non usare il portachiavi di sistema: la chiave va in {MASTER_KEY_ENV}")

    p_mig = sub.add_parser("migrate", help="Sposta le chiavi dal file .env all'archivio cifrato")
    p_mig.add_argument("--yes", action="store_true", help="Togli i valori da .env senza chiedere conferma")
    p_mig.add_argument("--keep-env", action="store_true", help="Copia nell'archivio ma lascia .env com'è")

    sub.add_parser("list", help="Elenca i segreti salvati (solo nomi e data, mai i valori)")

    p_set = sub.add_parser("set", help="Salva o sostituisce un segreto (il valore viene chiesto senza eco)")
    p_set.add_argument("name", help="Nome della variabile, es. OPENROUTER_API_KEY")
    p_set.add_argument("--stdin", action="store_true", help="Legge il valore da stdin (per script)")

    p_unset = sub.add_parser("unset", help="Rimuove un segreto dall'archivio")
    p_unset.add_argument("name")

    p_rot = sub.add_parser("rotate", help="Ricifra l'archivio con una chiave master nuova")
    p_rot.add_argument("--no-keyring", action="store_true",
                       help=f"Mostra la chiave nuova invece di salvarla nel portachiavi (per chi usa {MASTER_KEY_ENV})")


def _print_key_once(key: str) -> None:
    print("\n🔑 Chiave master (mostrata solo ora, conservala in un posto sicuro):")
    print(f"   {key}")
    print(f"   Per usarla: export {MASTER_KEY_ENV}='<chiave>' (es. nel profilo della shell o nel servizio launchd).")
    print("   Senza questa chiave i segreti dell'archivio non si possono più leggere.\n")


def _cmd_init(args: argparse.Namespace) -> None:
    from rt.services import secrets_service
    res = secrets_service.init_store(use_keyring=not args.no_keyring, show_key=args.print_key)
    print(f"✅ Archivio cifrato creato: {res.path}")
    if res.key_in_keyring:
        print("🔐 Chiave master salvata nel portachiavi di sistema (servizio 'rt').")
    elif not res.master_key_to_show:
        print(f"🔐 Archivio cifrato con la chiave già presente in {MASTER_KEY_ENV}.")
    else:
        print("⚠️  Portachiavi di sistema non usato o non disponibile.")
    if res.master_key_to_show:
        _print_key_once(res.master_key_to_show)
    print("Prossimo passo: 'rt secrets migrate' per spostare le chiavi dal file .env.")


def _cmd_migrate(args: argparse.Namespace) -> None:
    from rt.services import config_service, secrets_service
    env_path = config_service.env_path()
    names = secrets_service.secret_names_from_config()
    plan = secrets_service.plan_migration(env_path, names)
    if not plan.removable:
        print(f"Nessun segreto da migrare in {env_path}.")
        return
    for name in plan.to_store:
        print(f"  → {name}: da copiare nell'archivio")
    for name in plan.already_stored:
        print(f"  = {name}: già nell'archivio")
    for name in plan.conflicts:
        print(f"  ! {name}: nell'archivio c'è un valore diverso, resta quello dell'archivio")
    strip = False
    if not args.keep_env:
        if args.yes:
            strip = True
        elif sys.stdin.isatty():
            answer = input(f"Dopo la copia (verificata) togliere questi valori da {env_path}? "
                           "Verrà creato un backup .env.bak-<data>. [s/N] ")
            strip = answer.strip().lower() in ("s", "si", "sì", "y", "yes")
    res = secrets_service.migrate_env(env_path, names, strip_env=strip)
    print(f"✅ {len(plan.to_store)} segreti copiati e verificati nell'archivio cifrato.")
    if res.backup_path:
        print(f"🗄️  Backup del vecchio .env: {res.backup_path} (permessi 600; cancellalo quando hai verificato).")
        print(f"🧹 Tolti da .env: {', '.join(res.stripped)}")
    else:
        print("ℹ️  .env lasciato intatto: i valori dell'archivio hanno comunque la precedenza.")


def _cmd_list(_args: argparse.Namespace) -> None:
    from rt.services import secrets_service
    items = secrets_service.list_secrets()
    if not items:
        print("Archivio vuoto.")
        return
    width = max(len(n) for n in items)
    for name, meta in items.items():
        print(f"{name.ljust(width)}  {meta.get('updated_at', '')}")


def _cmd_set(args: argparse.Namespace) -> None:
    from rt.services import secrets_service
    if args.stdin:
        value = sys.stdin.readline().strip()
    else:
        value = getpass.getpass(f"Valore per {args.name} (non verrà mostrato): ").strip()
    if not value:
        raise SecretStoreError("Valore vuoto: nulla è stato salvato.")
    secrets_service.set_secret(args.name, value)
    print(f"✅ {args.name} salvato nell'archivio cifrato.")


def _cmd_unset(args: argparse.Namespace) -> None:
    from rt.services import secrets_service
    if secrets_service.unset_secret(args.name):
        print(f"✅ {args.name} rimosso dall'archivio.")
    else:
        print(f"{args.name} non è nell'archivio.")


def _cmd_rotate(args: argparse.Namespace) -> None:
    from rt.services import secrets_service
    res = secrets_service.rotate_key(use_keyring=False if args.no_keyring else None)
    print(f"✅ Archivio {res.path} ricifrato con una chiave nuova.")
    if res.key_in_keyring:
        print("🔐 Portachiavi aggiornato con la nuova chiave.")
    if res.master_key_to_show:
        print(f"⚠️  Aggiorna {MASTER_KEY_ENV} con la chiave nuova: la vecchia non apre più l'archivio.")
        _print_key_once(res.master_key_to_show)


_HANDLERS = {
    "init": _cmd_init,
    "migrate": _cmd_migrate,
    "list": _cmd_list,
    "set": _cmd_set,
    "unset": _cmd_unset,
    "rotate": _cmd_rotate,
}


def cmd_secrets(args: argparse.Namespace) -> None:
    try:
        _HANDLERS[args.secrets_command](args)
    except SecretStoreError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
