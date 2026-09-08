"""
rt.telegram.formatting
Rendering testuale dell'outline per la conferma (Telegram HTML e terminale
condividono la stessa funzione di rendering in testo semplice).
"""
import html
from rt.core.models import Outline

MAX_MESSAGE_CHARS = 3800  # margine di sicurezza sotto il limite di 4096 di Telegram


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def render_outline_summary_text(outline: Outline) -> str:
    lines = [f"📋 <b>{escape_html(outline.lesson_title)}</b>", ""]
    for macro in outline.macro_sections:
        lines.append(f"<b>{escape_html(macro.id)}. {escape_html(macro.title)}</b>")
        for unit in macro.units:
            concepts = ", ".join(unit.key_concepts[:4])
            suffix = f" — {escape_html(concepts)}" if concepts else ""
            lines.append(f"  {escape_html(unit.id)} {escape_html(unit.title)}{suffix}")
        lines.append("")
    text = "\n".join(lines).strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS] + "\n\n… (troncato, elenco completo in outline.json)"
    return text


def build_outline_decision_keyboard(short_id: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approva", "callback_data": f"rtappr:{short_id}"},
            {"text": "✏️ Richiedi modifiche", "callback_data": f"rtedit:{short_id}"},
        ]]
    }
