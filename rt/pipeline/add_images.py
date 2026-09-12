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
import re
import math
from typing import Dict, Any, Optional, List, Tuple
from rt.core.lesson_paths import lesson_path
from rt.core.image_extract import ExtractedImage, extract_images
from rt.core.searxng_client import search_images, download_image
from rt.llm.client import LLMClient
from rt.llm.prompts import (
    ImageDescription,
    IMAGE_DESCRIPTION_SYSTEM_PROMPT,
    IMAGE_DESCRIPTION_SYSTEM_PROMPT_NO_CONTEXT,
    build_image_description_user_prompt,
    ImageUnitJudgeResult,
    IMAGE_UNIT_JUDGE_SYSTEM_PROMPT,
    build_image_descriptions_context_message,
    build_image_unit_judge_user_prompt,
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


def judge_images_by_macro(lesson_dir: str, outline: Any, force_mock: bool = False) -> Dict[str, List[str]]:
    """Per ogni macro-sezione di 'outline', esegue UNA chiamata a call_structured con la history
    condivisa (messaggio 1: descriptions.json completo, messaggio 2: ack dell'assistant) e il
    prompt specifico della macro-sezione. Ritorna {macro_id: [hash, ...]}. Se descriptions.json
    è vuoto, ritorna {} senza chiamate LLM."""
    descriptions = load_image_descriptions(lesson_dir)
    if not descriptions:
        return {}

    desc_msg = build_image_descriptions_context_message(descriptions)
    history = [
        {"role": "user", "content": desc_msg},
        {"role": "assistant", "content": "Ho letto tutte le descrizioni delle immagini disponibili."}
    ]

    client = LLMClient(force_mock=force_mock)
    results: Dict[str, List[str]] = {}

    for macro in getattr(outline, "macro_sections", []):
        macro_id = str(macro.id)
        unit_lines = []
        for unit in getattr(macro, "units", []):
            kc = ", ".join(unit.key_concepts) if getattr(unit, "key_concepts", None) else "Nessuno"
            unit_lines.append(f"- Unità {unit.id}: {unit.title} (Concetti chiave: {kc})")
        units_text = "\n".join(unit_lines)

        user_prompt = build_image_unit_judge_user_prompt(macro.title, units_text)
        res: ImageUnitJudgeResult = client.call_structured(
            prompt=user_prompt,
            system_prompt=IMAGE_UNIT_JUDGE_SYSTEM_PROMPT,
            response_model=ImageUnitJudgeResult,
            job_name="image_unit_judge",
            history=history,
            lesson_dir=lesson_dir,
        )
        results[macro_id] = res.image_hashes

    return results


def build_macro_search_queries(outline: Any) -> Dict[str, str]:
    """Per ogni macro-sezione, unisce (deduplicati, in ordine di comparsa) i key_concepts di
    tutte le sue unità, prende i primi 3 e li unisce in un'unica stringa di query. Ritorna
    {macro_id: query_string}. Macro-sezioni senza alcun key_concept ottengono una query di
    fallback basata sul solo title della macro."""
    queries: Dict[str, str] = {}
    for macro in getattr(outline, "macro_sections", []):
        macro_id = str(macro.id)
        seen_kc: List[str] = []
        for unit in getattr(macro, "units", []):
            for kc in getattr(unit, "key_concepts", []) or []:
                clean_kc = str(kc).strip()
                if clean_kc and clean_kc not in seen_kc:
                    seen_kc.append(clean_kc)
        if seen_kc:
            query = " ".join(seen_kc[:3])
        else:
            query = re.sub(r'[/\\:*?"<>|]', ' ', getattr(macro, "title", "Macro")).strip()
        queries[macro_id] = query
    return queries


def fetch_web_images(
    lesson_dir: str,
    outline: Any,
    total_count: int,
    base_url: Optional[str] = None,
    force_mock: bool = False,
) -> List[ExtractedImage]:
    """Cerca ed estrae immagini dal web via SearXNG."""
    if not base_url and not force_mock:
        raise ValueError(
            "Impossibile eseguire la ricerca immagini web (--web-search): 'searxng_base_url' "
            "non è configurato in config/general.yaml."
        )

    queries = build_macro_search_queries(outline)
    if not queries or total_count <= 0:
        return []

    count_per_macro = math.ceil(total_count / len(queries))
    extracted: List[ExtractedImage] = []

    if force_mock:
        for idx, (macro_id, query) in enumerate(queries.items(), start=1):
            for i in range(count_per_macro):
                dummy_bytes = f"mock web image bytes {macro_id}_{i}".encode("utf-8")
                extracted.append(ExtractedImage(image_bytes=dummy_bytes, source_label=f"websearch:{query}#{i+1}"))
        return extracted[:total_count]

    for macro_id, query in queries.items():
        try:
            web_results = search_images(base_url, query, count=count_per_macro)
        except Exception:
            continue
        for res in web_results:
            try:
                data = download_image(res.image_url)
                label = f"websearch:{query}"
                extracted.append(ExtractedImage(image_bytes=data, source_label=label))
            except Exception:
                continue

    return extracted[:total_count]


def run_add_images(
    lesson_dir: str,
    input_path: Optional[str] = None,
    web_search_count: Optional[int] = None,
    carousel: bool = False,
    force_mock: bool = False,
) -> Dict[str, Any]:
    """Orchestratore principale di 'rt add-images'."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.core.state import read_info_yaml
    from rt.core.segments import load_segments_json
    from rt.pipeline.outline import load_outline
    from rt.pipeline.rewrite import load_draft
    from rt.pipeline.review import load_science_issues
    from rt.pipeline.ledger import load_ledger, apply_decisions_to_draft
    from rt.pipeline.build import render_rielaborato_md, _atomic_write_text

    phase_status, reason = check_phase_status(lesson_dir, "build")
    if phase_status != PhaseStatus.VALID:
        raise RuntimeError(
            f"La lezione in '{lesson_dir}' non ha ancora completato la fase di build "
            f"(stato attuale: {phase_status.value}). Esegui prima 'rt build'."
        )

    outline = load_outline(lesson_dir)
    extracted: List[ExtractedImage] = []

    if input_path:
        extracted.extend(extract_images(input_path))

    if web_search_count and web_search_count > 0:
        from rt.core.config import load_config
        cfg = load_config()
        searxng_url = getattr(cfg, "searxng_base_url", None)
        web_extracted = fetch_web_images(
            lesson_dir=lesson_dir,
            outline=outline,
            total_count=web_search_count,
            base_url=searxng_url,
            force_mock=force_mock,
        )
        extracted.extend(web_extracted)

    if extracted:
        new_images, _cached = partition_new_vs_cached_images(lesson_dir, extracted)
        if new_images:
            lesson_context = get_lesson_context(lesson_dir)
            describe_new_images(lesson_dir, new_images, lesson_context=lesson_context, force_mock=force_mock)

    assignments = judge_images_by_macro(lesson_dir, outline, force_mock=force_mock)

    descriptions = load_image_descriptions(lesson_dir)
    images_by_macro: Dict[str, List[dict]] = {}
    assigned_hashes = set()

    for macro_id, hashes in assignments.items():
        macro_imgs = []
        for h in hashes:
            if h in descriptions:
                macro_imgs.append(descriptions[h])
                assigned_hashes.add(h)
        if macro_imgs:
            images_by_macro[macro_id] = macro_imgs

    yaml_path = lesson_path(lesson_dir, "info.yaml")
    info = read_info_yaml(yaml_path)
    date_val = info.get("data", "0000-00-00")
    subject_val = info.get("materia", "MATERIA")
    topics_val = info.get("argomenti", "Argomenti")

    draft = load_draft(lesson_dir)
    segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    science_issues = load_science_issues(lesson_dir)
    ledger = load_ledger(lesson_dir)

    resolved_draft = apply_decisions_to_draft(draft, ledger, science_issues)

    rielab_md = render_rielaborato_md(
        outline=outline,
        draft=resolved_draft,
        segments_data=segments_data,
        date=date_val,
        subject=subject_val,
        topics=topics_val,
        images_by_macro=images_by_macro,
        carousel=carousel,
    )

    safe_title = re.sub(r'[/\\:*?"<>|]', ' ', outline.lesson_title)
    safe_title = re.sub(r'\s+', ' ', safe_title).strip()
    named_filename = f"[{date_val}] {subject_val.upper()} - {safe_title}.md"
    named_filepath = os.path.join(lesson_dir, named_filename)

    _atomic_write_text(lesson_path(lesson_dir, "rielaborato.md"), rielab_md)
    _atomic_write_text(named_filepath, rielab_md)

    return {
        "images_added": len(assigned_hashes),
        "macros_with_images": list(images_by_macro.keys()),
        "rielaborato_md": lesson_path(lesson_dir, "rielaborato.md"),
        "deliverable_md": named_filepath,
    }
