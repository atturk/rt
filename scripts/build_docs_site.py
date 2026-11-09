#!/usr/bin/env python3
"""Prepara la documentazione e compila il sito statico per GitHub Pages tramite MkDocs."""
import argparse
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


def prepare_site_docs(target_dir: str = "site_docs") -> None:
    os.makedirs(target_dir, exist_ok=True)
    guida_target = os.path.join(target_dir, "guida")
    os.makedirs(guida_target, exist_ok=True)

    guida_src = os.path.join(ROOT_DIR, "docs", "guida")
    guide_files = read_guide_index(guida_src)
    nav_guida = []

    # Copia solo i file della guida elencati nell'indice
    if os.path.isdir(guida_src):
        for slug in guide_files:
            src_md = os.path.join(guida_src, f"{slug}.md")
            if os.path.isfile(src_md):
                shutil.copy2(src_md, os.path.join(guida_target, f"{slug}.md"))
                title = slug
                with open(src_md, "r", encoding="utf-8") as f:
                    for line in f:
                        trimmed = line.strip()
                        if trimmed.startswith("# "):
                            title = trimmed[2:].strip()
                            break
                nav_guida.append({title: f"guida/{slug}.md"})

    # Copia immagini della guida
    immagini_src = os.path.join(guida_src, "immagini")
    immagini_target = os.path.join(guida_target, "immagini")
    if os.path.isdir(immagini_src):
        os.makedirs(immagini_target, exist_ok=True)
        for name in os.listdir(immagini_src):
            src_file = os.path.join(immagini_src, name)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, os.path.join(immagini_target, name))

    # Aggiorna la nav in mkdocs.yml
    mkdocs_file = os.path.join(ROOT_DIR, "mkdocs.yml")
    if os.path.isfile(mkdocs_file):
        with open(mkdocs_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        config["nav"] = [
            {"Home": "index.md"},
            {"Guida": nav_guida}
        ]
        with open(mkdocs_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)

    # Copia immagini del sito
    img_src = os.path.join(ROOT_DIR, "docs", "sito", "img")
    img_target = os.path.join(target_dir, "img")
    if os.path.isdir(img_src):
        os.makedirs(img_target, exist_ok=True)
        for name in os.listdir(img_src):
            shutil.copy2(os.path.join(img_src, name), os.path.join(img_target, name))

    # Prepara index.md della landing page con eventuale link donazioni
    landing_src = os.path.join(ROOT_DIR, "docs", "sito", "index.md")
    with open(landing_src, "r", encoding="utf-8") as f:
        content = f.read()

    donazioni_link = f"- **Sostieni il progetto**: [Sostieni RT]({DONAZIONI_URL})" if DONAZIONI_URL.strip() else ""
    content = content.replace("<!-- DONAZIONI_SEGNAPOSTO -->", donazioni_link)

    with open(os.path.join(target_dir, "index.md"), "w", encoding="utf-8") as f:
        f.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Costruisce il sito di RT con MkDocs")
    parser.add_argument("--prepare-only", action="store_true", help="Prepara solo i file in site_docs senza lanciare mkdocs")
    args = parser.parse_args()

    target_dir = os.path.join(ROOT_DIR, "site_docs")
    prepare_site_docs(target_dir)

    if args.prepare_only:
        print(f"File preparati in {target_dir}")
        return 0

    print("Esecuzione di mkdocs build…")
    result = subprocess.run(["mkdocs", "build"], cwd=ROOT_DIR)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
