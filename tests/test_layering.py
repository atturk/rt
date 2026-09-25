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
"""
import ast
import os
from typing import Set


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PACKAGES = ("rt/pipeline", "rt/core", "rt/services")
FORBIDDEN_MODULES = ("textual", "rich.prompt", "questionary", "rt.telegram", "rt.tui", "rt.web")



def _is_forbidden(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in FORBIDDEN_MODULES) or \
        module.split(".")[0] == "textual_diff_view"


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


def collect_violations() -> Set[str]:
    found: Set[str] = set()
    for pkg in ENGINE_PACKAGES:
        base = os.path.join(PROJECT_ROOT, pkg)
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if fn.endswith(".py"):
                    path = os.path.join(dirpath, fn)
                    rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
                    found |= _file_violations(path, rel)
    return found


def test_engine_is_ui_free():
    found = sorted(collect_violations())
    assert not found, "Dipendenze UI nel motore (rt/pipeline, rt/core):\n" + "\n".join(found)
