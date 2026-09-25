#!/usr/bin/env python3
"""Esporta lo schema OpenAPI dell'API in docs/openapi.json (usato dal client della SPA).

Uso: python scripts/export_openapi.py [--check]
--check esce con codice 1 se il file salvato non coincide con lo schema attuale.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TARGET = os.path.join(ROOT, "docs", "openapi.json")


def render() -> str:
    from rt.api.app import create_app
    schema = create_app().openapi()
    schema["info"]["version"] = "rt"  # la versione cambia a ogni release: fuori dal confronto
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv) -> int:
    text = render()
    if "--check" in argv:
        try:
            with open(TARGET, "r", encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            current = ""
        if current != text:
            print("docs/openapi.json non aggiornato: esegui python scripts/export_openapi.py")
            return 1
        return 0
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Schema OpenAPI scritto in {os.path.relpath(TARGET, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
