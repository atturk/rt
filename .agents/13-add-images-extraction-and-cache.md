# Task 13 — `rt add-images`: estrazione immagini grezze + cache per hash (fondamenta)

Primo di 5 task sequenziali (13→17) per la nuova feature "aggiungi immagini al documento
finale". Ognuno dei successivi dipende da questo — non saltarlo né farlo in parallelo con gli
altri. Nessuna chiamata LLM in questo task: solo estrazione ed infrastruttura di cache.

Nel progetto RT (/Users/attilioturco/Desktop/trt), implementa direttamente, senza produrre un
piano preliminare.

## Contesto

RT copre oggi solo l'audio della lezione. Questa feature (comando supplementare, fuori da
`rt run`, sullo stesso modello di `rt review-asr`/`rt recall`) integra slide (PDF condiviso dal
docente) o foto (scattate a lezione) nel documento markdown finale, sotto la macro-sezione
(es. "## 3. Titolo", non le sotto-unità "### 3.1") a cui appartengono per contenuto. In
task futuri (14-17) si aggiungeranno le chiamate LLM di descrizione/assegnazione e
l'inserimento nel documento; QUESTO task costruisce solo l'estrazione delle immagini grezze e
il meccanismo di cache che eviterà di ri-processare le stesse immagini a ogni rilancio.

## Parte 1 — Estrazione immagini grezze (`rt/core/image_extract.py`, nuovo file)

Segue lo stesso stile a basso livello di `rt/core/audio_clip.py` (leggilo prima come
precedente di stile: funzioni pure, sollevano eccezioni chiare, non toccano il filesystem
della lezione — quello è compito del chiamante).

```python
"""
rt.core.image_extract
Estrazione di immagini grezze da PDF (una pagina = un'immagine) o da una cartella di foto.
Funzioni pure: non scrivono nella cartella della lezione, ritornano bytes in memoria.
"""
from dataclasses import dataclass
from typing import List
import os

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


@dataclass
class ExtractedImage:
    image_bytes: bytes
    source_label: str   # es. "pdf:slide.pdf#3" (pagina 3, 1-indexed) o "folder:foto_10.jpg"


def extract_images_from_pdf(pdf_path: str, zoom: float = 2.0) -> List[ExtractedImage]:
    """Estrae ogni pagina del PDF come immagine PNG in memoria, zoom 2x (stesso approccio
    dello script di riferimento /Users/attilioturco/comandi-personali/analisi_immagini.py,
    che usa PyMuPDF/fitz — leggilo per la chiamata esatta, righe ~243-274, prima di scrivere
    questa funzione). Solleva FileNotFoundError se pdf_path non esiste, ValueError se il PDF
    non si apre o non ha pagine."""
    import fitz
    if not os.path.isfile(pdf_path):
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
    return results


def extract_images_from_folder(folder_path: str) -> List[ExtractedImage]:
    """Enumera ricorsivamente le immagini in folder_path (estensioni in
    SUPPORTED_IMAGE_EXTENSIONS, case-insensitive, ignora dotfile), lette da disco as-is.
    Solleva FileNotFoundError se folder_path non esiste o non è una cartella."""
    if not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Cartella non trovata: '{folder_path}'")
    results = []
    for root, _dirs, files in os.walk(folder_path):
        for fn in sorted(files):
            if fn.startswith("."):
                continue
            if not fn.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
                continue
            full = os.path.join(root, fn)
            with open(full, "rb") as f:
                data = f.read()
            results.append(ExtractedImage(image_bytes=data, source_label=f"folder:{fn}"))
    return results


def extract_images(input_path: str) -> List[ExtractedImage]:
    """Dispatcher: se input_path è un file .pdf usa extract_images_from_pdf, se è una
    cartella usa extract_images_from_folder. Solleva ValueError per un file non-PDF singolo
    (non supportato come input diretto, solo cartelle o PDF)."""
    if os.path.isdir(input_path):
        return extract_images_from_folder(input_path)
    if input_path.lower().endswith(".pdf"):
        return extract_images_from_pdf(input_path)
    raise ValueError(
        f"Input non supportato: '{input_path}'. Passa un file .pdf o una cartella di immagini."
    )
```

Aggiungi `PyMuPDF` a `requirements.txt` (nuova dipendenza, nessun'altra parte del progetto la
usa oggi — verificato).

## Parte 2 — Cache per hash e stato lezione (`rt/pipeline/add_images.py`, nuovo file)

Le immagini vanno in una cartella nuova `lesson_dir/assets/images/` — DELIBERATAMENTE NON
sotto `_state/` (verifica `rt/core/lesson_paths.py` per capire la distinzione: `_state/` è
per file interni di stato/idempotenza, mentre `assets/images/` contiene file referenziati con
path relativo dal documento finale pubblicato, quindi è un artefatto del prodotto, non dello
stato interno — non aggiungerlo a `_STATE_ENTRIES`).

```python
"""
rt.pipeline.add_images
Comando supplementare (fuori da 'rt run', come review-asr/recall) che integra immagini
(slide PDF, foto, o risultati di ricerca web) nel documento markdown finale della lezione,
sotto la macro-sezione a cui appartengono per contenuto.
"""
import os
import json
import hashlib
from typing import Dict, Any, Optional
from rt.core.lesson_paths import lesson_path


def get_images_dir(lesson_dir: str) -> str:
    return lesson_path(lesson_dir, "assets/images")


def get_descriptions_path(lesson_dir: str) -> str:
    return os.path.join(get_images_dir(lesson_dir), "descriptions.json")


def compute_image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def load_image_descriptions(lesson_dir: str) -> Dict[str, Any]:
    """Ritorna {sha256_hash: {filename, source, slide_title, ocr_text, visual_elements,
    summary_keywords, alt_text}}. Dizionario vuoto se il file non esiste ancora."""
    path = get_descriptions_path(lesson_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_image_descriptions(lesson_dir: str, data: Dict[str, Any]) -> None:
    """Scrittura atomica (tmp file + os.replace), stesso pattern già usato in tutto il
    progetto per file di stato/artefatti — vedi rt/pipeline/outline.py::save_outline come
    esempio da imitare esattamente."""
    os.makedirs(get_images_dir(lesson_dir), exist_ok=True)
    path = get_descriptions_path(lesson_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def save_raw_image(lesson_dir: str, image_bytes: bytes, image_hash: str, ext: str = ".png") -> str:
    """Salva l'immagine grezza in assets/images/<hash_breve>.ext (solo se non già presente:
    idempotente per esistenza) e ritorna il path RELATIVO alla cartella della lezione (es.
    'assets/images/a1b2c3d4.png'), quello che andrà usato nel markdown finale."""
    short_hash = image_hash[:16]
    filename = f"{short_hash}{ext}"
    images_dir = get_images_dir(lesson_dir)
    os.makedirs(images_dir, exist_ok=True)
    full_path = os.path.join(images_dir, filename)
    if not os.path.isfile(full_path):
        tmp_path = full_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)
        os.replace(tmp_path, full_path)
    return f"assets/images/{filename}"
```

## Parte 3 — Logica di dedup (senza ancora chiamare l'LLM)

In `rt/pipeline/add_images.py`, aggiungi una funzione che, data una lista di
`ExtractedImage` (da Parte 1), calcola l'hash di ciascuna e SEPARA quelle già presenti in
`descriptions.json` (da riusare, nessun ricalcolo) da quelle nuove (da descrivere nei task
successivi):

```python
def partition_new_vs_cached_images(lesson_dir: str, images) -> tuple:
    """Ritorna (nuove, già_cachate) dove 'nuove' è una lista di (ExtractedImage, hash) per
    le immagini non ancora presenti in descriptions.json, e 'già_cachate' è una lista di
    (hash, entry_esistente) per quelle già descritte in un run precedente (stesso identico
    contenuto binario, mai la descrizione: quella non è mai stabile tra due chiamate LLM,
    l'hash è sempre e solo sui byte grezzi dell'immagine)."""
    existing = load_image_descriptions(lesson_dir)
    new_images = []
    cached = []
    seen_in_this_run = set()
    for img in images:
        h = compute_image_hash(img.image_bytes)
        if h in seen_in_this_run:
            continue  # stessa immagine esatta ripetuta nell'input di questo run, salta il duplicato
        seen_in_this_run.add(h)
        if h in existing:
            cached.append((h, existing[h]))
        else:
            new_images.append((img, h))
    return new_images, cached
```

## Test

Crea `tests/test_image_extract.py` e `tests/test_add_images.py`: `extract_images_from_pdf` su
un PDF di test minimale (genera un PDF sintetico al volo con `fitz` stesso nel test, o
verifica che sollevi `FileNotFoundError`/`ValueError` sui casi d'errore se costruire un PDF di
test è complesso); `extract_images_from_folder` con `tmp_path` popolata di file immagine finti
(bytes arbitrari, l'estensione basta per il filtro) e file non-immagine da ignorare;
`compute_image_hash` deterministico sugli stessi bytes; `save_raw_image` idempotente (secondo
salvataggio con stesso hash non sovrascrive, ritorna lo stesso path); `partition_new_vs_cached_images`
con un `descriptions.json` preesistente in `tmp_path` che separa correttamente nuove/cachate.
Esegui `python3 -m pytest tests/ -q` e correggi eventuali fallimenti tu stesso prima di
considerare il task concluso.

## Attenzione — bug di portabilità ricorrente in questo progetto

Più round di task precedenti hanno usato `Optional[...]`/`List[...]`/`Dict[...]` come
annotazione di tipo senza il corrispondente `from typing import ...` in cima al file — funziona
per puro caso in questo ambiente (Python 3.14 valuta le annotazioni in modo differito di
default, PEP 649) ma darebbe `NameError` su Python <3.14. Verifica sempre che ogni nome da
`typing` che usi sia importato esplicitamente nel file che lo usa.
