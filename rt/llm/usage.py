"""Conteggi del prompt comuni alle risposte complete e ai chunk dei provider."""
from typing import Optional


def cached_prompt_tokens(usage) -> Optional[int]:
    if not isinstance(usage, dict):
        return None
    value = usage.get("prompt_cache_hit_tokens")
    if value is None:
        details = usage.get("prompt_tokens_details")
        value = details.get("cached_tokens") if isinstance(details, dict) else None
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else None
