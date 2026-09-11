"""
tests/test_typing_imports_portability.py
Guardia di portabilità: verifica che ogni nome usato da 'typing' (Optional, List, Dict, ecc.)
come annotazione di tipo sia importato esplicitamente nel file che lo usa.

Motivazione: Python 3.14 valuta le annotazioni di funzione in modo differito di default
(PEP 649), quindi un file che usa 'Optional[str]' senza 'from typing import Optional'
funziona per puro caso in quell'ambiente, ma solleva NameError all'import su Python <3.14
(dove le annotazioni sono valutate eagerly). Questo bug si è già presentato tre volte in
round di sviluppo diversi (rt/pipeline/review_science.py, rt/telegram/daemon.py,
rt/pipeline/recall_session.py) prima di essere trovato a mano ogni volta — questo test lo
cattura automaticamente per qualunque file futuro.
"""
import ast
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RT_DIR = os.path.join(REPO_ROOT, "rt")

TYPING_NAMES = {
    "Optional", "List", "Dict", "Tuple", "Set", "Union", "Any", "Callable",
    "Iterable", "Iterator", "Sequence", "Mapping", "Type", "FrozenSet",
}


def _find_python_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _missing_typing_imports(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=path)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "typing":
                    imported.add("typing")

    if "typing" in imported:
        return set()  # 'import typing' + typing.Optional-style usage is always qualified, safe

    used = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, node):
            if node.id in TYPING_NAMES:
                used.add(node.id)
            self.generic_visit(node)

    Visitor().visit(tree)
    return used - imported


@pytest.mark.parametrize("path", sorted(_find_python_files(RT_DIR)))
def test_no_missing_typing_imports(path):
    missing = _missing_typing_imports(path)
    rel = os.path.relpath(path, REPO_ROOT)
    assert not missing, (
        f"{rel} usa {sorted(missing)} come annotazione senza importarli da 'typing'. "
        f"Funziona solo su Python 3.14+ (PEP 649, valutazione differita delle annotazioni) "
        f"e solleverebbe NameError su Python <3.14. Aggiungi 'from typing import "
        f"{', '.join(sorted(missing))}' in cima al file."
    )
