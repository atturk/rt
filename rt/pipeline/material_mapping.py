"""
rt.pipeline.material_mapping
Assegnazione delle pagine dei materiali alle sottounità didattiche (MF1).
- MF1a: Ricerca locale delle candidate con TF-IDF, rimozione stopwords italiane
  (inclusi intercalari del parlato) e stemmer italiano puro Python.
- MF1b: Valutazione sì/no tramite Jev Decision API con aggregazione a macro-unità (>= 3).
- MF1c-MF1e: Integrazione nella pipeline prima della rielaborazione.
"""

import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

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
