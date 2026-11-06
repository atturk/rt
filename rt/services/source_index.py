"""
rt.services.source_index
Indice delle pagine dei materiali della lezione per la verifica scientifica.
Unisce testo estratto dal PDF e OCR/descrizione Vision, con normalizzazione
per formule/testo e ricerca BM25/TF-IDF.
"""

from __future__ import annotations

import base64
import io
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from rt.core.lesson_paths import lesson_path
from rt.core.sources import load_sources, Source
from rt.pipeline.add_images import load_image_descriptions
from rt.storage import fs


def normalize_text(text: str) -> str:
    """
    Normalizza il testo per la ricerca:
    minuscole, via spazi e comandi LaTeX (\\mathrm, \\left, ecc.), via graffe e parentesi.
    Rende uguali 'w + 1', '(w+1)' e 'w+1'.
    """
    if not text:
        return ""
    t = text.lower()
    # Rimuovi comandi LaTeX come \mathrm, \left, \right, \text, \bm, etc.
    t = re.sub(r"\\[a-zA-Z]+", "", t)
    # Rimuovi parentesi e graffe: (), {}, []
    t = re.sub(r"[(){}\[\]]", "", t)
    # Rimuovi spazi e caratteri di spaziatura
    t = re.sub(r"\s+", "", t)
    return t


def tokenize_search_terms(text: str) -> List[str]:
    """Estrae token per la ricerca BM25 sia come parole che come espressioni matematiche normalizzate."""
    if not text:
        return []
    cleaned = text.lower()
    # Rimuovi comandi LaTeX
    cleaned = re.sub(r"\\[a-zA-Z]+", " ", cleaned)
    # Parentesi e graffe rimosse
    cleaned = re.sub(r"[(){}\[\]]", " ", cleaned)

    tokens: List[str] = []
    # Parole standard
    for word in re.findall(r"\w+", cleaned):
        if len(word) > 1 or word.isalpha():
            tokens.append(word)

    # Espressioni con operatori matematici (+, -, *, /, =, <, >, _, ^)
    norm = normalize_text(text)
    math_chunks = re.findall(r"[a-z0-9]+[\+\-\*\/\=\<\>\_\^][a-z0-9]+", norm)
    for chunk in math_chunks:
        if chunk not in tokens:
            tokens.append(chunk)

    # Aggiungi anche la forma normalizzata completa se corta (es. formule brevi come w+1)
    if norm and len(norm) <= 20 and norm not in tokens:
        tokens.append(norm)

    return tokens


@dataclass
class IndexedPage:
    source_id: str
    source_file: str
    page_number: int
    pdf_text: str
    desc_text: str
    combined_text: str
    tokens: List[str]
    attached_unit_ids: Set[str] = field(default_factory=set)
    attached_macro_ids: Set[str] = field(default_factory=set)
    affidabilita: str = "normale"


@dataclass
class SourcePageMatch:
    fonte: str
    pagina: int
    testo: str
    da_descrizione: bool
    score: float = 0.0
    source_id: str = ""
    affidabilita: str = "normale"


class SourceIndex:
    """Indice BM25 delle pagine dei materiali della lezione."""

    def __init__(self, lesson_dir: str):
        self.lesson_dir = lesson_dir
        self.pages: List[IndexedPage] = []
        self._build_index()

    def _build_index(self) -> None:
        from rt.core.materials import cached_pages, material_pages
        from rt.pipeline.material_mapping import STATE_FILE, _read_json

        sources = [s for s in load_sources(self.lesson_dir) if s.tipo == "materiale" and not s.rimossa_il]
        if not sources:
            return

        state = _read_json(self.lesson_dir, STATE_FILE) or {}
        pages_by_unit = state.get("pages_by_unit", {})
        pages_by_macro = state.get("pages_by_macro", {})

        descriptions = load_image_descriptions(self.lesson_dir)

        # Mappa (source_id, page_number) -> set di unit_ids e macro_ids
        page_attached_units: Dict[Tuple[str, int], Set[str]] = {}
        page_attached_macros: Dict[Tuple[str, int], Set[str]] = {}

        for u_id, items in pages_by_unit.items():
            for it in items:
                sid = str(it.get("source_id", ""))
                pnum = int(it.get("page", 0))
                page_attached_units.setdefault((sid, pnum), set()).add(str(u_id))

        for m_id, items in pages_by_macro.items():
            for it in items:
                sid = str(it.get("source_id", ""))
                pnum = int(it.get("page", 0))
                page_attached_macros.setdefault((sid, pnum), set()).add(str(m_id))

        for source in sources:
            source_pages = cached_pages(self.lesson_dir, source)
            if source_pages is None:
                try:
                    source_pages = material_pages(self.lesson_dir, source, mock=True)
                except Exception:
                    source_pages = []

            for p in source_pages:
                pnum = int(p.get("numero", 0))
                pdf_text = str(p.get("testo") or "")

                # Cerca descrizione OCR / Vision per questa pagina
                desc_parts: List[str] = []
                # Da descriptions caricate
                for desc in descriptions.values():
                    src_tag = str(desc.get("source") or "")
                    if f"material:{source.id}:{pnum}" in src_tag or f"{source.file}" in src_tag:
                        for k in ("slide_title", "ocr_text", "visual_elements", "summary_keywords", "alt_text"):
                            val = desc.get(k)
                            if val:
                                desc_parts.append(" ".join(map(str, val)) if isinstance(val, list) else str(val))

                # Anche dall'archivio (descrizione.json se esiste)
                from rt.core.archive import entry_dir, read_json
                arch_desc = read_json(os.path.join(entry_dir(source.impronta), "descrizione.json"), {}) or {}
                for k in ("slide_title", "ocr_text", "visual_elements", "summary_keywords", "alt_text"):
                    val = arch_desc.get(k)
                    if val:
                        desc_parts.append(" ".join(map(str, val)) if isinstance(val, list) else str(val))

                desc_text = "\n".join(desc_parts)
                combined_text = (pdf_text + "\n" + desc_text).strip() if desc_text else pdf_text

                tokens = tokenize_search_terms(combined_text)
                attached_u = page_attached_units.get((source.id, pnum), set())
                attached_m = page_attached_macros.get((source.id, pnum), set())

                self.pages.append(
                    IndexedPage(
                        source_id=source.id,
                        source_file=source.file,
                        page_number=pnum,
                        pdf_text=pdf_text,
                        desc_text=desc_text,
                        combined_text=combined_text,
                        tokens=tokens,
                        attached_unit_ids=attached_u,
                        attached_macro_ids=attached_m,
                        affidabilita=source.affidabilita or "normale",
                    )
                )

    def _score_bm25(self, candidate_pages: List[IndexedPage], query: str) -> List[Tuple[float, IndexedPage, bool]]:
        """Calcola il punteggio BM25 per ogni pagina candidata. Ritorna (score, page, da_descrizione)."""
        query_tokens = tokenize_search_terms(query)
        norm_query = normalize_text(query)
        if not query_tokens and not norm_query:
            return []

        N = len(self.pages) or len(candidate_pages)
        if N == 0:
            return []

        # Document frequencies su tutto il corpus
        df: Dict[str, int] = {}
        for p in self.pages:
            seen_tokens = set(p.tokens)
            for t in seen_tokens:
                df[t] = df.get(t, 0) + 1

        avgdl = sum(len(p.tokens) for p in candidate_pages) / len(candidate_pages) if candidate_pages else 1.0
        k1 = 1.5
        b = 0.75

        scored: List[Tuple[float, IndexedPage, bool]] = []
        for p in candidate_pages:
            doc_len = len(p.tokens)
            score = 0.0
            matched_in_pdf = False
            matched_in_desc = False

            norm_pdf = normalize_text(p.pdf_text)
            norm_desc = normalize_text(p.desc_text)

            for q in query_tokens:
                n_q = df.get(q, 0)
                idf = math.log(1.0 + (N - n_q + 0.5) / (n_q + 0.5))
                f_q = p.tokens.count(q)
                if f_q > 0:
                    score += idf * (f_q * (k1 + 1.0)) / (f_q + k1 * (1.0 - b + b * (doc_len / avgdl)))
                    if q in p.pdf_text.lower() or (len(q) >= 2 and q in norm_pdf):
                        matched_in_pdf = True
                    if q in p.desc_text.lower() or (len(q) >= 2 and q in norm_desc):
                        matched_in_desc = True

            # Boost per match esatto normalizzato (es. formule come w+1)
            if norm_query and len(norm_query) >= 2:
                if norm_query in norm_pdf:
                    score += 15.0
                    matched_in_pdf = True
                elif norm_query in norm_desc:
                    score += 15.0
                    matched_in_desc = True

            if score > 0:
                da_descrizione = matched_in_desc and not matched_in_pdf
                scored.append((score, p, da_descrizione))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def search(
        self,
        query: str,
        unit_id: Optional[str] = None,
        macro_id: Optional[str] = None,
    ) -> List[SourcePageMatch]:
        """
        Cerca le pagine migliori per la query.
        Prima cerca nelle pagine agganciate all'unità, poi in tutte le pagine della lezione.
        Restituisce fino a 3 pagine migliori.
        """
        if not self.pages:
            return []

        # 1. Pagine agganciate all'unità o alla sua macro-sezione
        attached: List[IndexedPage] = []
        if unit_id or macro_id:
            for p in self.pages:
                if (unit_id and unit_id in p.attached_unit_ids) or (macro_id and macro_id in p.attached_macro_ids):
                    attached.append(p)

        if attached:
            attached_scored = self._score_bm25(attached, query)
            if attached_scored:
                return [
                    SourcePageMatch(
                        fonte=os.path.basename(page.source_file),
                        pagina=page.page_number,
                        testo=page.combined_text,
                        da_descrizione=da_desc,
                        score=score,
                        source_id=page.source_id,
                        affidabilita=page.affidabilita,
                    )
                    for score, page, da_desc in attached_scored[:3]
                ]

        # 2. Tutte le pagine della lezione
        all_scored = self._score_bm25(self.pages, query)
        return [
            SourcePageMatch(
                fonte=os.path.basename(page.source_file),
                pagina=page.page_number,
                testo=page.combined_text,
                da_descrizione=da_desc,
                score=score,
                source_id=page.source_id,
                affidabilita=page.affidabilita,
            )
            for score, page, da_desc in all_scored[:3]
        ]

    def render_page_png(self, source_file_or_id: str, page_number: int) -> Optional[bytes]:
        """Rende la pagina specificata in formato PNG a 2x risoluzione."""
        target_source: Optional[Source] = None
        for s in load_sources(self.lesson_dir):
            if s.id == source_file_or_id or os.path.basename(s.file) == source_file_or_id or s.file == source_file_or_id:
                target_source = s
                break

        if not target_source:
            return None

        # Controlla prima se c'è un'immagine già renderizzata nell'archivio
        from rt.core.archive import entry_dir
        folder = entry_dir(target_source.impronta)
        candidate_rel = f"page-{page_number}-1.png"
        arch_path = os.path.join(folder, candidate_rel)
        if fs.isfile(arch_path):
            with fs.open(arch_path, "rb") as f:
                return f.read()

        real_path = os.path.join(self.lesson_dir, target_source.file)
        if not fs.isfile(real_path):
            return None

        suffix = os.path.splitext(real_path)[1].lower()
        if suffix == ".pdf":
            try:
                import pymupdf as fitz
                with fitz.open(real_path) as doc:
                    if 1 <= page_number <= len(doc):
                        return doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
            except Exception:
                return None
        elif suffix in (".png", ".jpg", ".jpeg", ".heic"):
            try:
                from PIL import Image, ImageOps
                try:
                    from pillow_heif import register_heif_opener
                    register_heif_opener()
                except ImportError:
                    pass
                with fs.open(real_path, "rb") as f:
                    data = f.read()
                with Image.open(io.BytesIO(data)) as img:
                    out = io.BytesIO()
                    ImageOps.exif_transpose(img).convert("RGB").save(out, format="PNG")
                    return out.getvalue()
            except Exception:
                return None

        return None
