"""
rt.pipeline.add_images
Comando supplementare (fuori da 'rt run', come review-asr/recall) che integra immagini
(slide PDF, foto, o risultati di ricerca web) nel documento markdown finale della lezione,
sotto la macro-sezione a cui appartengono per contenuto.
"""
import os
import json
import hashlib
import base64
from typing import Dict, Any, Optional, List, Tuple
from rt.core.lesson_paths import lesson_path
from rt.core.image_extract import ExtractedImage
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    ImageDescription,
    IMAGE_DESCRIPTION_SYSTEM_PROMPT,
    IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT,
    build_image_description_user_prompt,
)


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


def partition_new_vs_cached_images(lesson_dir: str, images: List[ExtractedImage]) -> Tuple[List[Tuple[ExtractedImage, str]], List[Tuple[str, Dict[str, Any]]]]:
    """Ritorna (nuove, già_cachate) dove 'nuove' è una lista di (ExtractedImage, hash) per
    le immagini non ancora presenti in descriptions.json, e 'già_cachate' è una lista di
    (hash, entry_esistente) per quelle già descritte in un run precedente."""
    existing = load_image_descriptions(lesson_dir)
    new_images: List[Tuple[ExtractedImage, str]] = []
    cached: List[Tuple[str, Dict[str, Any]]] = []
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


def get_lesson_context(lesson_dir: str) -> Optional[str]:
    info_path = os.path.join(lesson_dir, "info.yaml")
    if not os.path.isfile(info_path):
        return None
    try:
        from rt.core.state import read_info_yaml
        info = read_info_yaml(info_path)
        materia = info.get("materia", "").strip()
        titolo = info.get("titolo", "") or info.get("titolo_lezione", "") or info.get("argomenti", "")
        titolo = titolo.strip()
        parts = [p for p in (materia, titolo) if p]
        return " - ".join(parts) if parts else None
    except Exception:
        return None


def _get_image_mime_type(source_label: str) -> Tuple[str, str]:
    lbl_lower = source_label.lower()
    if lbl_lower.endswith(".jpg") or lbl_lower.endswith(".jpeg"):
        return "image/jpeg", ".jpg"
    elif lbl_lower.endswith(".webp"):
        return "image/webp", ".webp"
    else:
        return "image/png", ".png"


def describe_new_images(
    lesson_dir: str,
    new_images: List[Tuple[ExtractedImage, str]],
    lesson_context: Optional[str] = None,
    force_mock: bool = False,
) -> None:
    """Per ogni immagine nuova (ExtractedImage, hash), genera la descrizione strutturata
    via LLM con o senza contesto a seconda della sorgente, salva l'immagine grezza e
    aggiorna descriptions.json."""
    if not new_images:
        return

    if lesson_context is None:
        lesson_context = get_lesson_context(lesson_dir)

    client = LLMClient(force_mock=force_mock)
    existing_descriptions = load_image_descriptions(lesson_dir)

    for img, img_hash in new_images:
        mime_type, ext = _get_image_mime_type(img.source_label)
        b64_data = base64.b64encode(img.image_bytes).decode("utf-8")
        image_data_url = f"data:{mime_type};base64,{b64_data}"

        is_curated = img.source_label.startswith(("pdf:", "folder:"))
        if is_curated:
            sys_prompt = IMAGE_DESCRIPTION_SYSTEM_PROMPT
            user_prompt = build_image_description_user_prompt(context=lesson_context)
        else:
            sys_prompt = IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT
            user_prompt = build_image_description_user_prompt(context=None)

        desc: ImageDescription = client.call_structured(
            prompt=user_prompt,
            system_prompt=sys_prompt,
            response_model=ImageDescription,
            job_name="image_description",
            image_data_url=image_data_url,
            lesson_dir=lesson_dir,
        )

        rel_path = save_raw_image(lesson_dir, img.image_bytes, img_hash, ext=ext)

        existing_descriptions[img_hash] = {
            "filename": rel_path,
            "source": img.source_label,
            "slide_title": desc.slide_title,
            "ocr_text": desc.ocr_text,
            "visual_elements": desc.visual_elements,
            "summary_keywords": desc.summary_keywords,
            "alt_text": desc.alt_text,
        }
        save_image_descriptions(lesson_dir, existing_descriptions)
