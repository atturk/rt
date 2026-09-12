"""
rt.core.asr_risk
Rilevamento statistico deterministico del rischio ASR basato su wordTimestamps e confidenza per-parola.
"""

import os
import json
from typing import List, Dict, Any, Optional, Tuple
from rt.core.models import Segment, ScienceIssue, ScienceType, ScienceSeverity, Draft
from rt.core.lesson_paths import lesson_path
from rt.pipeline.rewrite import load_draft


def _calculate_p10(vals: List[float]) -> float:
    """Calcola il 10° percentile di una lista di valori float (o il minimo se meno di 3 elementi)."""
    if not vals:
        return 0.0
    if len(vals) < 3:
        return float(min(vals))
    s = sorted(vals)
    idx = 0.10 * (len(s) - 1)
    i = int(idx)
    f = idx - i
    if i >= len(s) - 1:
        return float(s[-1])
    return float(s[i] + f * (s[i + 1] - s[i]))


def _calculate_median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    else:
        return float((s[mid - 1] + s[mid]) / 2.0)


def _calculate_mad(vals: List[float], median_val: float) -> float:
    devs = [abs(x - median_val) for x in vals]
    return _calculate_median(devs)


def detect_statistical_asr_risks(
    lesson_dir: str,
    k: float = 3.0,
    floor: float = 0.35,
) -> List[ScienceIssue]:
    """
    Individua i segmenti ASR con confidenza significativamente degradata
    rispetto alla norma della lezione (o sotto la soglia di sicurezza)
    e genera una ScienceIssue di tipo ERR_ASR_ST per ciascuna unità didattica interessata.
    """
    raw_json_path = lesson_path(lesson_dir, "trascritto grezzo.json")
    if not os.path.isfile(raw_json_path):
        return []

    try:
        with open(raw_json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception:
        return []

    if not isinstance(raw_data, dict):
        return []

    word_timestamps = raw_data.get("wordTimestamps", [])
    raw_segments = raw_data.get("transcriptSegments") or raw_data.get("segments") or []
    if not isinstance(word_timestamps, list) or not isinstance(raw_segments, list):
        return []

    # 1. Calcola la metrica di rischio per segmento
    valid_seg_metrics: List[Tuple[str, str, float]] = []  # (seg_id, text_raw, metric)

    for i, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        seg_id = f"seg_{i:06d}"
        w_range = item.get("wordRange")
        if not isinstance(w_range, dict):
            continue
        s_idx = w_range.get("startIndex")
        e_idx = w_range.get("endIndexExclusive")
        if not (isinstance(s_idx, int) and isinstance(e_idx, int) and 0 <= s_idx < e_idx <= len(word_timestamps)):
            continue

        word_confs = [
            w["confidence"] for w in word_timestamps[s_idx:e_idx]
            if isinstance(w, dict) and isinstance(w.get("confidence"), (int, float))
        ]
        if not word_confs:
            continue

        metric = _calculate_p10(word_confs)
        text_raw = str(item.get("text", "")).strip()
        valid_seg_metrics.append((seg_id, text_raw, metric))

    if not valid_seg_metrics:
        return []

    metrics_list = [m for _, _, m in valid_seg_metrics]
    median_val = _calculate_median(metrics_list)
    mad_val = _calculate_mad(metrics_list, median_val)
    mad_scaled = mad_val * 1.4826

    use_stat_test = (len(metrics_list) >= 10) and (mad_val > 0)
    threshold_stat = (median_val - k * mad_scaled) if use_stat_test else None

    # 2. Flagga i segmenti degradati
    flagged_map: Dict[str, Tuple[str, float, bool]] = {}  # seg_id -> (text_raw, metric, is_floor)

    for seg_id, text_raw, metric in valid_seg_metrics:
        is_floor = (metric < floor)
        is_stat = (threshold_stat is not None) and (metric < threshold_stat)
        if is_floor or is_stat:
            flagged_map[seg_id] = (text_raw, metric, is_floor)

    if not flagged_map:
        return []

    # 3. Raggruppa per unità didattica
    try:
        draft = load_draft(lesson_dir)
    except Exception:
        return []

    units_flagged: Dict[str, List[Tuple[str, str, float, bool]]] = {}  # unit_id -> list of (seg_id, text_raw, metric, is_floor)

    for unit in draft.units:
        unit_flags = []
        for s_id in unit.source_segment_ids:
            if s_id in flagged_map:
                text_raw, metric, is_floor = flagged_map[s_id]
                unit_flags.append((s_id, text_raw, metric, is_floor))
        if unit_flags:
            units_flagged[unit.unit_id] = unit_flags

    issues: List[ScienceIssue] = []

    for unit_id, seg_flags in units_flagged.items():
        # Trova il segmento rappresentativo più critico (metric più bassa)
        seg_flags.sort(key=lambda x: x[2])
        rep_seg_id, rep_text_raw, rep_metric, _ = seg_flags[0]
        has_floor_flag = any(is_fl for _, _, _, is_fl in seg_flags)
        severity = ScienceSeverity.HIGH if has_floor_flag else ScienceSeverity.MEDIUM

        count = len(seg_flags)
        if threshold_stat is not None:
            thresh_info = f"percentile-10 parole: {rep_metric:.2f}; soglia lezione: {threshold_stat:.2f}"
        else:
            thresh_info = f"percentile-10 parole: {rep_metric:.2f}; soglia sicurezza: {floor:.2f}"

        if count == 1:
            reason = (
                f"Confidenza ASR di questo tratto significativamente sotto la norma della lezione "
                f"({thresh_info}) — verifica che l'unità rispecchi fedelmente quanto detto nell'audio."
            )
        else:
            reason = (
                f"{count} segmenti in questa unità risultano degradati "
                f"(il più critico ha {thresh_info}) — verifica che l'unità rispecchi fedelmente quanto detto nell'audio."
            )

        iss = ScienceIssue(
            id=f"sci_st_{unit_id}",
            type=ScienceType.ERR_ASR_ST,
            severity=severity,
            unit_id=unit_id,
            segment_id=rep_seg_id,
            claim=rep_text_raw,
            reason=reason,
            suggested_fix=None,
            diplomatic_question=None,
            status="pending",
        )
        issues.append(iss)

    return issues
