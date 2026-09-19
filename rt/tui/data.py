"""
rt.tui.data
Scansione della cartella lezioni (telegram.lessons_root) e calcolo dello stato di
ciascuna lezione per la dashboard principale. Riusa la stessa logica già impiegata
da 'rt status'/'rt cost', nessuna duplicazione di regole di stato.
"""
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rt.core.idempotency import PhaseStatus, check_phase_status
from rt.core.lesson_paths import lesson_path
from rt.core.state import WorkflowState, compute_effective_workflow_state, read_info_yaml
from rt.pipeline.cost import compute_lesson_cost
from rt.pipeline.ledger import load_ledger
from rt.pipeline.review import load_science_issues

PHASES = ["prepare", "outline", "rewrite", "review", "build"]

# Ogni WorkflowState è legato a un'etichetta e a un token di colore SEMANTICO di
# Textual ($primary, $warning, ...), mai a un colore fisso, così la dashboard resta
# leggibile sia in tema scuro che chiaro senza codice dedicato per stato.
STATE_BADGE = {
    WorkflowState.METADATA_ONLY: ("METADATA", "secondary"),
    WorkflowState.SETUP_COMPLETED: ("SETUP", "secondary"),
    WorkflowState.PREPARED: ("PREPARATA", "primary"),
    WorkflowState.OUTLINE_VALIDATED: ("OUTLINE", "primary"),
    WorkflowState.DRAFT_VALIDATED: ("REWRITE", "primary"),
    WorkflowState.REVIEW_READY: ("REVISIONATA", "accent"),
    WorkflowState.HUMAN_REVIEW_REQUIRED: ("REVISIONE", "warning"),
    WorkflowState.READY_TO_BUILD: ("PRONTA BUILD", "accent"),
    WorkflowState.COMPLETED: ("COMPLETATA", "success"),
    WorkflowState.FAILED: ("FALLITA", "error"),
}


@dataclass
class LessonSummary:
    dir_path: str
    title: str
    subject: str
    recorded: str
    when: str
    state: Optional[WorkflowState]
    phase_status: List[Tuple[str, PhaseStatus]]
    pending_issues: int
    cost_total: Optional[float]
    mtime: float
    error: Optional[str] = None


def badge_for_state(state: Optional[WorkflowState]) -> Tuple[str, str]:
    if state is None:
        return ("SCONOSCIUTO", "secondary")
    return STATE_BADGE.get(state, (state.value.upper(), "secondary"))


def _relative_time(mtime: float) -> str:
    delta = max(0.0, time.time() - mtime)
    if delta < 60:
        return "adesso"
    if delta < 3600:
        return f"{int(delta // 60)}m fa"
    if delta < 86400:
        return f"{int(delta // 3600)}h fa"
    days = int(delta // 86400)
    return "ieri" if days <= 1 else f"{days}g fa"


def _lesson_dirs(root: str) -> List[str]:
    if not root or not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full) and os.path.isfile(lesson_path(full, "info.yaml")):
            found.append(full)
    return found


def _lesson_mtime(lesson_dir: str) -> float:
    info_path = lesson_path(lesson_dir, "info.yaml")
    try:
        return os.path.getmtime(info_path)
    except OSError:
        return os.path.getmtime(lesson_dir)


def load_lesson_summary(lesson_dir: str) -> LessonSummary:
    mtime = _lesson_mtime(lesson_dir)
    title = os.path.basename(lesson_dir.rstrip(os.sep))
    try:
        info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
        ledger = load_ledger(lesson_dir)
        sci_issues = load_science_issues(lesson_dir)
        decided_ids = {d.issue_id for d in ledger.decisions}
        pending = sum(1 for x in sci_issues if x.id not in decided_ids)
        phase_status = [(ph, check_phase_status(lesson_dir, ph)[0]) for ph in PHASES]
        cost_data = compute_lesson_cost(lesson_dir)
        return LessonSummary(
            dir_path=lesson_dir,
            title=title,
            subject=info.get("materia") or "",
            recorded=info.get("data") or "",
            when=_relative_time(mtime),
            state=compute_effective_workflow_state(lesson_dir),
            phase_status=phase_status,
            pending_issues=pending,
            cost_total=(cost_data or {}).get("total_estimated_cost_usd"),
            mtime=mtime,
        )
    except Exception as exc:
        # Una lezione con stato illeggibile non deve impedire la lista delle altre:
        # viene mostrata comunque, marcata in errore, invece di far fallire l'intera scansione.
        return LessonSummary(
            dir_path=lesson_dir, title=title, subject="", recorded="", when=_relative_time(mtime),
            state=None, phase_status=[(ph, PhaseStatus.MISSING) for ph in PHASES],
            pending_issues=0, cost_total=None, mtime=mtime, error=str(exc),
        )


def discover_lessons(root: Optional[str]) -> List[LessonSummary]:
    if not root:
        return []
    summaries = [load_lesson_summary(d) for d in _lesson_dirs(root)]
    summaries.sort(key=lambda s: s.mtime, reverse=True)
    return summaries


def load_markdown_preview(lesson_dir: str) -> str:
    """Markdown reale se la lezione è già stata 'build'ata; altrimenti un'anteprima
    live generata al volo dallo stesso renderer usato da 'rt build' (riuso diretto,
    nessuna duplicazione); altrimenti un placeholder onesto."""
    rielab_path = lesson_path(lesson_dir, "rielaborato.md")
    if os.path.isfile(rielab_path):
        try:
            with open(rielab_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            pass

    try:
        from rt.core.segments import load_segments_json
        from rt.pipeline.build import render_rielaborato_md
        from rt.pipeline.ledger import apply_decisions_to_draft
        from rt.pipeline.outline import load_outline
        from rt.pipeline.rewrite import load_draft

        outline = load_outline(lesson_dir)
        draft = load_draft(lesson_dir)
        segments_data = load_segments_json(lesson_path(lesson_dir, "segments.json"))
        ledger = load_ledger(lesson_dir)
        science_issues = load_science_issues(lesson_dir)
        resolved_draft = apply_decisions_to_draft(draft, ledger, science_issues)
        info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
        return render_rielaborato_md(
            outline=outline,
            draft=resolved_draft,
            segments_data=segments_data,
            date=info.get("data") or "",
            subject=info.get("materia") or "",
            topics=info.get("argomenti") or "",
        )
    except Exception:
        return (
            "# Nessuna anteprima disponibile\n\n"
            "Il documento Markdown di questa lezione non è ancora stato generato.\n\n"
            "Serve almeno la fase di *rewrite* completata per un'anteprima live, "
            "oppure la fase di *build* per il documento finale."
        )
