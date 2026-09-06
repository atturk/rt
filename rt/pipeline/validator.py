"""
rt.pipeline.validator
Validatore deterministico per Outline, Draft, Copertura didattica e Provenance.
Nessun output LLM viene accettato se non supera questa validazione.
"""

from typing import Dict, Any, List, Set
from rt.core.models import Outline, SegmentsData, Draft, Segment


class ValidationError(Exception):
    pass


def validate_outline(outline: Outline, segments_data: SegmentsData) -> Dict[str, Any]:
    """
    Valida l'outline in modo deterministico:
    1. Esistenza di tutti i segment_id in segments.json
    2. Start segment index <= End segment index
    3. Monotonicità temporale (ordine cronologico tra unità consecutive)
    4. Assenza di sovrapposizioni illogiche tra unità didattiche
    5. Titoli non vuoti e struttura gerarchica corretta
    6. Calcolo della copertura del trascritto (segmenti coperti, omessi, duplicati)
    """
    if not outline.macro_sections:
        raise ValidationError("L'outline non contiene alcuna macro-sezione.")
    
    seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}
    total_segments_count = len(segments_data.segments)
    
    seen_unit_ids: Set[str] = set()
    covered_indices: Set[int] = set()
    duplicate_indices: Set[int] = set()
    
    last_end_index = 0
    units_count = 0
    
    for m_idx, macro in enumerate(outline.macro_sections):
        if not macro.title.strip():
            raise ValidationError(f"Macro-sezione #{m_idx+1} (ID '{macro.id}') ha un titolo vuoto.")
        if not macro.units:
            raise ValidationError(f"Macro-sezione '{macro.title}' non contiene unità didattiche.")
            
        for u_idx, unit in enumerate(macro.units):
            units_count += 1
            if unit.id in seen_unit_ids:
                raise ValidationError(f"ID unità duplicato rilevato: '{unit.id}'")
            seen_unit_ids.add(unit.id)
            
            if not unit.title.strip():
                raise ValidationError(f"Unità didattica '{unit.id}' ha un titolo vuoto.")
                
            start_seg = seg_by_id.get(unit.start_segment_id)
            if not start_seg:
                raise ValidationError(f"Unità '{unit.id}': start_segment_id '{unit.start_segment_id}' non esiste nei segmenti.")
                
            end_seg = seg_by_id.get(unit.end_segment_id)
            if not end_seg:
                raise ValidationError(f"Unità '{unit.id}': end_segment_id '{unit.end_segment_id}' non esiste nei segmenti.")
                
            if start_seg.index > end_seg.index:
                raise ValidationError(
                    f"Unità '{unit.id}': start_segment ({unit.start_segment_id}, idx {start_seg.index}) "
                    f"è successivo a end_segment ({unit.end_segment_id}, idx {end_seg.index})"
                )
                
            # Controllo monotonicità con l'unità precedente
            if start_seg.index < last_end_index:
                raise ValidationError(
                    f"Inversione cronologica o sovrapposizione anomala nell'unità '{unit.id}': "
                    f"start index {start_seg.index} precede l'end index della sezione precedente ({last_end_index})"
                )
            last_end_index = end_seg.index
            
            # Traccia indici coperti
            for idx in range(start_seg.index, end_seg.index + 1):
                if idx in covered_indices:
                    duplicate_indices.add(idx)
                covered_indices.add(idx)
                
    omitted_indices = set(range(1, total_segments_count + 1)) - covered_indices
    coverage_ratio = len(covered_indices) / total_segments_count if total_segments_count > 0 else 0.0
    
    report = {
        "valid": True,
        "macro_count": len(outline.macro_sections),
        "units_count": units_count,
        "total_segments": total_segments_count,
        "covered_segments": len(covered_indices),
        "coverage_percentage": round(coverage_ratio * 100, 2),
        "omitted_count": len(omitted_indices),
        "duplicate_count": len(duplicate_indices),
        "omitted_ranges": _summarize_index_ranges(omitted_indices)
    }
    return report


def validate_draft(draft: Draft, outline: Outline, segments_data: SegmentsData) -> Dict[str, Any]:
    """
    Valida il Draft rielaborato:
    1. Corrispondenza e ordine delle unità rispetto all'Outline
    2. Validità di tutti i source_segment_ids nella provenance
    3. Vincolo di intervallo: ogni source_segment_id deve appartenere all'intervallo outline dell'unità
       [out.start_segment_id .. out.end_segment_id] senza richiedere copertura 1:1 (provenance selettiva accademica)
    4. Monotonicità cronologica dei segmenti all'interno di ciascuna unità (nessuna inversione temporale)
    5. Presenza di contenuto non vuoto
    6. Assicura che per ogni unità sia ricostruibile il timecode audio esatto
    """
    seg_by_id: Dict[str, Segment] = {s.id: s for s in segments_data.segments}
    outline_units: Dict[str, Any] = {}
    expected_order: List[str] = []
    for macro in outline.macro_sections:
        for u in macro.units:
            outline_units[u.id] = u
            expected_order.append(u.id)
            
    if not draft.units:
        raise ValidationError("Il Draft non contiene alcuna unità rielaborata.")
        
    draft_unit_ids = set()
    actual_order: List[str] = []
    provenance_verified = 0
    total_source_segments_used = 0
    
    for u in draft.units:
        if u.unit_id not in outline_units:
            raise ValidationError(f"Unità nel Draft '{u.unit_id}' non trovata nell'Outline.")
        if u.unit_id in draft_unit_ids:
            raise ValidationError(f"Unità duplicata nel Draft: '{u.unit_id}'")
        draft_unit_ids.add(u.unit_id)
        actual_order.append(u.unit_id)
        
        if not u.content.strip():
            raise ValidationError(f"Unità '{u.unit_id}' ha un contenuto vuoto.")
            
        if not u.source_segment_ids:
            raise ValidationError(f"Unità '{u.unit_id}' è priva di source_segment_ids (provenance vuota).")
            
        # Recupera i limiti stabiliti dall'outline per questa unità
        out_unit = outline_units[u.unit_id]
        out_start_seg = seg_by_id.get(out_unit.start_segment_id)
        out_end_seg = seg_by_id.get(out_unit.end_segment_id)
        if not out_start_seg:
            raise ValidationError(f"Unità '{u.unit_id}': start_segment_id '{out_unit.start_segment_id}' inesistente nei segmenti.")
        if not out_end_seg:
            raise ValidationError(f"Unità '{u.unit_id}': end_segment_id '{out_unit.end_segment_id}' inesistente nei segmenti.")
            
        # Verifica ogni ID sorgente e la monotonicità all'interno dell'unità
        last_seg_index = -1
        for s_id in u.source_segment_ids:
            s = seg_by_id.get(s_id)
            if not s:
                raise ValidationError(f"Unità '{u.unit_id}': source_segment_id '{s_id}' inesistente nei segmenti.")
                
            # Verifica che il segmento ricada nell'intervallo dell'outline
            if s.index < out_start_seg.index or s.index > out_end_seg.index:
                raise ValidationError(
                    f"Unità '{u.unit_id}': il segmento '{s_id}' (indice {s.index}) è esterno all'intervallo outline "
                    f"[{out_unit.start_segment_id}..{out_unit.end_segment_id}] (indici {out_start_seg.index}..{out_end_seg.index})"
                )
                
            # Monotonicità temporale all'interno dell'unità
            if s.index <= last_seg_index:
                raise ValidationError(
                    f"Unità '{u.unit_id}': inversione cronologica o duplicato nella provenance "
                    f"per il segmento '{s_id}' (indice {s.index} <= {last_seg_index})"
                )
            last_seg_index = s.index
            
        # Verifica che il segmento iniziale esista e fornisca il timestamp esatto
        start_seg = seg_by_id.get(u.start_segment_id)
        if not start_seg:
            raise ValidationError(f"Unità '{u.unit_id}': start_segment_id '{u.start_segment_id}' inesistente.")
            
        provenance_verified += 1
        total_source_segments_used += len(u.source_segment_ids)

    # Verifica sequenza e ordinamento gerarchico delle unità rispetto all'outline
    expected_subsequence = [uid for uid in expected_order if uid in draft_unit_ids]
    if actual_order != expected_subsequence:
        raise ValidationError(
            f"Le unità nel Draft non rispettano l'ordine cronologico dell'Outline. "
            f"Ordine effettivo: {actual_order}, Ordine atteso: {expected_subsequence}"
        )
        
    return {
        "valid": True,
        "draft_units_count": len(draft.units),
        "expected_units_count": len(outline_units),
        "all_units_covered": len(draft.units) == len(outline_units),
        "provenance_verified_units": provenance_verified,
        "total_source_segments_used": total_source_segments_used
    }


def _summarize_index_ranges(indices: Set[int]) -> List[str]:
    """Sintetizza un set di indici in una lista leggibile di intervalli (es. ['1-3', '45-48'])."""
    if not indices:
        return []
    sorted_idx = sorted(list(indices))
    ranges = []
    start = sorted_idx[0]
    prev = sorted_idx[0]
    
    for x in sorted_idx[1:]:
        if x == prev + 1:
            prev = x
        else:
            ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = x
            prev = x
    ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ranges
