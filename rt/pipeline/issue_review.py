"""
rt.pipeline.issue_review
Regole pure sulle issue scientifiche usate da tutte le interfacce di review (nessuna UI).
- App Textual e review da terminale: rt.tui.issue_review
- invio sequenziale via Telegram: rt.telegram.review_channel
- registrazione delle decisioni: rt.services.review_service
"""
from typing import Any, Optional, Tuple

from rt.core.models import ScienceIssue, ScienceType


def should_auto_accept_science(iss: ScienceIssue, auto_accept: Optional[str]) -> bool:
    """Valuta se auto-accettare una critica scientifica in base ai flag CLI."""
    if not auto_accept:
        return False
    mode = str(auto_accept).lower()
    if mode in ("all", "true"):
        return True
    return False


def _is_no_diff_issue_type(iss: ScienceIssue) -> bool:
    """Tipi di issue che non hanno un suggested_fix da mostrare come diff rosso/verde:
    vengono renderizzati con una descrizione piatta (stesso trattamento già riservato
    alle issue ASR)."""
    iss_type_str = iss.type.value if hasattr(iss.type, "value") else str(iss.type)
    return iss.type in (ScienceType.ERR_ASR_ST, ScienceType.ERR_REWRITE_DRIFT) or iss_type_str in ("ERR_ASR_LLM", "ERR_REWRITE_DRIFT")


def _build_diff_strings(sci_unit: Any, iss: ScienceIssue) -> Tuple[str, str]:
    from rt.core.encoding import fix_mojibake

    unit_text = fix_mojibake(sci_unit.content).strip() if (sci_unit and getattr(sci_unit, "content", None)) else ""
    claim_clean = fix_mojibake(iss.claim or "").strip()
    has_fix = bool(iss.suggested_fix and iss.suggested_fix.strip())
    fix_clean = fix_mojibake(iss.suggested_fix.strip()) if has_fix else ""

    if not unit_text:
        return (claim_clean, fix_clean if has_fix else claim_clean)

    if not has_fix:
        return (unit_text, unit_text)

    pos = unit_text.find(claim_clean) if claim_clean else -1
    if pos != -1:
        code_orig = unit_text
        code_mod = unit_text[:pos] + fix_clean + unit_text[pos + len(claim_clean):]
        return (code_orig, code_mod)
    else:
        # Fallback se non c'è match posizionale esatto
        code_orig = f"{unit_text}\n\n[Affermazione]: {claim_clean}"
        code_mod = f"{unit_text}\n\n[Correzione]: {fix_clean}"
        return (code_orig, code_mod)
