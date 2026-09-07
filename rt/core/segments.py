"""
rt.core.segments
Gestione fondamentale dei segmenti ASR (Source of Truth).
Supporta sia l'export JSON nativo di MacWhisper sia il parsing di trascritto grezzo.md.
"""

from typing import List, Tuple, Dict, Any, Optional
import os
import json
import re
from rt.core.models import Segment, SegmentsData
from rt.core.timestamp import parse_timestamp, format_timestamp, parse_interval
from rt.core.encoding import fix_mojibake, sanitize_object_encoding

MD_TIMESTAMP_PATTERN = re.compile(r"^\*(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[-–—]\s*\d{1,2}:\d{2}(?::\d{2})?)?)\*$")


def make_segment_id(index: int) -> str:
    """Genera ID segmento stabile e univoco (es. seg_000001)."""
    return f"seg_{index:06d}"


def parse_segments_from_json(json_path: str) -> List[Segment]:
    """
    Parsa segmenti da un file JSON ASR.
    Supporta:
    1. Formato MacWhisper: { "segments": [ { "start": ms, "end": ms, "text": "...", ... } ] }
    2. Formato lista: [ { "text": "...", "timestamp": "00:02-00:12" } ]
    3. Formato lista SegmentsData già normalizzato.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    raw_list: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        if "segments" in data and isinstance(data["segments"], list):
            raw_list = data["segments"]
        else:
            raise ValueError(f"Formato JSON non riconosciuto in '{json_path}'")
    elif isinstance(data, list):
        raw_list = data
    else:
        raise ValueError(f"Contenuto JSON non valido in '{json_path}'")
    
    parsed_segments: List[Segment] = []
    
    for i, item in enumerate(raw_list, start=1):
        seg_id = make_segment_id(i)
        
        # Caso 1: MacWhisper (start ed end in millisecondi)
        if "start" in item and "end" in item and isinstance(item["start"], (int, float)):
            # MacWhisper esporta sempre start/end in millisecondi (es. 2720 per 2.72s)
            start_val = float(item["start"])
            end_val = float(item["end"])
            start_sec = round(start_val / 1000.0, 3)
            end_sec = round(end_val / 1000.0, 3)
            
            if end_sec <= start_sec:
                end_sec = start_sec + 1.0 # Fallback minimo
            
            text = fix_mojibake(str(item.get("text", "")).strip())
            
            parsed_segments.append(Segment(
                id=seg_id,
                index=i,
                start_seconds=start_sec,
                end_seconds=end_sec,
                start_formatted=format_timestamp(start_sec),
                end_formatted=format_timestamp(end_sec),
                text_raw=text,
                source_file=os.path.basename(json_path),
                speaker=item.get("speaker"),
                confidence=item.get("confidence")
            ))
            
        # Caso 2: timestamp stringa (es. "00:02-00:12" o "00:02")
        elif "timestamp" in item:
            ts_str = str(item["timestamp"]).strip()
            text = fix_mojibake(str(item.get("text", "")).strip())
            
            if "-" in ts_str or "–" in ts_str or "—" in ts_str:
                start_sec, end_sec = parse_interval(ts_str)
            else:
                start_sec = parse_timestamp(ts_str)
                end_sec = start_sec + 5.0 # Verrà raffinato dopo
            
            parsed_segments.append(Segment(
                id=seg_id,
                index=i,
                start_seconds=start_sec,
                end_seconds=end_sec,
                start_formatted=format_timestamp(start_sec),
                end_formatted=format_timestamp(end_sec),
                text_raw=text,
                source_file=os.path.basename(json_path)
            ))
            
        # Caso 3: Segment già conforme
        elif "id" in item and "start_seconds" in item and "text_raw" in item:
            parsed_segments.append(Segment.model_validate(sanitize_object_encoding(item)))
            
        else:
            raise ValueError(f"Elemento segmento non riconosciuto all'indice {i}: {item}")
            
    return validate_and_refine_segments(parsed_segments)


def parse_segments_from_markdown(md_path: str) -> List[Segment]:
    """
    Parsa segmenti da un trascritto Markdown grezzo (es. generato da mw --format md).
    Riconosce blocchi tipo:
    *00:02*
    testo del segmento...
    
    oppure:
    *00:02-00:06*
    testo del segmento...
    """
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Rimuove eventuale blocco YAML frontmatter iniziale
    content_no_yaml = re.sub(r"^\s*---\s*\n[\s\S]*?\n---\s*\n", "", content)
    
    lines = content_no_yaml.splitlines()
    raw_blocks: List[Tuple[str, List[str]]] = []
    
    current_ts: Optional[str] = None
    current_text_lines: List[str] = []
    
    for line in lines:
        stripped = line.strip()
        m = MD_TIMESTAMP_PATTERN.match(stripped)
        if m:
            if current_ts is not None:
                raw_blocks.append((current_ts, current_text_lines))
            current_ts = m.group(1)
            current_text_lines = []
        else:
            if stripped:
                current_text_lines.append(stripped)
    
    if current_ts is not None:
        raw_blocks.append((current_ts, current_text_lines))
    
    # Prima raccogliamo le informazioni grezze: (start_sec, end_sec_or_none, text)
    raw_parsed: List[Tuple[float, Optional[float], str]] = []
    for ts_str, text_lines in raw_blocks:
        text = " ".join(text_lines).strip()
        if "-" in ts_str or "–" in ts_str or "—" in ts_str:
            s_sec, e_sec = parse_interval(ts_str)
            raw_parsed.append((s_sec, e_sec, text))
        else:
            s_sec = parse_timestamp(ts_str)
            raw_parsed.append((s_sec, None, text))
    
    segments: List[Segment] = []
    for i, (start_sec, end_sec, text) in enumerate(raw_parsed, start=1):
        seg_id = make_segment_id(i)
        if end_sec is None or end_sec <= start_sec:
            if i < len(raw_parsed):
                next_start = raw_parsed[i][0] # i è già l'indice successivo perché enumerate parte da 1
                if next_start > start_sec:
                    resolved_end = next_start
                else:
                    resolved_end = start_sec + 1.0
            else:
                resolved_end = start_sec + 6.0
        else:
            resolved_end = end_sec
            
        segments.append(Segment(
            id=seg_id,
            index=i,
            start_seconds=start_sec,
            end_seconds=resolved_end,
            start_formatted=format_timestamp(start_sec),
            end_formatted=format_timestamp(resolved_end),
            text_raw=text,
            source_file=os.path.basename(md_path)
        ))
    
    return validate_and_refine_segments(segments)


def validate_and_refine_segments(segments: List[Segment]) -> List[Segment]:
    """
    Valida e segnala anomalie nei segmenti:
    - ID univoci
    - Indici univoci e sequenziali
    - start >= 0
    - end > start
    - Segnala gap o overlap tramite flags senza alterare il dato sorgente
    """
    if not segments:
        raise ValueError("Nessun segmento trovato nel file di trascrizione")
    
    seen_ids = set()
    for i, seg in enumerate(segments):
        if seg.id in seen_ids:
            raise ValueError(f"ID segmento duplicato rilevato: {seg.id}")
        seen_ids.add(seg.id)
        
        if seg.start_seconds < 0:
            raise ValueError(f"Segmento {seg.id} ha start_seconds negativo: {seg.start_seconds}")
        if seg.end_seconds <= seg.start_seconds:
            raise ValueError(f"Segmento {seg.id} ha end_seconds ({seg.end_seconds}) <= start_seconds ({seg.start_seconds})")
        
        # Flag per anomalie temporali con il segmento precedente
        if i > 0:
            prev = segments[i - 1]
            if seg.start_seconds < prev.start_seconds:
                seg.flags.append("TIME_INVERSION")
            elif seg.start_seconds < prev.end_seconds:
                overlap = prev.end_seconds - seg.start_seconds
                if overlap > 0.1:
                    seg.flags.append(f"OVERLAP_{overlap:.1f}s")
            elif seg.start_seconds > prev.end_seconds:
                gap = seg.start_seconds - prev.end_seconds
                if gap > 5.0:
                    seg.flags.append(f"GAP_{gap:.1f}s")
                    
    return segments


def save_segments_json(segments: List[Segment], output_path: str, lesson_id: Optional[str] = None) -> None:
    """Salva i segmenti strutturati in segments.json in modo atomico."""
    duration = segments[-1].end_seconds if segments else 0.0
    data = SegmentsData(
        schema_version="1.0",
        lesson_id=lesson_id,
        audio_duration_seconds=duration,
        segments=segments
    )
    
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(sanitize_object_encoding(data.model_dump(mode="json")), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, output_path)


def load_segments_json(segments_path: str) -> SegmentsData:
    """Carica segments.json."""
    if not os.path.isfile(segments_path):
        raise FileNotFoundError(f"segments.json non trovato in '{segments_path}'")
    with open(segments_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cleaned_data = sanitize_object_encoding(data)
    return SegmentsData.model_validate(cleaned_data)


def export_normalized_transcript_md(segments: List[Segment], output_path: str) -> None:
    """Esporta transcript_normalized.md con segment ID e timecode per facilitare la lettura umana."""
    lines = ["# Trascritto Normalizzato con Riferimento Segmenti\n\n"]
    for seg in segments:
        flags_str = f" `[{', '.join(seg.flags)}]`" if seg.flags else ""
        lines.append(f"**[{seg.id}]** `{seg.start_formatted} - {seg.end_formatted}`{flags_str}\n")
        lines.append(f"{seg.text_raw}\n\n")
        
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp_path, output_path)
