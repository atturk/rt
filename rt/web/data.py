"""Adattatori di lettura e presentazione per il prototipo Gradio."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
import io
import re
import subprocess
import wave
from typing import Optional

import numpy as np

from rt.core.audio_clip import resolve_audio_path
from rt.core.config import load_config
from rt.pipeline.issue_review import _prepare_issue_context
from rt.pipeline.issue_review import _is_no_diff_issue_type
from rt.pipeline.ledger import load_ledger, sanitize_suggested_fix
from rt.pipeline.review import load_science_issues
from rt.pipeline.rewrite import load_draft
from rt.tui.data import LessonSummary, badge_for_state, discover_lessons, load_markdown_preview


PHASE_LABELS = {
    "prepare": "Preparazione", "outline": "Scaletta", "rewrite": "Rielaborazione",
    "review": "Revisione", "build": "Documento",
}
PHASE_COLORS = {"valid": "done", "partial": "warn", "stale": "warn", "invalid": "bad", "missing": "todo"}


@dataclass
class IssueDetail:
    heading: str = "<div class='rt-empty'>Nessuna questione da visualizzare.</div>"
    claim: str = ""
    proposal: str = ""
    reason: str = ""
    source_quote: str = ""
    unit_text: str = ""
    diff: str = ""
    audio: object = None
    editor_initial: str = ""
    can_accept: bool = False
    can_reject: bool = False
    can_edit: bool = False
    can_undo: bool = False


def _word_diff(original: str, proposed: Optional[str]) -> str:
    if not proposed:
        return '<div class="rt-diff-empty">Nessuna sostituzione testuale automatica proposta.</div>'
    old = re.findall(r"\s+|\S+", original)
    new = re.findall(r"\s+|\S+", proposed)
    parts = []
    for tag, old_start, old_end, new_start, new_end in SequenceMatcher(None, old, new).get_opcodes():
        before = escape("".join(old[old_start:old_end]))
        after = escape("".join(new[new_start:new_end]))
        if tag == "equal":
            parts.append(before)
        else:
            if before:
                parts.append(f"<del>{before}</del>")
            if after:
                parts.append(f"<ins>{after}</ins>")
    return '<div class="rt-diff"><span class="rt-eyebrow">CONFRONTO DEL TESTO</span><p>' + "".join(parts) + "</p></div>"


def _unit_for_issue(lesson_dir: str, issue):
    try:
        draft = load_draft(lesson_dir)
    except (OSError, ValueError, KeyError):
        return None
    unit = next((unit for unit in draft.units if unit.unit_id == issue.unit_id), None)
    if unit is None and issue.segment_id:
        unit = next((unit for unit in draft.units if issue.segment_id in unit.source_segment_ids), None)
    return unit


def lessons_root() -> Optional[str]:
    return load_config().telegram.lessons_root


def list_lessons(root: str) -> list[LessonSummary]:
    return discover_lessons(root)


def picker_choices(lessons: list[LessonSummary], query: str = "") -> list[tuple[str, str]]:
    needle = query.strip().casefold()
    choices = []
    for lesson in lessons:
        if needle and needle not in f"{lesson.subject} {lesson.title} {lesson.recorded}".casefold():
            continue
        topic = lesson.title.split(" - ", 1)[-1] if " - " in lesson.title else lesson.title
        topic = topic[:54] + ("…" if len(topic) > 54 else "")
        count = f" · {lesson.pending_issues} da rivedere" if lesson.pending_issues else ""
        choices.append((f"{lesson.recorded or 'Senza data'} · {lesson.subject or 'Lezione'} · {topic}{count}",
                        lesson.dir_path))
    return choices


def lesson_stats(lessons: list[LessonSummary]) -> str:
    total = len(lessons)
    needs_review = sum(1 for lesson in lessons if lesson.pending_issues)
    complete = sum(1 for lesson in lessons if lesson.state and lesson.state.value == "completato")
    return (
        '<div class="rt-stats">'
        f'<div class="rt-stat"><strong>{total}</strong><span>Lezioni</span></div>'
        f'<div class="rt-stat"><strong>{needs_review}</strong><span>Da rivedere</span></div>'
        f'<div class="rt-stat"><strong>{complete}</strong><span>Completate</span></div>'
        '</div>'
    )


def lesson_card(lesson: Optional[LessonSummary]) -> str:
    if lesson is None:
        return '<div class="rt-empty">Seleziona una lezione per vedere il suo stato.</div>'
    badge, token = badge_for_state(lesson.state)
    phases = ''.join(
        f'<div class="rt-phase {PHASE_COLORS.get(status.value.lower(), "todo")}">'
        f'<span class="rt-phase-dot"></span>{escape(PHASE_LABELS.get(name, name))}</div>'
        for name, status in lesson.phase_status
    )
    warning = f'<p class="rt-error">{escape(lesson.error)}</p>' if lesson.error else ''
    meta = ' · '.join(x for x in (lesson.subject, lesson.recorded, f'aggiornata {lesson.when}') if x)
    return (
        '<div class="rt-lesson-card">'
        f'<div class="rt-card-head"><span class="rt-eyebrow">LEZIONE SELEZIONATA</span>'
        f'<span class="rt-badge {escape(token)}">{escape(badge)}</span></div>'
        f'<h2>{escape(lesson.title)}</h2><p class="rt-meta">{escape(meta)}</p>'
        f'<div class="rt-phase-row">{phases}</div>'
        f'<div class="rt-card-foot"><span>{lesson.pending_issues} questioni da valutare</span>'
        f'<span>Costo stimato ${lesson.cost_total or 0:.2f}</span></div>{warning}</div>'
    )


def lesson_preview(lesson: Optional[LessonSummary]) -> str:
    if lesson is None:
        return "Seleziona una lezione."
    text = load_markdown_preview(lesson.dir_path)
    return text[:18000] + ("\n\n… Anteprima limitata; apri il documento per il testo completo." if len(text) > 18000 else "")


def review_issues(lesson_dir: str):
    decisions = {decision.issue_id: decision for decision in load_ledger(lesson_dir).decisions}
    return load_science_issues(lesson_dir), decisions


def issue_choices(lesson: Optional[LessonSummary]) -> tuple[list[tuple[str, str]], Optional[str]]:
    if lesson is None:
        return [], None
    issues, decisions = review_issues(lesson.dir_path)
    choices = []
    for issue in issues:
        decision = decisions.get(issue.id)
        marker = {"accepted": "✓", "rejected": "×", "edited": "✎"}.get(decision.decision, "•") if decision else "○"
        short_claim = issue.claim.replace("\n", " ").strip()[:65]
        choices.append((f"{marker} {issue.unit_id or 'Unità'} · {short_claim}", issue.id))
    pending = next((issue.id for issue in issues if issue.id not in decisions), None)
    return choices, pending or (issues[0].id if issues else None)


def issue_detail(lesson: Optional[LessonSummary], issue_id: Optional[str]) -> IssueDetail:
    if lesson is None or not issue_id:
        return IssueDetail()
    issues, decisions = review_issues(lesson.dir_path)
    issue = next((item for item in issues if item.id == issue_id), None)
    if issue is None:
        return IssueDetail()
    try:
        context = _prepare_issue_context(lesson.dir_path, issue, "science")
    except (OSError, ValueError, KeyError):
        context = {}
    decision = decisions.get(issue.id)
    status = f"Decisione già registrata: {escape(decision.decision)}" if decision else "Decisione in attesa"
    heading = (
        '<div class="rt-issue-heading">'
        f'<span class="rt-eyebrow">{escape(issue.type.value)} · {escape(issue.severity.value.upper())}</span>'
        f'<h2>{escape(context.get("unit_info") or issue.unit_id or "Questione")}</h2>'
        f'<p class="rt-meta">{escape(issue.id)} · {escape(context.get("timecode") or "Audio disponibile sotto")}'
        f' · {status}</p></div>'
    )
    unit = _unit_for_issue(lesson.dir_path, issue)
    is_asr = _is_no_diff_issue_type(issue)
    source = issue.source_quote or context.get("sentence") or ""
    proposal = decision.resolved_text if decision and decision.resolved_text else (issue.suggested_fix or "Nessuna proposta automatica")
    reason = issue.reason or ""
    start_s, end_s = context.get("start_s"), context.get("end_s")
    if issue.segment_id:
        try:
            from rt.core.lesson_paths import lesson_path
            from rt.core.segments import load_segments_json

            segments = load_segments_json(lesson_path(lesson.dir_path, "segments.json"))
            segment = next((part for part in segments.segments if part.id == issue.segment_id), None)
            if segment:
                start_s = max(0.0, segment.start_seconds - 5.0)
                end_s = segment.end_seconds + 8.0
        except (OSError, ValueError, KeyError):
            pass
    audio = audio_excerpt(lesson.dir_path, start_s, end_s)
    return IssueDetail(
        heading=heading, claim=issue.claim, proposal=proposal, reason=reason,
        source_quote=source or "Nessuna citazione ASR disponibile.",
        unit_text=unit.content if unit else "Unità non disponibile.",
        diff=_word_diff(issue.claim, None if is_asr else sanitize_suggested_fix(issue.suggested_fix)),
        audio=audio,
        editor_initial=(unit.content if unit else issue.claim) if is_asr else issue.claim,
        can_accept=decision is None and (not is_asr or unit is not None),
        can_reject=decision is None and not is_asr,
        can_edit=decision is None,
        can_undo=decision is not None and decision.resolved_by == "web",
    )


def audio_excerpt(lesson_dir: str, start: Optional[float], end: Optional[float]):
    """Estratto PCM in memoria: nessuna copia permanente del file audio della lezione."""
    audio_path = resolve_audio_path(lesson_dir)
    if not audio_path or start is None:
        return None
    start = max(0.0, float(start))
    duration = min(max(float(end or start + 20) - start, 1.0), 35.0)
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(duration),
             "-i", audio_path, "-f", "wav", "-acodec", "pcm_s16le", "-ac", "1",
             "-ar", "22050", "pipe:1"],
            capture_output=True, check=True, timeout=25,
        )
        with wave.open(io.BytesIO(result.stdout)) as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).copy()
            return wav.getframerate(), samples
    except (OSError, subprocess.SubprocessError, EOFError, wave.Error, ValueError):
        return None


def configuration_summary(root: str) -> str:
    cfg = load_config()
    routes = []
    for job_name, job in cfg.llm.items():
        primary = job.primary
        provider = primary.provider or "Da configurare"
        model = primary.model or "—"
        routes.append(
            '<div class="rt-config-row">'
            f'<span>{escape(job_name)}</span><strong>{escape(provider)}</strong>'
            f'<span>{escape(model)}</span></div>'
        )
    return (
        '<div class="rt-config-card"><span class="rt-eyebrow">PERCORSI E PREFERENZE</span>'
        f'<div class="rt-config-row"><span>Cartella lezioni</span><strong>{escape(root)}</strong></div>'
        f'<div class="rt-config-row"><span>Canale predefinito</span><strong>{escape(cfg.telegram.default_channel)}</strong></div>'
        f'<div class="rt-config-row"><span>Tema terminale</span><strong>{escape(cfg.ui.theme)}</strong></div>'
        '</div><div class="rt-config-card"><span class="rt-eyebrow">MODELLI PER FASE</span>'
        + ''.join(routes) + '</div>'
    )
