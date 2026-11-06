import os
import yaml
import pytest
from rt.core import paths


def test_guide_index_files_exist():
    root = paths.project_root()
    guida_dir = os.path.join(root, "docs", "guida")
    index_file = os.path.join(guida_dir, "indice.yml")
    assert os.path.isfile(index_file), "docs/guida/indice.yml deve esistere"

    with open(index_file, "r", encoding="utf-8") as f:
        entries = yaml.safe_load(f)

    assert isinstance(entries, list) and len(entries) > 0, "indice.yml deve contenere una lista di file"

    for entry in entries:
        slug = entry.get("file") if isinstance(entry, dict) else entry
        assert slug, f"Voce non valida in indice.yml: {entry}"
        md_file = os.path.join(guida_dir, f"{slug}.md")
        assert os.path.isfile(md_file), f"Il file {slug}.md citato in indice.yml non esiste in {guida_dir}"


def test_guide_index_fails_on_missing_file(tmp_path):
    index_file = tmp_path / "indice.yml"
    index_file.write_text("- file: pagina-inesistente\n", encoding="utf-8")
    with open(index_file, "r", encoding="utf-8") as f:
        entries = yaml.safe_load(f)
    with pytest.raises(AssertionError):
        for entry in entries:
            slug = entry.get("file")
            assert (tmp_path / f"{slug}.md").is_file()
