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

Il documento finale si usa se esiste ed è aggiornato (build VALID). Altrimenti, se la bozza
è pronta (prepare, outline e rewrite VALID), si esporta l'anteprima: lo stesso Markdown che
il build scriverebbe ora (rt.pipeline.build.render_lesson_documents), con "(anteprima)" nel
nome dei file e un LEGGIMI che lo spiega. Senza bozza pronta resta il documento finale
superato, se c'è.
"""
import io
import os
import re
import zipfile
from typing import Dict, List, Optional, Tuple, Union

from rt.storage import fs

SCOPES = ("final", "all")
ERRORS_FILE = "Errori concettuali.md"
_TITLED_MD = re.compile(r"^\[\d{4}-\d{2}-\d{2}\] .+\.md$")
_MD_LINK = re.compile(r"!\[[^\]]*\]\(<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\)|<img[^>]+src=\"([^\"]+)\"")


PREVIEW_SUFFIX = " (anteprima)"
PREVIEW_README = "LEGGIMI - anteprima.txt"
PREVIEW_README_TEXT = (
    "Questo archivio contiene un'ANTEPRIMA della lezione, non il documento finale.\n\n"
    "Il documento è stato generato dalla bozza attuale, con le decisioni della revisione prese "
    "finora e le immagini aggiunte, ma non è ancora stato confermato come documento finale "
    "(fase Documento). Quando lo crei, il documento finale sarà uguale a questa anteprima, "
    "salvo modifiche successive.\n"
)
_NOT_READY = "La lezione non ha ancora una bozza pronta né un documento finale: completa prima la rielaborazione."

# Contenuto da esportare: percorso da leggere con rt.storage.fs, oppure i byte già pronti.
Source = Union[str, bytes]


class ExportError(ValueError):
    pass


def export_mode(lesson_dir: str, names: Optional[Dict[str, str]] = None) -> str:
    """"final" (documento finale aggiornato), "preview" (anteprima dalla bozza),
    "stale" (solo un documento finale superato) oppure "none"."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    names = lesson_file_names(lesson_dir) if names is None else names
    has_final = final_markdown_name(names) is not None
    if has_final and check_phase_status(lesson_dir, "build")[0] == PhaseStatus.VALID:
        return "final"
    if check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.VALID:
        return "preview"
    return "stale" if has_final else "none"


def _preview_documents(lesson_dir: str) -> Tuple[str, bytes, bytes]:
    """(nome del Markdown, Markdown, Errori concettuali) dell'anteprima."""
    from rt.core.encoding import fix_mojibake
    from rt.pipeline.build import render_lesson_documents
    docs = render_lesson_documents(lesson_dir)
    name = docs["named_filename"][:-len(".md")] + PREVIEW_SUFFIX + ".md"
    return (name, fix_mojibake(docs["rielaborato"]).encode("utf-8"),
            fix_mojibake(docs["errori_concettuali"]).encode("utf-8"))


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


def is_preview(lesson_dir: str) -> bool:
    """True se l'export della lezione è un'anteprima e non il documento finale."""
    return export_mode(lesson_dir) == "preview"


def collect(lesson_dir: str, scope: str = "final") -> List[Tuple[str, Source]]:
    """(nome relativo nell'export, percorso di lettura o contenuto) dei file da esportare."""
    if scope not in SCOPES:
        raise ExportError(f"Ambito di export sconosciuto: {scope} (usa {', '.join(SCOPES)})")
    names = lesson_file_names(lesson_dir)
    mode = export_mode(lesson_dir, names)
    if scope == "all":
        items: List[Tuple[str, Source]] = sorted(names.items())
        if mode == "preview":
            md_name, markdown, _errors = _preview_documents(lesson_dir)
            items += [(md_name, markdown), (PREVIEW_README, PREVIEW_README_TEXT.encode("utf-8"))]
        return items
    if mode == "none":
        raise ExportError(_NOT_READY)
    if mode == "preview":
        md_name, markdown, errors = _preview_documents(lesson_dir)
        picked: List[Tuple[str, Source]] = [(md_name, markdown), (ERRORS_FILE, errors)]
        assets = referenced_assets(markdown.decode("utf-8", errors="replace"), names)
        return picked + [(n, names[n]) for n in assets] + [(PREVIEW_README, PREVIEW_README_TEXT.encode("utf-8"))]
    final = final_markdown_name(names)
    picked_names = [final]
    if ERRORS_FILE in names:
        picked_names.append(ERRORS_FILE)
    markdown_text = _read(names[final]).decode("utf-8", errors="replace")
    picked_names += referenced_assets(markdown_text, names)
    return [(n, names[n]) for n in picked_names]


def final_markdown(lesson_dir: str) -> Tuple[str, bytes]:
    """(nome del file, contenuto) del Markdown da scaricare: il documento finale se
    aggiornato, altrimenti l'anteprima dalla bozza (nome con "(anteprima)")."""
    names = lesson_file_names(lesson_dir)
    mode = export_mode(lesson_dir, names)
    if mode == "none":
        raise ExportError(_NOT_READY)
    if mode == "preview":
        md_name, markdown, _errors = _preview_documents(lesson_dir)
        return md_name, markdown
    final = final_markdown_name(names)
    return final, _read(names[final])


def zip_name(lesson_dir: str) -> str:
    """Nome dell'archivio: con "(anteprima)" se non contiene il documento finale."""
    base = os.path.basename(os.path.normpath(lesson_dir))
    return f"{base}{PREVIEW_SUFFIX if is_preview(lesson_dir) else ''}.zip"


def _write_source(out, src: Source) -> None:
    if isinstance(src, bytes):
        out.write(src)
        return
    real = fs.real_path(src)
    if real is None:
        out.write(_read(src))
        return
    with open(real, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def export_to_dir(lesson_dir: str, out_dir: str, scope: str = "final") -> List[str]:
    """Scrive i file in <out_dir>/<nome lezione>/ e restituisce i percorsi scritti."""
    base = os.path.join(os.path.abspath(os.path.expanduser(out_dir)), os.path.basename(os.path.normpath(lesson_dir)))
    written = []
    for rel, src in collect(lesson_dir, scope):
        target = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as out:
            _write_source(out, src)
        written.append(target)
    return written


def export_zip(lesson_dir: str, scope: str = "final") -> bytes:
    """Archivio zip con i file nella cartella <nome lezione>/."""
    folder = os.path.basename(os.path.normpath(lesson_dir))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, src in collect(lesson_dir, scope):
            real = None if isinstance(src, bytes) else fs.real_path(src)
            if real is not None:
                zf.write(real, f"{folder}/{rel}")
            else:
                zf.writestr(f"{folder}/{rel}", src if isinstance(src, bytes) else _read(src))
    return buf.getvalue()
