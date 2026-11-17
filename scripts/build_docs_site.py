#!/usr/bin/env python3
"""Compila il sito di RT per GitHub Pages.

Struttura pubblicata (cartella ``site/``):
- ``index.html``, ``download.html`` e risorse: landing page e pagina Scarica, da ``docs/sito/``;
- ``guida/``: la guida di ``docs/guida/`` compilata con MkDocs (``mkdocs.yml``).

Nelle pagine di ``docs/sito/`` ``{{VERSIONE}}`` diventa la versione in ``VERSION`` e
``<!-- DONAZIONI_SEGNAPOSTO -->`` il pulsante per sostenere RT, se ``DONAZIONI_URL`` è impostato.
"""
import argparse
import html
import os
import shutil
import subprocess
import sys

import yaml

# Assicura che rt sia importabile
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from rt.core.donazioni import DONAZIONI_URL

SEGNAPOSTO_DONAZIONI = "<!-- DONAZIONI_SEGNAPOSTO -->"
SITO_HOME = "https://atturk.github.io/rt/"


def read_guide_index(guida_src: str) -> list[str]:
    index_file = os.path.join(guida_src, "indice.yml")
    if not os.path.isfile(index_file):
        return []
    with open(index_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    files = []
    for item in data:
        slug = item.get("file") if isinstance(item, dict) else item
        if slug:
            files.append(str(slug))
    return files


def read_version() -> str:
    with open(os.path.join(ROOT_DIR, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def donazioni_html(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return f'          <a class="btn pri" href="{html.escape(url, quote=True)}">Sostieni RT</a>'


def prepare_site_docs(target_dir: str = "site_docs", update_mkdocs: bool = True) -> None:
    """Copia in target_dir le pagine della guida elencate in indice.yml e le immagini;
    con update_mkdocs aggiorna la nav di mkdocs.yml."""
    os.makedirs(target_dir, exist_ok=True)
    guida_src = os.path.join(ROOT_DIR, "docs", "guida")
    nav_guida = []

    for slug in read_guide_index(guida_src):
        src_md = os.path.join(guida_src, f"{slug}.md")
        if not os.path.isfile(src_md):
            continue
        shutil.copy2(src_md, os.path.join(target_dir, f"{slug}.md"))
        title = slug
        with open(src_md, "r", encoding="utf-8") as f:
            for line in f:
                trimmed = line.strip()
                if trimmed.startswith("# "):
                    title = trimmed[2:].strip()
                    break
        nav_guida.append({title: f"{slug}.md"})

    immagini_src = os.path.join(guida_src, "immagini")
    if os.path.isdir(immagini_src):
        immagini_target = os.path.join(target_dir, "immagini")
        os.makedirs(immagini_target, exist_ok=True)
        for name in os.listdir(immagini_src):
            src_file = os.path.join(immagini_src, name)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, os.path.join(immagini_target, name))

    if update_mkdocs:
        mkdocs_file = os.path.join(ROOT_DIR, "mkdocs.yml")
        with open(mkdocs_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        config["nav"] = nav_guida + [{"← Sito di RT": SITO_HOME}]
        with open(mkdocs_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)


def prepare_landing(out_dir: str, donazioni_url: str | None = None) -> None:
    """Copia docs/sito in out_dir, sostituendo versione e segnaposto delle donazioni nelle pagine HTML."""
    if donazioni_url is None:
        donazioni_url = DONAZIONI_URL
    sito_src = os.path.join(ROOT_DIR, "docs", "sito")
    versione = read_version()
    for dirpath, _dirs, files in os.walk(sito_src):
        rel = os.path.relpath(dirpath, sito_src)
        dest_dir = os.path.normpath(os.path.join(out_dir, rel))
        os.makedirs(dest_dir, exist_ok=True)
        for name in files:
            if name == "README.md":
                continue
            src = os.path.join(dirpath, name)
            dest = os.path.join(dest_dir, name)
            if name.endswith(".html"):
                with open(src, encoding="utf-8") as f:
                    content = f.read()
                content = content.replace("{{VERSIONE}}", versione)
                content = content.replace(SEGNAPOSTO_DONAZIONI, donazioni_html(donazioni_url))
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                shutil.copy2(src, dest)
    # GitHub Pages: niente elaborazione Jekyll
    open(os.path.join(out_dir, ".nojekyll"), "w").close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Costruisce il sito di RT (landing page + guida MkDocs)")
    parser.add_argument("--prepare-only", action="store_true", help="Prepara solo i file in site_docs senza lanciare mkdocs")
    args = parser.parse_args()

    target_dir = os.path.join(ROOT_DIR, "site_docs")
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    prepare_site_docs(target_dir)

    if args.prepare_only:
        print(f"File preparati in {target_dir}")
        return 0

    site_dir = os.path.join(ROOT_DIR, "site")
    if os.path.isdir(site_dir):
        shutil.rmtree(site_dir)
    print("Esecuzione di mkdocs build…")
    result = subprocess.run(["mkdocs", "build", "--strict"], cwd=ROOT_DIR)
    if result.returncode != 0:
        return result.returncode
    prepare_landing(site_dir)
    print(f"Sito pronto in {site_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
