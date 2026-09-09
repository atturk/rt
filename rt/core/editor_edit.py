"""
rt.core.editor_edit
Modifica testuale interattiva tramite editor di sistema ($EDITOR / nano).
"""

import os
import tempfile
import subprocess


def edit_text_in_editor(initial_content: str) -> str:
    """
    Scrive initial_content in un file temporaneo e apre l'editor configurato in $EDITOR (fallback 'nano').
    Attende la chiusura dell'editor, rilegge il contenuto salvato, ripulisce il file temporaneo
    e ritorna il testo senza whitespace finale.
    """
    editor = os.environ.get("EDITOR", "").strip() or "nano"

    tmp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    tmp_path = tmp_file.name
    try:
        tmp_file.write(initial_content)
        tmp_file.flush()
        tmp_file.close()

        cmd = [editor]
        if os.path.basename(editor) == "nano":
            cmd.append("--softwrap")
        elif os.path.basename(editor) == "micro":
            cmd += ["-softwrap", "true"]
        cmd.append(tmp_path)

        subprocess.call(cmd)

        with open(tmp_path, "r", encoding="utf-8") as f:
            content = f.read()

        return content.rstrip()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
