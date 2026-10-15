"""
rt.pipeline.material_mapping
Assegnazione delle pagine dei materiali alle sottounità didattiche (MF1).
- MF1a: Ricerca locale delle candidate con TF-IDF, rimozione stopwords italiane
  (inclusi intercalari del parlato) e stemmer italiano puro Python.
- MF1b: Valutazione sì/no tramite Jev Decision API con aggregazione a macro-unità (>= 3).
- MF1c-MF1e: Integrazione nella pipeline prima della rielaborazione.
"""

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from rt.llm.cancel import RunCancelled
from rt.core.lesson_paths import lesson_path
from rt.core.models import Outline, Segment, SegmentsData
from rt.storage import fs

# Intercalari del parlato e stopwords italiane
ITALIAN_STOPWORDS: Set[str] = {
    # Articoli
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "l",
    # Preposizioni semplici e articolate
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    # Pronomi e particelle
    "che", "chi", "cui", "quale", "quali", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "ciò", "mi", "ti", "si", "ci", "vi", "ne",
    "li", "me", "te", "se", "noi", "voi", "loro", "esso", "essa", "essi", "esse",
    "mio", "tuo", "suo", "nostro", "vostro", "mia", "tua", "sua", "nostra", "vostra",
    "miei", "tuoi", "suoi", "nostri", "vostri", "mie", "tue", "sue", "nostre", "vostre",
    # Congiunzioni
    "e", "ed", "o", "oppure", "ma", "però", "tuttavia", "né", "se", "come", "quando",
    "dove", "affinché", "poiché", "perché", "perchè", "mentre", "invece",
    # Avverbi e forme comuni
    "non", "più", "anche", "solo", "quasi", "già", "ancora", "molto", "poco", "assai",
    "troppo", "tanto", "quanto", "sì", "no", "forse", "mai", "sempre", "subito", "poi",
    "ora", "adesso", "qui", "qua", "lì", "là",
    # Ausiliari e verbi frequenti
    "è", "sono", "era", "erano", "stato", "stati", "stata", "state", "essere", "fu",
    "ha", "hanno", "aveva", "avevano", "avuto", "avere", "ho", "abbiamo", "avete",
    "siamo", "siete", "sei", "ero", "sta", "stanno", "stava", "stavano", "stiamo",
    "fare", "fa", "fanno", "faceva", "fatto", "va", "vanno", "andare",
    # Intercalari del parlato (come richiesto esplicitamente nel piano MF1a)
    "quindi", "diciamo", "cioè", "allora", "praticamente", "insomma", "ecco",
    "comunque", "veramente", "appunto", "magari", "proprio", "vediamo", "esatto",
    "tipo", "bene", "niente", "chiaramente", "ovviamente", "sostanzialmente",
}

WORD_PATTERN = re.compile(r"[a-zA-ZàèéìòùÀÈÉÌÒÙ]{2,}")


def stem_italian(word: str) -> str:
    """Stemmer italiano rule-based leggero e deterministico, senza dipendenze esterne."""
    w = word.lower().strip()
    if len(w) <= 3:
        return w
    # Normalizzazione accenti finali
    w = (w.replace("à", "a")
          .replace("è", "e")
          .replace("é", "e")
          .replace("ì", "i")
          .replace("ò", "o")
          .replace("ù", "u"))

    # 1. Suffissi derivazionali lunghi
    long_suffixes = (
        "ativamente", "abilmente", "ibilmente", "ivamente", "osamente", "amente", "mente",
        "icazione", "icazioni", "izzazione", "izzazioni", "azione", "azioni",
        "amento", "amenti", "imento", "imenti",
        "abilita", "ibilita", "attivita",
        "abile", "abili", "ibile", "ibili",
        "istico", "istica", "istici", "istiche",
        "atore", "atori", "atrice", "atrici",
        "issimo", "issima", "issimi", "issime",
    )
    for sfx in long_suffixes:
        if w.endswith(sfx) and len(w) - len(sfx) >= 3:
            w = w[:-len(sfx)]
            break

    # 2. Suffissi verbali
    verb_suffixes = (
        "assero", "assimo", "eranno", "erebbero", "eremmo", "ereste", "eresti",
        "essero", "essimo", "iranno", "irebbero", "iremmo", "ireste", "iresti",
        "avamo", "avate", "evamo", "evate", "ivamo", "ivate",
        "arono", "erono", "irono", "eremo", "iremo",
        "ando", "endo",
        "asse", "assi", "esse", "essi", "isse", "issi",
        "ammo", "emmo", "immo",
        "iamo", "iate",
        "asse", "asti", "este", "esti", "iste", "isti",
        "avano", "evano", "ivano",
        "ava", "avi", "avo", "eva", "evi", "evo", "iva", "ivi", "ivo",
        "are", "ere", "ire", "ato", "ata", "ati", "ate", "uto", "uta", "uti", "ute", "ito", "ita", "iti", "ite",
        "ano", "eno", "ono",
    )
    for sfx in verb_suffixes:
        if w.endswith(sfx) and len(w) - len(sfx) >= 3:
            w = w[:-len(sfx)]
            break

    # 3. Suffissi nominali semplici
    nominal_suffixes = (
        "ismo", "ismi", "ista", "isti", "iste",
        "ita", "ico", "ica", "ici", "iche", "oso", "osa", "osi", "ose"
    )
    for sfx in nominal_suffixes:
        if w.endswith(sfx) and len(w) - len(sfx) >= 3:
            w = w[:-len(sfx)]
            break

    # 4. Riduzione vocale tematica finale
    if len(w) > 3 and w[-1] in ("o", "a", "e", "i", "u"):
        w = w[:-1]

    return w


def tokenize_text(text: str) -> List[str]:
    """Estrae token radicalizzati escludendo stopwords e intercalari."""
    words = WORD_PATTERN.findall(text.lower())
    tokens: List[str] = []
    for w in words:
        if w in ITALIAN_STOPWORDS or len(w) < 2:
            continue
        stem = stem_italian(w)
        if stem and stem not in ITALIAN_STOPWORDS:
            tokens.append(stem)
    return tokens


@dataclass
class SubunitCorpusEntry:
    unit_id: str
    macro_id: str
    title: str
    transcript: str
    tokens: List[str]
    tf_vector: Dict[str, float]


@dataclass
class CandidateSubunit:
    unit_id: str
    macro_id: str
    title: str
    transcript: str
    score: float


def build_subunit_corpus(outline: Outline, segments_data: SegmentsData) -> Tuple[List[SubunitCorpusEntry], Dict[str, float]]:
    """Costruisce il corpus delle sottounità con i rispettivi vettori TF-IDF normalizzati."""
    seg_by_id = {s.id: s for s in segments_data.segments}
    all_segs = segments_data.segments
    entries: List[SubunitCorpusEntry] = []

    for macro in outline.macro_sections:
        for unit in macro.units:
            start_seg = seg_by_id.get(unit.start_segment_id)
            end_seg = seg_by_id.get(unit.end_segment_id)
            if start_seg and end_seg and start_seg.index <= end_seg.index:
                unit_segs = all_segs[start_seg.index - 1 : end_seg.index]
                transcript = " ".join(s.text_raw for s in unit_segs)
            else:
                transcript = ""
            full_text = f"{unit.title} {transcript}"
            tokens = tokenize_text(full_text)
            entries.append(SubunitCorpusEntry(
                unit_id=unit.id,
                macro_id=str(macro.id),
                title=unit.title,
                transcript=transcript,
                tokens=tokens,
                tf_vector={},
            ))

    num_units = len(entries)
    if num_units == 0:
        return [], {}

    # Calcolo Document Frequency (DF)
    df: Dict[str, int] = {}
    for entry in entries:
        seen = set(entry.tokens)
        for term in seen:
            df[term] = df.get(term, 0) + 1

    # Calcolo IDF: ln((N + 1) / (df + 1)) + 1.0 (termini rari pesano di più)
    idf: Dict[str, float] = {
        term: math.log((num_units + 1.0) / (freq + 1.0)) + 1.0
        for term, freq in df.items()
    }

    # Calcolo vettori normalizzati per ogni sottounità
    for entry in entries:
        term_counts: Dict[str, int] = {}
        for t in entry.tokens:
            term_counts[t] = term_counts.get(t, 0) + 1

        vec: Dict[str, float] = {
            t: count * idf[t] for t, count in term_counts.items()
        }
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm > 0:
            entry.tf_vector = {t: v / norm for t, v in vec.items()}
        else:
            entry.tf_vector = {}

    return entries, idf


def find_candidate_subunits_for_page(
    page_text: str,
    corpus: List[SubunitCorpusEntry],
    idf: Dict[str, float],
) -> List[CandidateSubunit]:
    """
    Individua fino a 5 sottounità candidate per una pagina di materiale non principale (MF1a).
    Si tengono le candidate con punteggio almeno metà del migliore, al massimo 5.
    Se la pagina non ha testo utile o non ci sono candidate, restituisce una lista vuota.
    """
    page_tokens = tokenize_text(page_text)
    # Pagina senza testo utile (meno di 3 token utili o priva di testo)
    if len(page_tokens) < 3 or not corpus:
        return []

    # Calcolo vettore TF-IDF della pagina
    page_counts: Dict[str, int] = {}
    for t in page_tokens:
        page_counts[t] = page_counts.get(t, 0) + 1

    page_vec: Dict[str, float] = {}
    for t, count in page_counts.items():
        if t in idf:
            page_vec[t] = count * idf[t]

    page_norm = math.sqrt(sum(v * v for v in page_vec.values()))
    if page_norm == 0:
        return []

    normalized_page_vec = {t: v / page_norm for t, v in page_vec.items()}

    # Calcolo somiglianza coseno con ogni sottounità
    scored: List[Tuple[float, SubunitCorpusEntry]] = []
    for entry in corpus:
        if not entry.tf_vector:
            continue
        sim = sum(normalized_page_vec[t] * entry.tf_vector[t]
                  for t in normalized_page_vec if t in entry.tf_vector)
        if sim > 0:
            scored.append((sim, entry))

    if not scored:
        return []

    # Ordina per somiglianza decrescente
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]
    if best_score <= 0:
        return []

    threshold = 0.5 * best_score
    candidates: List[CandidateSubunit] = []
    for sim, entry in scored:
        if sim >= threshold and len(candidates) < 5:
            candidates.append(CandidateSubunit(
                unit_id=entry.unit_id,
                macro_id=entry.macro_id,
                title=entry.title,
                transcript=entry.transcript,
                score=sim,
            ))

    return candidates


STATE_FILE = "material_attachments.json"
CACHE_FILE = "material_decisions.json"


def _read_json(lesson_dir: str, name: str) -> Dict[str, Any]:
    path = lesson_path(lesson_dir, name)
    if not fs.isfile(path):
        return {}
    try:
        with fs.open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except Exception:
        return {}


def _write_json(lesson_dir: str, name: str, data: Dict[str, Any]) -> None:
    path = lesson_path(lesson_dir, name)
    tmp_path = path + ".tmp"
    with fs.open(tmp_path, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    fs.replace(tmp_path, path)


def classify_material_page(
    page: Dict[str, Any],
    candidates: List[CandidateSubunit],
    source: Any,
    lesson_dir: str,
    cached: Dict[str, Any],
    *,
    mock: bool = False,
    ctx: Any = None,
) -> Tuple[List[str], List[str]]:
    """
    Classifica una pagina rispetto alle sottounità candidate usando Jev (MF1b).
    Restituisce (assigned_unit_ids, assigned_macro_ids).
    Se passa per 3 o più sottounità della stessa macro, va sotto la macro al posto loro.
    Se il classificatore è spento o in errore: restituisce ([], []).
    """
    if not candidates:
        return [], []

    from rt.core.config import load_config, classifier_job
    from rt.services.enrichment_service import digest, decision
    from rt.llm.jev_client import JevNoulQuestion, JevNoulAnswer
    from rt.llm.client import LLMClient

    cfg = classifier_job(load_config(), "images")
    if cfg.mode == "off":
        return [], []

    threshold = cfg.threshold if getattr(cfg, "threshold", None) is not None else 0.8
    force_mock = LLMClient(force_mock=mock).force_mock

    # Domande noul, una per candidata
    questions: Dict[str, JevNoulQuestion] = {}
    for c in candidates:
        q_key = f"unit_{c.unit_id.replace('.', '_')}"
        questions[q_key] = JevNoulQuestion(
            instructions=f"La pagina spiega o illustra un argomento trattato in modo specifico nella sottounità «{c.title}», non solo la stessa materia."
        )

    # Prompt state: pagina e candidate (~1.500 caratteri di trascritto ciascuna), mai la lezione intera
    candidates_text = "\n\n".join(
        f"### Sottounità {c.unit_id}: {c.title}\n"
        f"Estratto del trascritto:\n{c.transcript[:1500]}"
        for c in candidates
    )
    prompt_state = (
        f"PAGINA DEL MATERIALE (pagina {page['numero']})\n"
        f"{page['testo']}\n\n"
        f"SOTTOUNITÀ CANDIDATE\n"
        f"{candidates_text}"
    )

    pid = f"{source.id}:{page['numero']}"
    key = digest([
        source.impronta,
        page["numero"],
        page["testo"],
        [c.unit_id for c in candidates],
        {k: q.model_dump() for k, q in questions.items()},
        cfg.model,
    ])

    probabilities: Dict[str, float] = {}
    entry = cached.get(pid, {})
    if entry.get("key") == key and "probabilities" in entry:
        probabilities = entry["probabilities"]
    elif force_mock:
        # Mock deterministico: prima candidata 0.9, le altre 0.1
        for idx, c in enumerate(candidates):
            q_key = f"unit_{c.unit_id.replace('.', '_')}"
            probabilities[q_key] = 0.9 if idx == 0 else 0.1
        cached[pid] = {"key": key, "probabilities": probabilities}
        _write_json(lesson_dir, CACHE_FILE, cached)
    else:
        try:
            if ctx:
                ctx.check_cancelled()
            resp = decision(
                prompt_state,
                questions,
                lesson_dir=lesson_dir,
                job_name="image_unit_judge",
                unit_id=pid,
            )
            for k in questions:
                ans = resp.answers.get(k)
                if isinstance(ans, JevNoulAnswer):
                    probabilities[k] = ans.noul
                else:
                    probabilities[k] = 0.0
            cached[pid] = {"key": key, "probabilities": probabilities}
            _write_json(lesson_dir, CACHE_FILE, cached)
        except RunCancelled:
            raise
        except Exception:
            # Il classificatore spento o in errore: nessuna pagina assegnata, la lezione si fa lo stesso
            return [], []

    # Sottounità approvate con probabilità >= soglia
    approved_candidates: List[CandidateSubunit] = []
    for c in candidates:
        q_key = f"unit_{c.unit_id.replace('.', '_')}"
        prob = probabilities.get(q_key, 0.0)
        if prob >= threshold:
            approved_candidates.append(c)

    # Raggruppamento per macro-unità: se >= 3 sottounità della stessa macro, va sotto la macro
    by_macro: Dict[str, List[CandidateSubunit]] = {}
    for c in approved_candidates:
        by_macro.setdefault(c.macro_id, []).append(c)

    assigned_units: List[str] = []
    assigned_macros: List[str] = []

    for macro_id, c_list in by_macro.items():
        if len(c_list) >= 3:
            assigned_macros.append(macro_id)
        else:
            assigned_units.extend(c.unit_id for c in c_list)

    return assigned_units, assigned_macros


@dataclass(frozen=True)
class PageSourceIdentity:
    """Identità minima della fonte per la cache, anche per file caricati senza registro fonti."""
    id: str
    impronta: str


def place_page_in_outline(page, corpus, idf, source, lesson_dir, cached, *, mock=False, ctx=None,
                          mock_fallback=False):
    """Candidate TF-IDF e stessa decisione per import materiali e Arricchimento.

    Il fallback serve soltanto a conservare i fixture storici dell'import in mock.
    I caricamenti senza candidate restano non collocati, anche in mock.
    """
    if ctx:
        ctx.check_cancelled()
    if page.get("mapping_skip"):
        return [], []
    page = {**page, "testo": page.get("mapping_text", page.get("testo", ""))}
    candidates = find_candidate_subunits_for_page(page.get("testo", ""), corpus, idf)
    if not candidates and mock and mock_fallback and corpus and page.get("testo", "").strip():
        entry = corpus[0]
        candidates = [CandidateSubunit(entry.unit_id, entry.macro_id, entry.title, entry.transcript, 1.0)]
    return classify_material_page(page, candidates, source, lesson_dir, cached, mock=mock, ctx=ctx)


def append_page_placements(units, macros, image_hash, assigned_units, assigned_macros):
    """Aggiunge senza cancellare né duplicare le immagini già collocate."""
    for target, ids in ((units, assigned_units), (macros, assigned_macros)):
        for section_id in ids:
            hashes = target.setdefault(section_id, [])
            if image_hash not in hashes:
                hashes.append(image_hash)


def assign_material_pages(
    lesson_dir: str,
    outline: Outline,
    *,
    mock: bool = False,
    ctx: Any = None,
) -> Dict[str, Any]:
    """
    Assegna le pagine dei materiali alle sottounità e macro sezioni (MF1c-MF1e).
    Eseguita prima della rielaborazione.
    """
    from rt.core.sources import load_sources
    from rt.core.state import read_info_yaml
    from rt.core.materials import material_pages
    from rt.core.source_selection import selection
    from rt.core.segments import load_segments_json
    from rt.pipeline.add_images import (
        compute_image_hash,
        load_image_descriptions,
        save_image_descriptions,
        save_raw_image,
    )
    from rt.pipeline.image_placement import (
        load_image_placement,
        save_image_placement,
    )

    sources = [s for s in load_sources(lesson_dir) if s.tipo == "materiale"]
    previous_state = _read_json(lesson_dir, STATE_FILE)
    if not sources and not previous_state:
        return {}

    info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    enabled = str(info.get("allega_materiali", "true")).casefold() not in ("false", "0", "no")

    primary_id = selection(lesson_dir).get("principale")
    segment_path = lesson_path(lesson_dir, "segments.json")
    segments_data = load_segments_json(segment_path) if fs.isfile(segment_path) else SegmentsData()

    corpus, idf = build_subunit_corpus(outline, segments_data)
    cached_decisions = _read_json(lesson_dir, CACHE_FILE)

    units_placement: Dict[str, List[str]] = {}
    macros_placement: Dict[str, List[str]] = {}
    pages_by_unit: Dict[str, List[Dict[str, Any]]] = {}
    pages_by_macro: Dict[str, List[Dict[str, Any]]] = {}

    descriptions = load_image_descriptions(lesson_dir)

    for source in sources:
        is_primary = (source.id == primary_id)
        pages = material_pages(lesson_dir, source, mock=mock, ctx=ctx)

        if is_primary:
            # MF1e: Le pagine del materiale principale diventano segmenti;
            # le loro immagini vanno alla sottounità i cui segmenti le contengono, senza classificatore.
            seg_by_id = {s.id: s for s in segments_data.segments}
            seg_to_unit: Dict[str, str] = {}
            for macro in outline.macro_sections:
                for u in macro.units:
                    start_seg = seg_by_id.get(u.start_segment_id)
                    end_seg = seg_by_id.get(u.end_segment_id)
                    if start_seg and end_seg:
                        for s in segments_data.segments[start_seg.index - 1 : end_seg.index]:
                            seg_to_unit[s.id] = u.id

            source_segs = [s for s in segments_data.segments if getattr(s, "source_file", None) == source.id or "materiale" in getattr(s, "flags", [])]
            for page in pages:
                page_idx = page["numero"] - 1
                target_unit_id = None
                if page_idx < len(source_segs):
                    seg_id = source_segs[page_idx].id
                    target_unit_id = seg_to_unit.get(seg_id)

                if target_unit_id and enabled and page.get("immagini"):
                    for img_rel in page["immagini"]:
                        img_path = os.path.join(lesson_dir, img_rel)
                        if fs.isfile(img_path):
                            with fs.open(img_path, "rb") as stream:
                                data = stream.read()
                            h = compute_image_hash(data)
                            fn = save_raw_image(lesson_dir, data, h)
                            descriptions.setdefault(h, {
                                "filename": fn,
                                "source": f"material:{source.id}:{page['numero']}",
                                "alt_text": f"{os.path.basename(source.file)}, pagina {page['numero']}",
                            })
                            if h not in units_placement.setdefault(target_unit_id, []):
                                units_placement[target_unit_id].append(h)
        else:
            # Materiale non principale: MF1a candidate locali + MF1b classificatore
            for page in pages:
                if ctx:
                    ctx.check_cancelled()
                assigned_units, assigned_macros = place_page_in_outline(
                    page, corpus, idf, source, lesson_dir, cached_decisions,
                    mock=mock, ctx=ctx, mock_fallback=True,
                )

                page_info = {
                    "source_id": source.id,
                    "source_file": os.path.basename(source.file),
                    "page": page["numero"],
                    "text": page["testo"],
                }

                for uid in assigned_units:
                    pages_by_unit.setdefault(uid, []).append(page_info)
                for mid in assigned_macros:
                    pages_by_macro.setdefault(mid, []).append(page_info)

                if enabled and page.get("immagini") and (assigned_units or assigned_macros):
                    for img_rel in page["immagini"]:
                        img_path = os.path.join(lesson_dir, img_rel)
                        if fs.isfile(img_path):
                            with fs.open(img_path, "rb") as stream:
                                data = stream.read()
                            h = compute_image_hash(data)
                            fn = save_raw_image(lesson_dir, data, h)
                            descriptions.setdefault(h, {
                                "filename": fn,
                                "source": f"material:{source.id}:{page['numero']}",
                                "alt_text": f"{os.path.basename(source.file)}, pagina {page['numero']}",
                            })
                            append_page_placements(units_placement, macros_placement, h,
                                                   assigned_units, assigned_macros)

    save_image_descriptions(lesson_dir, descriptions)

    state = {
        "units": units_placement if enabled else {},
        "macros": macros_placement if enabled else {},
        "pages_by_unit": pages_by_unit,
        "pages_by_macro": pages_by_macro,
    }
    _write_json(lesson_dir, STATE_FILE, state)

    placement = load_image_placement(lesson_dir) or {"macros": {}, "units": {}, "carousel": False}
    # Si tolgono soltanto le immagini messe dall'assegnazione precedente (anche quella della
    # 4.2.5, sotto le macro): le immagini a mano o dal web restano dove sono.
    old_macros = previous_state.get("macros", {}) or {}
    old_units = previous_state.get("units", {}) or {}
    new_macros = {mid: [h for h in hashes if h not in old_macros.get(mid, [])]
                  for mid, hashes in placement.get("macros", {}).items()}
    new_units = {uid: [h for h in hashes if h not in old_units.get(uid, [])]
                 for uid, hashes in placement.get("units", {}).items()}
    if enabled:
        for mid, h_list in macros_placement.items():
            existing = new_macros.setdefault(mid, [])
            existing.extend(h for h in h_list if h not in existing)
        for uid, h_list in units_placement.items():
            existing = new_units.setdefault(uid, [])
            existing.extend(h for h in h_list if h not in existing)
    save_image_placement(lesson_dir, macros=new_macros, units=new_units, carousel=placement.get("carousel", False))

    return state


def clear_material_context(lesson_dir: str) -> None:
    """Assegnazione non riuscita: nessuna pagina va nel contesto (le immagini restano)."""
    state = _read_json(lesson_dir, STATE_FILE)
    if state.get("pages_by_unit") or state.get("pages_by_macro"):
        state.update(pages_by_unit={}, pages_by_macro={})
        _write_json(lesson_dir, STATE_FILE, state)


def material_context_for_unit(lesson_dir: str, unit_id: str, macro_id: str) -> str:
    """
    Restituisce il testo dei materiali assegnati a una sottounità (MF1d):
    solo il testo delle sue pagine e di quelle assegnate alla sua unità madre.
    """
    state = _read_json(lesson_dir, STATE_FILE)
    if not state:
        return ""
    pages_by_unit = state.get("pages_by_unit", {})
    pages_by_macro = state.get("pages_by_macro", {})

    items: List[Dict[str, Any]] = []
    # Prima le pagine della macro unità
    items.extend(pages_by_macro.get(str(macro_id), []))
    # Poi le pagine specifiche della sottounità
    items.extend(pages_by_unit.get(str(unit_id), []))

    if not items:
        return ""

    seen = set()
    parts = []
    for item in items:
        key = (item.get("source_id"), item.get("page"))
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"[Fonte: {item.get('source_file')}, pag. {item.get('page')}]\n{item.get('text', '')}")

    return "\n\n".join(parts)
