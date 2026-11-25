"""Conteggi del prompt comuni alle risposte complete e ai chunk dei provider."""
from typing import Any, Dict, Optional, Tuple


def cached_prompt_tokens(usage) -> Optional[int]:
    if not isinstance(usage, dict):
        return None
    value = usage.get("prompt_cache_hit_tokens")
    if value is None:
        details = usage.get("prompt_tokens_details")
        value = details.get("cached_tokens") if isinstance(details, dict) else None
    if value is None:
        value = usage.get("cache_read_input_tokens")
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else None


def extract_usage_tokens(usage: Optional[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[bool]]:
    """Estrae (input_tokens, output_tokens, reasoning_tokens, total_tokens, reasoning_included).

    reasoning_included è True/False quando total_tokens permette di verificarlo dai numeri
    (es. total == in + out vs total == in + out + reasoning), altrimenti None (usa il default
    del provider in calculate_cost).
    """
    if not isinstance(usage, dict):
        return None, None, None, None, None

    in_t = usage.get("prompt_tokens")
    if in_t is None:
        in_t = usage.get("input_tokens")
    if in_t is None:
        in_t = usage.get("promptTokenCount")

    out_t = usage.get("completion_tokens")
    if out_t is None:
        out_t = usage.get("output_tokens")
    if out_t is None:
        out_t = usage.get("candidatesTokenCount")

    det = usage.get("completion_tokens_details") or usage.get("output_tokens_details")
    reas_t = det.get("reasoning_tokens") if isinstance(det, dict) else None
    if reas_t is None:
        reas_t = usage.get("thoughtsTokenCount")

    tot_t = usage.get("total_tokens")
    if tot_t is None:
        tot_t = usage.get("totalTokenCount")

    reasoning_included: Optional[bool] = None
    if isinstance(in_t, int) and isinstance(out_t, int) and isinstance(reas_t, int) and reas_t > 0 and isinstance(tot_t, int):
        if tot_t == in_t + out_t:
            reasoning_included = True
        elif tot_t == in_t + out_t + reas_t:
            reasoning_included = False

    if tot_t is None and (in_t is not None or out_t is not None):
        tot_t = (in_t or 0) + (out_t or 0)

    return in_t, out_t, reas_t, tot_t, reasoning_included
