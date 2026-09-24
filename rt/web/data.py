"""Adattatori di lettura e presentazione per il prototipo Gradio."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
from hashlib import sha256
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import wave
from typing import Optional

import numpy as np
from markdown_it import MarkdownIt

from rt.core.audio_clip import resolve_audio_path
from rt.core.config import load_config
from rt.pipeline.issue_review import _prepare_issue_context
from rt.pipeline.issue_review import _is_no_diff_issue_type
from rt.pipeline.ledger import load_ledger, sanitize_suggested_fix
from rt.pipeline.review import load_science_issues
from rt.pipeline.rewrite import load_draft
from rt.tui.data import LessonSummary, discover_lessons, load_markdown_preview


PHASE_LABELS = {
    "prepare": "Preparazione", "outline": "Scaletta", "rewrite": "Rielaborazione",
    "review": "Revisione", "build": "Documento",
}
PHASE_COLORS = {"valid": "done", "partial": "warn", "stale": "warn", "invalid": "bad", "missing": "todo"}
MARKDOWN = MarkdownIt("commonmark", {"html": False})
_WEB_AUDIO_DIR: Optional[tempfile.TemporaryDirectory] = None


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


def lesson_title(lesson: LessonSummary) -> str:
    """Rimuove data e materia usate come prefisso nel nome della cartella."""
    title = re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\s*", "", lesson.title)
    prefix = f"{lesson.subject} - " if lesson.subject else ""
    return title[len(prefix):] if prefix and title.casefold().startswith(prefix.casefold()) else title


def sidebar_lessons(lessons: list[LessonSummary], selected: Optional[str]) -> str:
    """Elenco per materia, con una selezione diretta della lezione."""
    grouped: dict[str, list[LessonSummary]] = {}
    for lesson in lessons:
        grouped.setdefault(lesson.subject or "Altre lezioni", []).append(lesson)
    sections = []
    for subject in sorted(grouped, key=str.casefold):
        items = []
        for lesson in sorted(grouped[subject], key=lambda item: (item.recorded, item.title), reverse=True):
            count = f'<span class="rt-sidebar-count">{lesson.pending_issues} da rivedere</span>' if lesson.pending_issues else ''
            active = ' active' if lesson.dir_path == selected else ''
            items.append(
                f'<button type="button" class="rt-sidebar-lesson{active}" '
                f'data-lesson-path="{escape(lesson.dir_path, quote=True)}" '
                f'aria-current="{"page" if active else "false"}">'
                f'<span class="rt-sidebar-date">{escape(lesson.recorded or "Senza data")}</span>'
                f'<span class="rt-sidebar-title">{escape(lesson_title(lesson))}</span>{count}</button>'
            )
        sections.append(f'<section class="rt-sidebar-group"><h3>{escape(subject)}</h3>{"".join(items)}</section>')
    return '<nav class="rt-sidebar-lessons" aria-label="Lezioni per materia">' + (
        ''.join(sections) if sections else '<p class="rt-sidebar-empty">Nessuna lezione.</p>'
    ) + '</nav>'


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
    phases = ''.join(
        f'<div class="rt-phase {PHASE_COLORS.get(status.value.lower(), "todo")}">'
        f'<span class="rt-phase-dot"></span>{escape(PHASE_LABELS.get(name, name))}</div>'
        for name, status in lesson.phase_status
    )
    warning = f'<p class="rt-error">{escape(lesson.error)}</p>' if lesson.error else ''
    title = lesson_title(lesson)
    meta = ' · '.join(x for x in (lesson.subject, lesson.recorded) if x)
    review_link = (
        f'<button class="rt-review-link" type="button" data-open-review="1">'
        f'{lesson.pending_issues} questioni da valutare →</button>'
        if lesson.pending_issues else '<span class="rt-complete-label">Nessuna questione in attesa</span>'
    )
    return (
        '<div class="rt-lesson-card">'
        f'<h2>{escape(title)}</h2><p class="rt-meta">{escape(meta)}</p>'
        f'<div class="rt-phase-row">{phases}</div>'
        f'<div class="rt-card-foot">{review_link}</div>{warning}</div>'
    )


def lesson_preview(lesson: Optional[LessonSummary]) -> str:
    if lesson is None:
        return "Seleziona una lezione."
    text = load_markdown_preview(lesson.dir_path)
    text = re.sub(r"\A#\s+[^\n]+\n+", "", text, count=1)
    return text


def lesson_preview_html(lesson: Optional[LessonSummary]) -> str:
    """Renderizza Markdown senza HTML grezzo; i timecode diventano controlli del player."""
    return '<div class="rt-document">' + MARKDOWN.render(lesson_preview(lesson)) + '</div>'


def lesson_audio_path(lesson: Optional[LessonSummary]) -> Optional[str]:
    if lesson is None:
        return None
    audio = resolve_audio_path(lesson.dir_path)
    if audio:
        return _web_audio_path(lesson, audio)
    # Le lezioni appena importate hanno info.yaml, ma il manifest arriva con prepare.
    from rt.core.lesson_paths import lesson_path
    from rt.core.state import read_info_yaml

    try:
        raw_name = read_info_yaml(lesson_path(lesson.dir_path, "info.yaml")).get("file_audio")
        candidate = Path(lesson.dir_path) / Path(str(raw_name or "")).name
        return _web_audio_path(lesson, str(candidate)) if raw_name and candidate.is_file() else None
    except (OSError, ValueError):
        return None


def _web_audio_path(lesson: LessonSummary, original: str) -> Optional[str]:
    """Espone a Gradio solo l'audio scelto, lasciando bloccata la cartella lezioni."""
    source = Path(original).resolve()
    if not source.is_file() or not source.is_relative_to(Path(lesson.dir_path).resolve()):
        return None
    global _WEB_AUDIO_DIR
    if _WEB_AUDIO_DIR is None:
        _WEB_AUDIO_DIR = tempfile.TemporaryDirectory(prefix="rt-web-audio-")
    stat = source.stat()
    name = sha256(f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:20]
    target = Path(_WEB_AUDIO_DIR.name) / f"{name}{source.suffix.lower()}"
    if not target.exists():
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)
    return str(target)


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
