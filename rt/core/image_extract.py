"""
rt.core.image_extract
Estrazione di immagini grezze da PDF (una pagina = un'immagine) o da una cartella di foto.
Funzioni pure: non scrivono nella cartella della lezione, ritornano bytes in memoria.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional
import os
from rt.storage import fs

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif")


@dataclass
class ExtractedImage:
    image_bytes: bytes
    source_label: str   # es. "pdf:slide.pdf#3" o "folder:foto_10.jpg"
    text: str = ""
    page_number: int = 1
    file_fingerprint: str = ""
    unit_id: Optional[str] = None


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
    from rt.core.idempotency import compute_file_sha256
    fingerprint = compute_file_sha256(pdf_path)
    basename = os.path.basename(pdf_path)
    results = []
    mat = fitz.Matrix(zoom, zoom)
    for i in range(doc.page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=mat)
        results.append(ExtractedImage(
            image_bytes=pix.tobytes("png"),
            source_label=f"pdf:{basename}#{i + 1}",
            text=page.get_text().strip(),
            page_number=i + 1,
            file_fingerprint=fingerprint,
        ))
        if progress:
            progress(i + 1, doc.page_count)
    doc.close()
    return results


def extract_images_from_folder(folder_path: str, progress: Optional[Callable[[int, int], None]] = None) -> List[ExtractedImage]:
    """Enumera ricorsivamente PDF e immagini in folder_path (estensioni in
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
            if not fn.lower().endswith((*SUPPORTED_IMAGE_EXTENSIONS, ".pdf")):
                continue
            paths.append(os.path.join(root, fn))
    # I caricamenti multipli arrivano nella stessa cartella, anche PDF e foto insieme.
    import fitz
    counts = []
    for full in paths:
        if full.lower().endswith('.pdf'):
            with fitz.open(full) as doc:
                counts.append(doc.page_count)
        else:
            counts.append(1)
    total = sum(counts)
    completed = 0
    for full, count in zip(paths, counts):
        if full.lower().endswith('.pdf'):
            results.extend(extract_images_from_pdf(full, progress=(
                lambda current, _total: progress(completed + current, total)) if progress else None))
        else:
            results.append(_extract_photo(full))
            if progress:
                progress(completed + 1, total)
        completed += count
    return results


def _extract_photo(path: str) -> ExtractedImage:
    import hashlib
    with fs.open(path, 'rb') as stream:
        data = stream.read()
    fingerprint = hashlib.sha256(data).hexdigest()
    if path.lower().endswith(('.heic', '.gif')):
        from rt.core.materials import _png_image
        data = _png_image(data)
    return ExtractedImage(data, f"folder:{os.path.basename(path)}", file_fingerprint=fingerprint)


def extract_images(input_path: str, progress: Optional[Callable[[int, int], None]] = None) -> List[ExtractedImage]:
    """Dispatcher: se input_path è un file .pdf usa extract_images_from_pdf, se è una
    cartella usa extract_images_from_folder. Solleva ValueError per un file non-PDF singolo
    (non supportato come input diretto, solo cartelle o PDF)."""
    if fs.isdir(input_path):
        return extract_images_from_folder(input_path, progress=progress)
    if input_path.lower().endswith(".pdf"):
        return extract_images_from_pdf(input_path, progress=progress)
    if input_path.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
        image = _extract_photo(input_path)
        if progress:
            progress(1, 1)
        return [image]
    raise ValueError(
        f"Input non supportato: '{input_path}'. Passa un PDF, una foto o una cartella di PDF e immagini."
    )
