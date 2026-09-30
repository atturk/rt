"""
tests/test_layering.py
Test architetturale (RT4-A0): il motore (rt/pipeline, rt/core) non deve dipendere dalle
interfacce utente né bloccarsi sul terminale.

Segnala in ogni file di rt/pipeline, rt/core e rt/services:
  - import di textual, rich.prompt, questionary, rt.telegram, rt.tui, rt.web (anche dentro
    funzioni);
  - chiamate a input() e sys.exit().

Dalla chiusura della fase A (RT4-A6) il test è bloccante e senza eccezioni: la UI vive in
rt/tui, rt/telegram, rt/web e negli adattatori CLI (rt/cli*.py); il motore passa da
rt/services.

Inoltre motore, servizi, storage, DB, LLM, sicurezza e bot Telegram non importano le
interfacce rt.api e rt.cli (rt/cli*.py): i servizi sollevano errori di dominio
(rt.services.errors) che l'API traduce in risposte HTTP, e la logica condivisa (es. i log
di 'rt logs') vive in rt/services.
"""
import ast
import os
from typing import Set


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PACKAGES = ("rt/pipeline", "rt/core", "rt/services")
FORBIDDEN_MODULES = ("textual", "rich.prompt", "questionary", "rt.telegram", "rt.tui", "rt.web")

# Pacchetti che non devono conoscere le interfacce (API REST e CLI).
INTERFACE_FREE_PACKAGES = ENGINE_PACKAGES + ("rt/storage", "rt/db", "rt/llm", "rt/security", "rt/telegram")


def _is_forbidden(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in FORBIDDEN_MODULES) or \
        module.split(".")[0] == "textual_diff_view"


def _is_interface(module: str) -> bool:
    """rt.api (e sottomoduli), rt.cli e gli adattatori rt.cli_* (rt.cli_jobs, rt.cli_prompts...)."""
    return module == "rt.api" or module.startswith("rt.api.") or module == "rt.cli" or \
        module.startswith(("rt.cli.", "rt.cli_"))


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            if node.module == "rt":  # from rt import api / from rt import cli
                for alias in node.names:
                    yield f"rt.{alias.name}"


def _interface_violations(path: str, rel: str) -> Set[str]:
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=rel)
    return {f"{rel}: import {mod}" for mod in _imported_modules(tree) if _is_interface(mod)}


def _file_violations(path: str, rel: str) -> Set[str]:
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=rel)
    found: Set[str] = set()
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules = [node.module]
            # "from rt import telegram" / "from rt.telegram import x"
            modules += [f"{node.module}.{a.name}" for a in node.names if node.module in ("rt", "rich")]
        for mod in modules:
            if _is_forbidden(mod):
                found.add(f"{rel}: import {mod}")
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "input":
                found.add(f"{rel}: call input()")
            elif isinstance(fn, ast.Attribute) and fn.attr == "exit" and \
                    isinstance(fn.value, ast.Name) and fn.value.id == "sys":
                found.add(f"{rel}: call sys.exit()")
    return found


def _python_files(packages):
    for pkg in packages:
        base = os.path.join(PROJECT_ROOT, pkg)
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if fn.endswith(".py"):
                    path = os.path.join(dirpath, fn)
                    yield path, os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")


def collect_violations() -> Set[str]:
    found: Set[str] = set()
    for path, rel in _python_files(ENGINE_PACKAGES):
        found |= _file_violations(path, rel)
    return found


def collect_interface_violations() -> Set[str]:
    found: Set[str] = set()
    for path, rel in _python_files(INTERFACE_FREE_PACKAGES):
        found |= _interface_violations(path, rel)
    return found


def test_engine_is_ui_free():
    found = sorted(collect_violations())
    assert not found, "Dipendenze UI nel motore (rt/pipeline, rt/core):\n" + "\n".join(found)


def test_engine_and_services_do_not_import_interfaces():
    found = sorted(collect_interface_violations())
    assert not found, "Il motore o i servizi importano le interfacce (rt.api, rt.cli):\n" + "\n".join(found)


def test_interface_check_catches_every_import_form():
    import textwrap
    tree = ast.parse(textwrap.dedent('''
        import rt.api.errors
        from rt.api.errors import ApiError
        from rt import cli
        from rt.cli_jobs import run_queued
        def f():
            from rt.cli import cmd_logs
        from rt.services.errors import ServiceError
        from rt.client import x
    '''))
    found = {m for m in _imported_modules(tree) if _is_interface(m)}
    assert found == {"rt.api.errors", "rt.cli", "rt.cli_jobs"}
