"""Adattatori di sola lettura per il prototipo Gradio."""
from __future__ import annotations

from html import escape
import io
import os
import subprocess
import wave
from typing import Optional

import numpy as np

from rt.core.audio_clip import resolve_audio_path
from rt.core.config import load_config
from rt.pipeline.issue_review import _prepare_issue_context
from rt.pipeline.ledger import load_ledger
from rt.pipeline.review import load_science_issues
from rt.tui.data import PHASES, LessonSummary, badge_for_state, discover_lessons, load_markdown_preview


PHASE_LABELS = {
    "prepare": "Preparazione", "outline": "Scaletta", "rewrite": "Rielaborazione",
    "review": "Revisione", "build": "Documento",
}
PHASE_COLORS = {"valid": "done", "partial": "warn", "stale": "warn", "invalid": "bad", "missing": "todo"}


def lessons_root() -> Optional[str]:
    return load_config().telegram.lessons_root


def list_lessons(root: str) -> list[LessonSummary]:
    return discover_lessons(root)


def picker_choices(lessons: list[LessonSummary], query: str = "") -> list[tuple[str, str]]:
    needle = query.strip().casefold()
    return [
        (f"{lesson.subject or 'Lezione'}  ·  {lesson.title}", lesson.dir_path)
        for lesson in lessons
        if not needle or needle in f"{lesson.subject} {lesson.title}".casefold()
    ]


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
        marker = "✓" if issue.id in decisions else "○"
        short_claim = issue.claim.replace("\n", " ").strip()[:65]
        choices.append((f"{marker} {issue.unit_id or 'Unità'} · {short_claim}", issue.id))
    pending = next((issue.id for issue in issues if issue.id not in decisions), None)
    return choices, pending or (issues[0].id if issues else None)


def issue_detail(lesson: Optional[LessonSummary], issue_id: Optional[str]):
    empty = ("<div class='rt-empty'>Nessuna questione da visualizzare.</div>", "", "", "", None)
    if lesson is None or not issue_id:
        return empty
    issues, decisions = review_issues(lesson.dir_path)
    issue = next((item for item in issues if item.id == issue_id), None)
    if issue is None:
        return empty
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
    source = issue.source_quote or context.get("sentence") or issue.claim
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
    return heading, source, proposal, reason, audio


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
