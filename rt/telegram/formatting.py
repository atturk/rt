"""
rt.telegram.formatting
Rendering testuale dell'outline per la conferma (Telegram HTML e terminale
condividono la stessa funzione di rendering in testo semplice).
"""
import html
from typing import Optional
from rt.core.models import Outline

MAX_MESSAGE_CHARS = 3800  # margine di sicurezza sotto il limite di 4096 di Telegram


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def render_outline_summary_text(outline: Outline, for_telegram: bool = True) -> str:
    if for_telegram:
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
    else:
        lines = [f"📋 {outline.lesson_title}", ""]
        for macro in outline.macro_sections:
            lines.append(f"{macro.id}. {macro.title}")
            for unit in macro.units:
                concepts = ", ".join(unit.key_concepts[:4])
                suffix = f" — {concepts}" if concepts else ""
                lines.append(f"  {unit.id} {unit.title}{suffix}")
            lines.append("")
        return "\n".join(lines).strip()


def render_lesson_list_text(entries, show_materia: bool) -> str:
    lines = []
    for i, e in enumerate(entries, start=1):
        label = e.titolo or e.argomenti or e.folder_name
        suffix = f" ({e.materia})" if show_materia and e.materia else ""
        lines.append(f"{i}. [{e.data}] {escape_html(label)}{suffix}")
    return "\n".join(lines)


def render_asr_issue_text(issue, unit_info: Optional[str], timecode: str, listen_range: str, sentence: str) -> str:
    lines = [f"🎙 <b>Ambiguità ASR ({escape_html(issue.level.value)})</b>"]
    if unit_info:
        lines.append(f"📚 Unità: {escape_html(unit_info)}")
    lines.append(f"⏱ Timecode: {escape_html(timecode)} (ascolto: {escape_html(listen_range)})")
    lines.append(f"🎙 ASR originale: <i>{escape_html(issue.source_text)}</i>")
    lines.append(f"💡 Proposta AI: <i>{escape_html(issue.candidate)}</i> (confidenza {issue.confidence:.2f})")
    lines.append(f"📝 Motivazione: {escape_html(issue.reason)}")
    if sentence:
        lines.append(f"📖 Contesto: <i>{escape_html(sentence)}</i>")
    return "\n".join(lines)


def render_science_issue_text(issue, unit_info: Optional[str], timecode: str) -> str:
    lines = [f"🔬 <b>Science Critic ({escape_html(issue.type.value)})</b>"]
    if unit_info:
        lines.append(f"📚 Unità: {escape_html(unit_info)}")
    lines.append(f"⏱ Timecode: {escape_html(timecode)}")
    lines.append(f"⚠️ Affermazione: <i>{escape_html(issue.claim)}</i>")
    lines.append(f"🔬 Critica: {escape_html(issue.reason)}")
    if issue.suggested_fix:
        lines.append(f"💡 Correzione: <i>{escape_html(issue.suggested_fix)}</i>")
    if issue.diplomatic_question:
        lines.append(f"🤝 Domanda docente: <i>{escape_html(issue.diplomatic_question)}</i>")
    return "\n".join(lines)


def build_issue_keyboard(short_id: str, issue_type: str) -> dict:
    if issue_type == "asr":
        row1 = [{"text": "✅ Accetta", "callback_data": f"ia:{short_id}"}, {"text": "❌ Rifiuta", "callback_data": f"ir:{short_id}"}]
    else:
        row1 = [{"text": "✅ Applica", "callback_data": f"ia:{short_id}"}, {"text": "🚫 Mantieni", "callback_data": f"ir:{short_id}"}]
    row2 = [{"text": "✏️ Modifica", "callback_data": f"ie:{short_id}"}, {"text": "⏭️ Salta", "callback_data": f"is:{short_id}"}]
    row3 = [{"text": "◀️ Indietro", "callback_data": f"ib:{short_id}"}, {"text": "🛑 Esci", "callback_data": f"iq:{short_id}"}]
    return {"inline_keyboard": [row1, row2, row3]}


def build_start_review_keyboard(short_id: str) -> dict:
    return {"inline_keyboard": [[{"text": "▶️ Inizia review", "callback_data": f"ivr:{short_id}"}]]}



def render_recall_question_text(question) -> str:
    """Rende il testo di una RecallQuestion mirata/vasta per l'invio Telegram.
    I quiz non passano di qui: sono inviati come poll nativo (vedi rt.telegram.client.send_poll),
    che mostra già domanda e opzioni nella propria UI."""
    label = {"mirata": "🔎 Domanda mirata", "vasta": "📚 Domanda vasta"}.get(question.type.value, "Domanda")
    lines = [f"<b>{escape_html(label)}</b>", f"📌 Unità: {escape_html(', '.join(question.unit_ids))}", ""]
    lines.append(escape_html(question.question_text))
    return "\n".join(lines)


def build_recall_action_keyboard(short_id: str) -> dict:
    """Tastiera con le uniche due azioni rapide sulla domanda di recall: 'Non lo so' (rivela
    subito la risposta/spiegazione) e 'Skip' (passa oltre senza registrare nulla). Il voto sulla
    qualità della domanda (👍👎⚡) non passa più da un bottone: si vota reagendo al messaggio
    della domanda con l'emoji corrispondente (vedi rt.telegram.daemon.handle_message_reaction)."""
    return {"inline_keyboard": [[
        {"text": "🤷 Non lo so", "callback_data": f"rns:{short_id}"},
        {"text": "⏭ Skip", "callback_data": f"rsk:{short_id}"},
    ]]}


def build_stile_keyboard(current_style: str) -> dict:
    labels = {"quiz": "Quiz", "mirata": "Mirata", "vasta": "Vasta"}
    row = []
    for style, label in labels.items():
        prefix = "✅ " if style == current_style else ""
        row.append({"text": f"{prefix}{label}", "callback_data": f"stile:{style}"})
    return {"inline_keyboard": [row]}


def build_post_answer_keyboard(short_id: str) -> dict:
    """Tastiera post-risposta con 3 bottoni in riga unica:
    ⏭️ avanza alla domanda successiva (rimuove tastiera, chiama send_current_recall_question),
    📖 mostra il testo completo dell'unità didattica (non rimuove tastiera),
    🔊 manda l'audio dell'unità come file musicale (non rimuove tastiera).
    Appare SOLO dopo un esito (risposta, non-lo-so, quiz), non prima della risposta."""
    return {"inline_keyboard": [[
        {"text": "⏭️", "callback_data": f"rnx:{short_id}"},
        {"text": "📖", "callback_data": f"rut:{short_id}"},
        {"text": "🔊", "callback_data": f"rua:{short_id}"},
    ]]}
