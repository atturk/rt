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
    has_figures: bool = True
    mapping_skip: bool = False


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
    # Lo stesso PDF già letto come fonte (o da un altro pannello) riusa le pagine dell'archivio.
    archived = _archived_pages(fingerprint, basename, doc.page_count)
    if archived is not None:
        doc.close()
        if progress:
            progress(len(archived), len(archived))
        return archived
    results = []
    mat = fitz.Matrix(zoom, zoom)
    from rt.core.material_page_filter import cleaned_page_texts, few_words, pdf_pages_have_figures
    texts = cleaned_page_texts([page.get_text().strip() for page in doc])
    figures = pdf_pages_have_figures(doc)
    for i in range(doc.page_count):
        page = doc.load_page(i)
        has_figures = figures[i]
        sparse = few_words(texts[i])
        pix = page.get_pixmap(matrix=mat)
        results.append(ExtractedImage(
            image_bytes=pix.tobytes("png"),
            source_label=f"pdf:{basename}#{i + 1}",
            text='' if sparse and has_figures else texts[i],
            page_number=i + 1,
            file_fingerprint=fingerprint,
            has_figures=has_figures,
            mapping_skip=sparse and not has_figures,
        ))
        if progress:
            progress(i + 1, doc.page_count)
    doc.close()
    _archive_pages(pdf_path, fingerprint, results, texts)
    return results


def _archived_pages(sha, basename, count):
    """Pagine con immagine già nell'archivio, nello stesso formato di extract_images_from_pdf."""
    from rt.core.archive import entry_dir, read_json
    try:
        folder = entry_dir(sha)
    except ValueError:
        return None
    pages = (read_json(os.path.join(folder, 'pages.json'), {}) or {}).get('pages') or []
    if len(pages) != count or not all(p and p.get('immagini') and 'has_figures' in p for p in pages):
        return None
    results = []
    for page in pages:
        path = os.path.join(folder, os.path.basename(page['immagini'][0]))
        if not os.path.isfile(path):
            return None
        with open(path, 'rb') as stream:
            data = stream.read()
        text = '' if page.get('vision_pending') else page.get('mapping_text', page.get('testo', ''))
        results.append(ExtractedImage(
            image_bytes=data, source_label=f"pdf:{basename}#{page['numero']}", text=text or '',
            page_number=page['numero'], file_fingerprint=sha, has_figures=page['has_figures'],
            mapping_skip=bool(page.get('mapping_skip'))))
    return results


def _archive_pages(pdf_path, sha, results, texts):
    """Il PDF del pannello entra nell'archivio con le sue pagine: come fonte non si rilegge."""
    from rt.core.archive import archive_lock, entry_dir, read_json, refresh_search, register_file, save_meta, write_json
    try:
        register_file(pdf_path, nome=os.path.basename(pdf_path), tipo='slide', sha=sha)
        folder = entry_dir(sha)
        with archive_lock(sha + '-extract'):
            if read_json(os.path.join(folder, 'pages.json')):
                return
            pages = []
            for image, text in zip(results, texts):
                name = f'page-{image.page_number}-1.png'
                with open(os.path.join(folder, name), 'wb') as stream:
                    stream.write(image.image_bytes)
                pages.append({'numero': image.page_number, 'testo': text, 'immagini': [name],
                              'mapping_text': text, 'has_figures': image.has_figures,
                              'mapping_skip': image.mapping_skip,
                              **({'vision_pending': True} if not image.text and not image.mapping_skip else {})})
            write_json(os.path.join(folder, 'pages.json'), {'impronta': sha, 'pages': pages})
            _write_page_entries(folder, pages)
        save_meta(sha, {'pagine_totali': len(pages), 'estrai': 'immagini'})
        refresh_search(sha)
    except OSError:
        # L'archivio è un'ottimizzazione: il pannello funziona anche senza.
        return


def _write_page_entries(folder, pages):
    """page-N.json delle pagine finite: la lettura come fonte le riprende senza rifarle."""
    import json
    for page in pages:
        target = os.path.join(folder, f"page-{page['numero']}.json")
        if page.get('vision_pending') or os.path.exists(target):
            continue
        with open(target + '.tmp', 'w', encoding='utf-8') as stream:
            json.dump(page, stream, ensure_ascii=False)
        os.replace(target + '.tmp', target)


def update_archived_descriptions(images, descriptions):
    """Le descrizioni fatte dal pannello completano le pagine dell'archivio ancora da descrivere."""
    from rt.core.archive import archive_lock, entry_dir, read_json, refresh_search, write_json
    by_sha = {}
    for image in images:
        if image.source_label.startswith('pdf:') and image.file_fingerprint:
            by_sha.setdefault(image.file_fingerprint, []).append(image)
    import hashlib
    for sha, pages_images in by_sha.items():
        try:
            path = os.path.join(entry_dir(sha), 'pages.json')
        except ValueError:
            continue
        with archive_lock(sha + '-extract'):
            data = read_json(path)
            if not data:
                continue
            changed = False
            by_number = {p['numero']: p for p in data.get('pages', []) if p}
            for image in pages_images:
                page = by_number.get(image.page_number)
                description = descriptions.get(hashlib.sha256(image.image_bytes).hexdigest()) or {}
                described = '\n'.join(str(description.get(k) or '') for k in ('slide_title', 'ocr_text', 'visual_elements')).strip()
                if page and page.get('vision_pending') and described:
                    page.pop('vision_pending')
                    page.update(testo='\n'.join(filter(None, [page.get('testo'), described])), mapping_text=described)
                    changed = True
            if changed:
                write_json(path, data)
                _write_page_entries(os.path.dirname(path), data['pages'])
        if changed:
            refresh_search(sha)


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
