"""Adattatori di lettura e presentazione per il prototipo Gradio."""
from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import Future, ThreadPoolExecutor
from html import escape
from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Optional
from urllib.parse import quote

import numpy as np
from markdown_it import MarkdownIt

from rt.core.audio_clip import resolve_audio_path
from rt.core.models import ScienceType
from rt.core.config import load_config
from rt.pipeline.ledger import load_ledger
from rt.pipeline.review import load_science_issues
from rt.pipeline.rewrite import load_draft
from rt.tui.data import LessonSummary, discover_lessons, load_markdown_preview
from rt.storage import fs


PHASE_LABELS = {
    "prepare": "Preparazione", "outline": "Scaletta", "rewrite": "Rielaborazione",
    "review": "Revisione", "build": "Documento",
}
PHASE_COLORS = {"valid": "done", "partial": "warn", "stale": "warn", "invalid": "bad", "missing": "todo"}
MARKDOWN = MarkdownIt("commonmark", {"html": False})
_WEB_AUDIO_DIR: Optional[tempfile.TemporaryDirectory] = None
_WAVE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rt-waveform")
_WAVE_JOBS: dict[str, Future[list[int]]] = {}


def web_audio_directory() -> str:
    global _WEB_AUDIO_DIR
    if _WEB_AUDIO_DIR is None:
        _WEB_AUDIO_DIR = tempfile.TemporaryDirectory(prefix="rt-web-audio-")
    return _WEB_AUDIO_DIR.name


@dataclass
class IssueActionState:
    editor_initial: str = ""
    can_accept: bool = False
    can_reject: bool = False
    can_undo: bool = False


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
        sections.append(
            f'<details class="rt-sidebar-group" open><summary>'
            f'<span>{escape(subject)}</span><span class="rt-sidebar-chevron" aria-hidden="true"></span>'
            f'</summary>{"".join(items)}</details>'
        )
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
    cost = f'<span class="rt-cost" title="Costo stimato">${lesson.cost_total or 0:.2f}</span>'
    review_link = (
        f'<button class="rt-review-link" type="button" data-open-review="1">'
        f'{lesson.pending_issues} issue da valutare →</button>'
        if lesson.pending_issues else '<span class="rt-complete-label">Nessuna issue da valutare</span>'
    )
    return (
        '<div class="rt-lesson-card">'
        f'<h2>{escape(title)}</h2><p class="rt-meta">{escape(meta)}</p>'
        f'<div class="rt-phase-row">{phases}</div>'
        f'<div class="rt-card-foot">{cost}{review_link}</div>{warning}</div>'
    )


def lesson_preview(lesson: Optional[LessonSummary]) -> str:
    if lesson is None:
        return "Seleziona una lezione."
    text = load_markdown_preview(lesson.dir_path)
    text = re.sub(r"\A#\s+[^\n]+\n+", "", text, count=1)
    return text


def lesson_preview_html(lesson: Optional[LessonSummary], issue_id: Optional[str] = None) -> str:
    """Documento con un commento contestuale ancorato al claim o all'unità."""
    rendered = MARKDOWN.render(lesson_preview(lesson))
    if lesson and issue_id:
        issues, decisions = review_issues(lesson.dir_path)
        issue = next((item for item in issues if item.id == issue_id), None)
        if issue:
            warning = issue.type in WARNING_LABELS
            claim = escape(issue.claim, quote=False)
            anchor = '<mark class="rt-claim-highlight" id="rt-issue-anchor">'
            anchored = False
            if not warning and claim and claim in rendered:
                rendered = rendered.replace(claim, anchor + claim + '</mark>', 1)
                anchored = True
            if not anchored and issue.unit_id:
                heading = re.search(
                    rf'<h[23][^>]*>[^<]*\b{re.escape(issue.unit_id)}\b[^<]*</h[23]>', rendered
                )
                if heading:
                    rendered = (rendered[:heading.start()] + '<span id="rt-issue-anchor" '
                                'class="rt-unit-anchor" title="Segnalazione per questa unità">⚠</span>'
                                + rendered[heading.start():])
                    anchored = True
            if not anchored:
                rendered = '<span id="rt-issue-anchor"></span>' + rendered

            decision = decisions.get(issue.id)
            label = WARNING_LABELS[issue.type][0] if warning else 'Errore concettuale'
            note = WARNING_LABELS[issue.type][1] if warning else ''
            proposal = (issue.suggested_fix or '').strip()
            if warning:
                unit = _unit_for_issue(lesson.dir_path, issue)
                proposal = unit.content if unit else ''
            parts = [
                '<aside class="rt-inline-comment" aria-label="Commento sulla issue">',
                '<div class="rt-comment-head">',
                f'<span class="rt-eyebrow">{escape(label)} · Unità {escape(issue.unit_id or "?")}</span>',
                '<button type="button" class="rt-comment-close" data-comment-close="1" '
                'aria-label="Chiudi commento">×</button></div>',
            ]
            if note:
                parts.append(f'<p>{escape(note)}</p>')
            if issue.claim and not warning:
                parts.append(f'<p class="rt-comment-claim">{escape(issue.claim)}</p>')
            if issue.reason:
                parts.append(f'<p><strong>Motivo</strong><br>{escape(issue.reason)}</p>')
            if issue.diplomatic_question:
                parts.append(f'<p><strong>Domanda al docente</strong><br>{escape(issue.diplomatic_question)}</p>')
            if decision:
                parts.append(f'<p class="rt-comment-decided">Decisione: {escape(decision.decision)}</p>')
                if decision.resolved_by == 'web':
                    parts.append('<button type="button" data-review-action="undo">Riapri decisione</button>')
            else:
                parts.append('<label for="rt-comment-edit">' +
                             ('Testo dell’unità' if warning else 'Correzione proposta') + '</label>')
                parts.append(f'<textarea id="rt-comment-edit" rows="5">{escape(proposal)}</textarea>')
                parts.append('<div class="rt-comment-actions">'
                             '<button type="button" data-review-action="accept">' +
                             ('Conferma unità' if warning else 'Accetta') + '</button>')
                if not warning:
                    parts.append('<button type="button" data-review-action="reject">Mantieni originale</button>')
                parts.append('</div>')
            parts.append('</aside>')
            marker = '<span id="rt-issue-anchor"'
            # Inserisce il commento dopo il paragrafo/heading che contiene l'ancora.
            if '<mark class="rt-claim-highlight" id="rt-issue-anchor">' in rendered:
                end = rendered.index('</mark>') + len('</mark>')
                paragraph_end = rendered.find('</p>', end)
                if paragraph_end >= 0:
                    end = paragraph_end + len('</p>')
            else:
                end = rendered.index('</span>', rendered.index(marker)) + len('</span>')
                heading_end = re.search(r'</h[23]>', rendered[end:])
                if heading_end:
                    end += heading_end.end()
            rendered = rendered[:end] + ''.join(parts) + rendered[end:]
    return '<div class="rt-document">' + rendered + '</div>'


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


def lesson_audio_html(lesson: Optional[LessonSummary]) -> str:
    """Lettore della lezione con waveform calcolata in background."""
    path = lesson_audio_path(lesson)
    if not path:
        return '<div class="rt-audio-empty">Nessun audio disponibile per questa lezione.</div>'
    # Percorso opaco: il middleware espone solo copie/link selezionati nella
    # directory temporanea, con FileResponse e supporto Range nativo.
    url = '/rt-audio/' + quote(Path(path).name)
    request_waveform(path)
    return (
        '<section class="rt-audio-player" aria-label="Audio della lezione">'
        '<div class="rt-audio-header"><span>♫</span><strong>Audio della lezione</strong></div>'
        f'<canvas class="rt-waveform" data-peaks-url="{escape(url + ".peaks", quote=True)}" '
        'height="76" aria-label="Forma d’onda: clicca per cercare un punto"></canvas>'
        '<div class="rt-audio-times"><span data-audio-current>0:00</span><span data-audio-duration>0:00</span></div>'
        '<div class="rt-audio-controls">'
        '<button type="button" class="rt-audio-small" data-audio-action="mute" aria-label="Attiva o disattiva audio">◖))</button>'
        '<button type="button" class="rt-audio-small" data-audio-action="speed" aria-label="Velocità di riproduzione">1×</button>'
        '<div class="rt-audio-transport">'
        '<button type="button" class="rt-audio-chapter" data-chapter="previous" '
        'aria-label="Unità precedente" title="Unità precedente">◀◀</button>'
        '<button type="button" class="rt-audio-play" data-audio-action="play" aria-label="Riproduci">▶</button>'
        '<button type="button" class="rt-audio-chapter" data-chapter="next" '
        'aria-label="Unità successiva" title="Unità successiva">▶▶</button>'
        '</div><span class="rt-audio-spacer"></span></div>'
        f'<audio preload="metadata" src="{escape(url, quote=True)}"></audio>'
        '</section>'
    )


def _compute_waveform(path: str) -> list[int]:
    """Campiona l'ampiezza reale senza creare un file audio duplicato o bloccare la UI."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", "200",
             "-f", "s16le", "pipe:1"], capture_output=True, check=True, timeout=120,
        )
        samples = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32)
        if samples.size == 0:
            return []
        chunks = np.array_split(np.abs(samples), min(300, samples.size))
        levels = np.asarray([float(np.sqrt(np.mean(chunk * chunk))) for chunk in chunks])
        quiet = float(np.percentile(levels, 10))
        loud = max(float(np.percentile(levels, 90)), quiet + 1.0)
        return [int(3 + 69 * np.clip((level - quiet) / (loud - quiet), 0, 1))
                for level in levels]
    except (OSError, subprocess.SubprocessError):
        return []


def request_waveform(path: str) -> None:
    resolved = str(Path(path).resolve())
    if resolved not in _WAVE_JOBS:
        _WAVE_JOBS[resolved] = _WAVE_EXECUTOR.submit(_compute_waveform, resolved)


def waveform_result(path: str) -> list[int] | None:
    job = _WAVE_JOBS.get(str(Path(path).resolve()))
    return job.result() if job and job.done() else None


def _web_audio_path(lesson: LessonSummary, original: str) -> Optional[str]:
    """Espone a Gradio solo l'audio scelto, lasciando bloccata la cartella lezioni."""
    source = Path(original).resolve()
    if not source.is_file() or not source.is_relative_to(Path(lesson.dir_path).resolve()):
        return None
    stat = source.stat()
    name = sha256(f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:20]
    suffix = source.suffix.lower()
    target = Path(web_audio_directory()) / f"{name}{suffix}"
    if not target.exists():
        with source.open('rb') as handle:
            is_mp4 = handle.read(8)[4:8] == b'ftyp'
        if suffix == '.m4a' and not is_mp4:
            # Alcune registrazioni AAC ADTS hanno un nome .m4a: il browser le rifiuta.
            temporary = target.with_suffix('.tmp.m4a')
            try:
                subprocess.run(
                    ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source),
                     '-c:a', 'copy', '-movflags', '+faststart', str(temporary)],
                    check=True, capture_output=True, timeout=90,
                )
                fs.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            try:
                os.link(source, target)
            except OSError:
                fs.copyfile(source, target)
    return str(target)


def review_issues(lesson_dir: str):
    decisions = {decision.issue_id: decision for decision in load_ledger(lesson_dir).decisions}
    return load_science_issues(lesson_dir), decisions


WARNING_LABELS = {
    ScienceType.ERR_ASR_ST: (
        "Qualità ASR · statistica",
        "Un segmento audio dell'unità ha una confidenza ASR insolitamente bassa. Controlla l'unità ascoltando l'audio: non è un errore confermato.",
    ),
    ScienceType.ERR_ASR_LLM: (
        "Qualità ASR · modello",
        "Un modello ha trovato sospetto un segmento ASR già segnalato dalla statistica. Confronta unità e audio: non è un errore confermato.",
    ),
    ScienceType.ERR_REWRITE_DRIFT: (
        "Fedeltà al parlato",
        "Il pre-filtro Jev segnala che l'unità potrebbe discostarsi dal trascritto grezzo. Confronta unità e audio: non è un errore confermato.",
    ),
}


def _issue_anchor_available(issue, units: dict, segments: set[str]) -> bool:
    unit = units.get(issue.unit_id)
    if unit is None:
        return False
    if issue.segment_id and issue.segment_id not in segments:
        return False
    if issue.type == ScienceType.ERR_CONCETTUALE:
        return bool(issue.claim.strip() and issue.claim.strip() in unit.content)
    return True


def issue_sidebar(lesson: Optional[LessonSummary], selected_issue: Optional[str],
                  group_by: str = "unit") -> str:
    """Elenco compatto: errori concettuali e segnalazioni di qualità restano distinti."""
    if lesson is None:
        return '<div class="rt-issue-sidebar"><p>Nessuna lezione selezionata.</p></div>'
    issues, decisions = review_issues(lesson.dir_path)
    try:
        draft = load_draft(lesson.dir_path)
        units = {unit.unit_id: unit for unit in draft.units}
    except (OSError, ValueError, KeyError):
        units = {}
    try:
        from rt.core.lesson_paths import lesson_path
        from rt.core.segments import load_segments_json
        segments = {s.id for s in load_segments_json(lesson_path(lesson.dir_path, "segments.json")).segments}
    except (OSError, ValueError, KeyError):
        segments = set()
    grouped: dict[str, list[str]] = {}
    orphan_count = 0
    for issue in issues:
        if not _issue_anchor_available(issue, units, segments):
            orphan_count += 1
            continue
        warning = WARNING_LABELS.get(issue.type)
        label = warning[0] if warning else "Errore concettuale"
        title = warning[1] if warning else "Correzione concettuale proposta per un passaggio del testo."
        marker = "⚠" if warning else "●"
        decided = " · valutata" if issue.id in decisions else ""
        active = " active" if issue.id == selected_issue else ""
        group = (f"Unità {issue.unit_id or '?'}" if group_by == "unit"
                 else "Errori concettuali" if not warning
                 else "Fedeltà al parlato" if issue.type == ScienceType.ERR_REWRITE_DRIFT
                 else "Qualità ASR")
        grouped.setdefault(group, []).append(
            f'<button type="button" class="rt-issue-item{active}" data-issue-id="{escape(issue.id, quote=True)}" '
            f'title="{escape(title, quote=True)}">'
            f'<span class="rt-issue-marker" aria-hidden="true">{marker}</span>'
            f'<span><strong>{escape(label)}</strong><small>Unità {escape(issue.unit_id or "?")}{decided}</small></span>'
            '</button>'
        )
    orphan_note = (
        '<div class="rt-orphan-note"><p>'
        f'{orphan_count} issue senza unità, segmento o claim corrispondente. '
        'Controlla il file JSON delle issue.</p>'
        '<button type="button" data-open-issues-file="1">Apri file JSON</button></div>'
        if orphan_count else ''
    )
    rows = ''.join(
        f'<section class="rt-issue-group"><h3>{escape(group)}</h3>{"".join(items)}</section>'
        for group, items in grouped.items()
    )
    return ('<aside class="rt-issue-sidebar" aria-label="Issue della lezione">'
            + (rows or '<p class="rt-sidebar-empty">Nessuna issue ancorata.</p>')
            + orphan_note + '</aside>')


def issue_choices(lesson: Optional[LessonSummary]) -> tuple[list[tuple[str, str]], Optional[str]]:
    if lesson is None:
        return [], None
    issues, decisions = review_issues(lesson.dir_path)
    try:
        units = {unit.unit_id: unit for unit in load_draft(lesson.dir_path).units}
    except (OSError, ValueError, KeyError):
        units = {}
    try:
        from rt.core.lesson_paths import lesson_path
        from rt.core.segments import load_segments_json
        segments = {s.id for s in load_segments_json(lesson_path(lesson.dir_path, "segments.json")).segments}
    except (OSError, ValueError, KeyError):
        segments = set()
    choices = []
    for issue in issues:
        if not _issue_anchor_available(issue, units, segments):
            continue
        decision = decisions.get(issue.id)
        marker = {"accepted": "✓", "rejected": "×", "edited": "✎"}.get(decision.decision, "•") if decision else "○"
        short_claim = issue.claim.replace("\n", " ").strip()[:65]
        choices.append((f"{marker} {issue.unit_id or 'Unità'} · {short_claim}", issue.id))
    visible_ids = {value for _, value in choices}
    pending = next((issue.id for issue in issues if issue.id in visible_ids and issue.id not in decisions), None)
    return choices, pending or (choices[0][1] if choices else None)


def issue_action_state(lesson: Optional[LessonSummary], issue_id: Optional[str]) -> IssueActionState:
    if lesson is None or not issue_id:
        return IssueActionState()
    issues, decisions = review_issues(lesson.dir_path)
    issue = next((item for item in issues if item.id == issue_id), None)
    if issue is None:
        return IssueActionState()
    decision = decisions.get(issue.id)
    unit = _unit_for_issue(lesson.dir_path, issue)
    warning = issue.type in WARNING_LABELS
    anchored = bool(unit and (warning or issue.claim.strip() in unit.content))
    return IssueActionState(
        editor_initial=unit.content if warning and unit else (issue.suggested_fix or ""),
        can_accept=decision is None and anchored,
        can_reject=decision is None and anchored and not warning,
        can_undo=decision is not None and decision.resolved_by == "web",
    )


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
        '<div class="rt-config-card"><span class="rt-eyebrow">LEZIONI</span>'
        f'<div class="rt-config-row"><span>Cartella lezioni</span><strong>{escape(root or "Da configurare")}</strong></div>'
        '</div><div class="rt-config-card"><span class="rt-eyebrow">MODELLI PER FASE</span>'
        + ''.join(routes) + '</div>'
    )
