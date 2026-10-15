"""
rt.core.image_extract
Estrazione di immagini grezze da PDF (una pagina = un'immagine) o da una cartella di foto.
Funzioni pure: non scrivono nella cartella della lezione, ritornano bytes in memoria.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional
import os
from rt.storage import fs

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class ExtractedImage:
    image_bytes: bytes
    source_label: str   # es. "pdf:slide.pdf#3" (pagina 3, 1-indexed) o "folder:foto_10.jpg"


def extract_images_from_pdf(pdf_path: str, zoom: float = 2.0, progress: Optional[Callable[[int, int], None]] = None) -> List[ExtractedImage]:
    """Estrae ogni pagina del PDF come immagine PNG in memoria, zoom 2x.
    Solleva FileNotFoundError se pdf_path non esiste, ValueError se il PDF
    non si apre o non ha pagine."""
    import fitz
    if not fs.isfile(pdf_path):
        raise FileNotFoundError(f"File PDF non trovato: '{pdf_path}'")
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise ValueError(f"Impossibile aprire il PDF '{pdf_path}': {e}")
    if doc.page_count == 0:
        raise ValueError(f"Il PDF '{pdf_path}' non contiene pagine.")
    basename = os.path.basename(pdf_path)
    results = []
    mat = fitz.Matrix(zoom, zoom)
    for i in range(doc.page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=mat)
        results.append(ExtractedImage(
            image_bytes=pix.tobytes("png"),
            source_label=f"pdf:{basename}#{i + 1}",
        ))
        if progress:
            progress(i + 1, doc.page_count)
    doc.close()
    return results


def extract_images_from_folder(folder_path: str, progress: Optional[Callable[[int, int], None]] = None) -> List[ExtractedImage]:
    """Enumera ricorsivamente le immagini in folder_path (estensioni in
    SUPPORTED_IMAGE_EXTENSIONS, case-insensitive, ignora dotfile), lette da disco as-is.
    Solleva FileNotFoundError se folder_path non esiste o non è una cartella."""
    if not fs.isdir(folder_path):
        raise FileNotFoundError(f"Cartella non trovata: '{folder_path}'")
    results = []
    paths = []
    for root, _dirs, files in fs.walk(folder_path):
        for fn in sorted(files):
            if fn.startswith("."):
                continue
            if not fn.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
                continue
            paths.append(os.path.join(root, fn))
    for i, full in enumerate(paths, 1):
        with fs.open(full, "rb") as f:
            data = f.read()
        results.append(ExtractedImage(image_bytes=data, source_label=f"folder:{os.path.basename(full)}"))
        if progress:
            progress(i, len(paths))
    return results


def extract_images(input_path: str, progress: Optional[Callable[[int, int], None]] = None) -> List[ExtractedImage]:
    """Dispatcher: se input_path è un file .pdf usa extract_images_from_pdf, se è una
    cartella usa extract_images_from_folder. Solleva ValueError per un file non-PDF singolo
    (non supportato come input diretto, solo cartelle o PDF)."""
    if fs.isdir(input_path):
        return extract_images_from_folder(input_path, progress=progress)
    if input_path.lower().endswith(".pdf"):
        return extract_images_from_pdf(input_path, progress=progress)
    raise ValueError(
        f"Input non supportato: '{input_path}'. Passa un file .pdf o una cartella di immagini."
    )
