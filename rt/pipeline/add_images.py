"""
rt.pipeline.add_images
Comando supplementare (fuori da 'rt run', come review-asr/recall) che integra immagini
(slide PDF, foto, o risultati di ricerca web) nel documento markdown finale della lezione,
sotto la macro-sezione a cui appartengono per contenuto.
"""
import os
import json
import hashlib
from typing import Dict, Any, Optional, List, Tuple
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
    progetto per file di stato/artefatti."""
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


def partition_new_vs_cached_images(lesson_dir: str, images: List) -> Tuple[List, List]:
    """Ritorna (nuove, già_cachate) dove 'nuove' è una lista di (ExtractedImage, hash) per
    le immagini non ancora presenti in descriptions.json, e 'già_cachate' è una lista di
    (hash, entry_esistente) per quelle già descritte in un run precedente (stesso identico
    contenuto binario)."""
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
