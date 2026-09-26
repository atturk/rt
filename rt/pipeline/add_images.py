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
from rt.storage import fs


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
    if not fs.isfile(path):
        return {}
    with fs.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_image_descriptions(lesson_dir: str, data: Dict[str, Any]) -> None:
    """Scrittura atomica (tmp file + os.replace), stesso pattern già usato in tutto il
    progetto per file di stato/artefatti."""
    fs.makedirs(get_images_dir(lesson_dir), exist_ok=True)
    path = get_descriptions_path(lesson_dir)
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    fs.replace(tmp_path, path)


def save_raw_image(lesson_dir: str, image_bytes: bytes, image_hash: str, ext: str = ".png") -> str:
    """Salva l'immagine grezza in assets/images/<hash_breve>.ext (solo se non già presente:
    idempotente per esistenza) e ritorna il path RELATIVO alla cartella della lezione (es.
    'assets/images/a1b2c3d4.png'), quello che andrà usato nel markdown finale."""
    short_hash = image_hash[:16]
    filename = f"{short_hash}{ext}"
    images_dir = get_images_dir(lesson_dir)
    fs.makedirs(images_dir, exist_ok=True)
    full_path = os.path.join(images_dir, filename)
    if not fs.isfile(full_path):
        tmp_path = full_path + ".tmp"
        with fs.open(tmp_path, "wb") as f:
            f.write(image_bytes)
        fs.replace(tmp_path, full_path)
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
    if not fs.isfile(info_path):
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

    if client.force_mock and results and not any(results.values()):
        # in mock il giudice non sceglie nulla: le immagini vanno nella prima macro-sezione,
        # così il documento di prova le mostra (anteprima della SPA, test end-to-end)
        results[next(iter(results))] = list(descriptions)
    return results


def _unit_query(unit: Any) -> str:
    """Query di ricerca di un'unità: i primi 3 key_concepts (deduplicati, in ordine), oppure il
    titolo dell'unità se non ne ha."""
    seen: List[str] = []
    for kc in getattr(unit, "key_concepts", []) or []:
        clean = str(kc).strip()
        if clean and clean not in seen:
            seen.append(clean)
    if seen:
        return " ".join(seen[:3])
    return re.sub(r'[/\\:*?"<>|]', ' ', str(getattr(unit, "title", "") or getattr(unit, "id", ""))).strip()


def outline_unit_ids(outline: Any) -> List[str]:
    return [str(u.id) for macro in getattr(outline, "macro_sections", []) for u in getattr(macro, "units", [])]


def build_unit_search_queries(outline: Any, unit_ids: Optional[List[str]] = None) -> Dict[str, str]:
    """Una query di ricerca per unità, nell'ordine dell'outline: {unit_id: query}. unit_ids
    limita la ricerca alle unità scelte (None = tutte); un id che non è nell'outline è un
    errore (ValueError)."""
    wanted = None
    if unit_ids is not None:
        wanted = [str(u) for u in unit_ids]
        unknown = sorted(set(wanted) - set(outline_unit_ids(outline)))
        if unknown:
            raise ValueError(f"Unità inesistenti nella scaletta: {', '.join(unknown)}.")
    queries: Dict[str, str] = {}
    for macro in getattr(outline, "macro_sections", []):
        for unit in getattr(macro, "units", []):
            unit_id = str(unit.id)
            if wanted is None or unit_id in wanted:
                queries[unit_id] = _unit_query(unit)
    return queries


def _mock_png(seed: str) -> bytes:
    """PNG valido 8x8 di un colore ricavato da seed (immagini web finte in mock: diverse per
    unità, e visualizzabili nell'anteprima)."""
    import struct
    import zlib
    r, g, b = hashlib.sha256(seed.encode("utf-8")).digest()[:3]

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + bytes((r, g, b)) * 8 for _ in range(8))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fetch_web_images(
    lesson_dir: str,
    outline: Any,
    per_unit: int,
    base_url: Optional[str] = None,
    force_mock: bool = False,
    unit_ids: Optional[List[str]] = None,
) -> Tuple[List[ExtractedImage], Dict[str, int]]:
    """Cerca immagini dal web via SearXNG: una query per unità e fino a per_unit risultati per
    ciascuna, sulle unità scelte (unit_ids, None = tutte). Restituisce le immagini scaricate e
    quante ne sono arrivate per unità."""
    if not base_url and not force_mock:
        raise ValueError(
            "La ricerca di immagini sul web richiede SearXNG: configuralo in Impostazioni."
        )

    queries = build_unit_search_queries(outline, unit_ids)
    if not queries or per_unit <= 0:
        return [], {}

    extracted: List[ExtractedImage] = []
    found: Dict[str, int] = {}

    for unit_id, query in queries.items():
        found[unit_id] = 0
        if force_mock:
            for i in range(per_unit):
                extracted.append(ExtractedImage(image_bytes=_mock_png(f"{unit_id}#{i}"),
                                                source_label=f"websearch:{query}#{i+1}"))
                found[unit_id] += 1
            continue
        try:
            web_results = search_images(base_url, query, count=per_unit)
        except Exception:
            continue
        for res in web_results[:per_unit]:
            try:
                data = download_image(res.image_url)
            except Exception:
                continue
            extracted.append(ExtractedImage(image_bytes=data, source_label=f"websearch:{query}"))
            found[unit_id] += 1

    return extracted, found


def run_add_images(
    lesson_dir: str,
    input_path: Optional[str] = None,
    web_search_count: Optional[int] = None,
    force_mock: bool = False,
    unit_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Orchestratore principale di 'rt add-images'. web_search_count: immagini da cercare sul
    web per ogni unità (unit_ids: solo quelle unità, None = tutte)."""
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
    web_found: Dict[str, int] = {}

    if input_path:
        extracted.extend(extract_images(input_path))

    if web_search_count and web_search_count > 0:
        from rt.core.config import load_config
        cfg = load_config()
        searxng_url = getattr(cfg, "searxng_base_url", None)
        web_extracted, web_found = fetch_web_images(
            lesson_dir=lesson_dir,
            outline=outline,
            per_unit=web_search_count,
            base_url=searxng_url,
            force_mock=force_mock,
            unit_ids=unit_ids,
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
        "web_images_by_unit": web_found,
        "rielaborato_md": lesson_path(lesson_dir, "rielaborato.md"),
        "deliverable_md": named_filepath,
    }
