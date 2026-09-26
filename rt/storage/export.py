"""
rt.storage.export
Export su richiesta dei file di una lezione (rt export, GET /lessons/{id}/export): con le
lezioni nel database i Markdown finali non vivono più in una cartella da aprire, si
scaricano quando servono.

- scope "final": il Markdown finale (quello intitolato "[data] MATERIA - Titolo.md", o
  rielaborato.md se la lezione non ha ancora il file intitolato), "Errori concettuali.md"
  e le immagini che il Markdown richiama (assets/...), con gli stessi percorsi relativi,
  così i link continuano a funzionare;
- scope "all": tutti i file della lezione (testi, metadati, stato e media), con i nomi
  usati nel database (senza il prefisso _state/).
Funziona allo stesso modo per le lezioni in cartella e per quelle nel database.
"""
import io
import os
import re
import zipfile
from typing import Dict, List, Optional, Tuple

from rt.storage import fs

SCOPES = ("final", "all")
ERRORS_FILE = "Errori concettuali.md"
_TITLED_MD = re.compile(r"^\[\d{4}-\d{2}-\d{2}\] .+\.md$")
_MD_LINK = re.compile(r"!\[[^\]]*\]\(<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\)|<img[^>]+src=\"([^\"]+)\"")


class ExportError(ValueError):
    pass


def lesson_file_names(lesson_dir: str) -> Dict[str, str]:
    """Nome nella lezione -> percorso da passare a rt.storage.fs (DB o cartella)."""
    if fs.is_db_lesson(lesson_dir):
        return {row["name"]: os.path.join(lesson_dir, str(row["name"])) for row in fs.lesson_files(lesson_dir)}
    if not os.path.isdir(lesson_dir):
        raise ExportError(f"Lezione non trovata: {lesson_dir}")
    from rt.storage.migrate import plan_lesson
    return dict(plan_lesson(lesson_dir).files)


def final_markdown_name(names: Dict[str, str]) -> Optional[str]:
    titled = sorted(n for n in names if "/" not in n and _TITLED_MD.match(n))
    if titled:
        return titled[-1]
    return "rielaborato.md" if "rielaborato.md" in names else None


def _read(path: str) -> bytes:
    with fs.open(path, "rb") as f:
        return f.read()


def referenced_assets(markdown: str, names: Dict[str, str]) -> List[str]:
    out = []
    for m in _MD_LINK.finditer(markdown):
        ref = (m.group(1) or m.group(2) or "").split("#", 1)[0]
        if not ref or "://" in ref or ref.startswith("/"):
            continue
        ref = os.path.normpath(ref).replace(os.sep, "/")
        if ref in names and ref not in out:
            out.append(ref)
    return out


def collect(lesson_dir: str, scope: str = "final") -> List[Tuple[str, str]]:
    """(nome relativo nell'export, percorso di lettura) dei file da esportare."""
    if scope not in SCOPES:
        raise ExportError(f"Ambito di export sconosciuto: {scope} (usa {', '.join(SCOPES)})")
    names = lesson_file_names(lesson_dir)
    if scope == "all":
        return sorted(names.items())
    final = final_markdown_name(names)
    if final is None:
        raise ExportError("La lezione non ha ancora un Markdown finale: esegui prima la build.")
    picked = [final]
    if ERRORS_FILE in names:
        picked.append(ERRORS_FILE)
    markdown = _read(names[final]).decode("utf-8", errors="replace")
    picked += referenced_assets(markdown, names)
    return [(n, names[n]) for n in picked]


def final_markdown(lesson_dir: str) -> Tuple[str, bytes]:
    """(nome del file, contenuto) del Markdown finale."""
    names = lesson_file_names(lesson_dir)
    final = final_markdown_name(names)
    if final is None:
        raise ExportError("La lezione non ha ancora un Markdown finale: esegui prima la build.")
    return final, _read(names[final])


def export_to_dir(lesson_dir: str, out_dir: str, scope: str = "final") -> List[str]:
    """Scrive i file in <out_dir>/<nome lezione>/ e restituisce i percorsi scritti."""
    base = os.path.join(os.path.abspath(os.path.expanduser(out_dir)), os.path.basename(os.path.normpath(lesson_dir)))
    written = []
    for rel, src in collect(lesson_dir, scope):
        target = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        real = fs.real_path(src)
        with open(target, "wb") as out:
            if real is not None:
                with open(real, "rb") as f:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
            else:
                out.write(_read(src))
        written.append(target)
    return written


def export_zip(lesson_dir: str, scope: str = "final") -> bytes:
    """Archivio zip con i file nella cartella <nome lezione>/."""
    folder = os.path.basename(os.path.normpath(lesson_dir))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, src in collect(lesson_dir, scope):
            real = fs.real_path(src)
            if real is not None:
                zf.write(real, f"{folder}/{rel}")
            else:
                zf.writestr(f"{folder}/{rel}", _read(src))
    return buf.getvalue()
