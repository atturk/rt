"""
tests/test_layering.py
Test architetturale (RT4-A0): il motore (rt/pipeline, rt/core) non deve dipendere dalle
interfacce utente né bloccarsi sul terminale.

Segnala in ogni file di rt/pipeline e rt/core:
  - import di textual, rich.prompt, questionary, rt.telegram, rt.tui, rt.web (anche dentro
    funzioni);
  - chiamate a input() e sys.exit().

ALLOWLIST elenca le violazioni esistenti quando il test è stato introdotto: ogni task della
fase A ne rimuove alcune. Una violazione nuova fa fallire il test, e anche una voce
dell'allowlist che non corrisponde più al codice (così l'elenco resta esatto).
test_engine_is_ui_free è xfail finché l'allowlist non è vuota (RT4-A6).
"""
import ast
import os
from typing import Set

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PACKAGES = ("rt/pipeline", "rt/core")
FORBIDDEN_MODULES = ("textual", "rich.prompt", "questionary", "rt.telegram", "rt.tui", "rt.web")

# Formato: "<file>: import <modulo>" | "<file>: call input()" | "<file>: call sys.exit()".
ALLOWLIST: Set[str] = {
    "rt/core/version.py: call sys.exit()",
    "rt/pipeline/configure.py: import questionary",
    "rt/pipeline/configure.py: import textual.app",
    "rt/pipeline/configure.py: import textual.widgets",
    "rt/pipeline/issue_review.py: import rt.telegram",
    "rt/pipeline/issue_review.py: import rt.telegram.audio_sent",
    "rt/pipeline/issue_review.py: import rt.telegram.config",
    "rt/pipeline/issue_review.py: import textual.app",
    "rt/pipeline/issue_review.py: import textual.containers",
    "rt/pipeline/issue_review.py: import textual.widgets",
    "rt/pipeline/issue_review.py: import textual_diff_view",
    "rt/pipeline/recall_session.py: call input()",
    "rt/pipeline/recall_session.py: import rt.telegram",
    "rt/pipeline/recall_session.py: import rt.telegram.client",
    "rt/pipeline/recall_session.py: import rt.telegram.config",
    "rt/pipeline/recall_session.py: import textual.app",
    "rt/pipeline/recall_session.py: import textual.widgets",
}


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


def test_no_new_layering_violations():
    new = sorted(collect_violations() - ALLOWLIST)
    assert not new, "Nuove dipendenze UI nel motore (rt/pipeline, rt/core):\n" + "\n".join(new)


def test_allowlist_has_no_stale_entries():
    stale = sorted(ALLOWLIST - collect_violations())
    assert not stale, "Voci dell'allowlist risolte, rimuovile da ALLOWLIST:\n" + "\n".join(stale)


@pytest.mark.xfail(strict=True, reason="Fase A in corso: l'allowlist si svuota in RT4-A6")
def test_engine_is_ui_free():
    assert not collect_violations()
