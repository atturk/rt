"""
rt.services.pipeline_service
Orchestratore della pipeline end-to-end (setup → prepare → outline → rewrite → review →
build), riusabile da CLI, API e worker. Non stampa, non legge da stdin e non chiama
sys.exit(): comunica con eventi sul RunContext e restituisce un PipelineResult con uno
stato finale esplicito.

Le decisioni umane (approvazione outline, issue scientifiche) non vengono chieste da qui:
se c'è un DecisionProvider (CLI interattiva) viene interrogato, altrimenti la pipeline si
ferma con WAITING_FOR_DECISION e la DecisionRequired pendente.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence, Union

from rt.services.context import RunCancelled, RunContext, phase_scope
from rt.services.events import DecisionRequired, Notice


class PipelineStatus(str, Enum):
    COMPLETED = "completed"
    WAITING_FOR_DECISION = "waiting_for_decision"
    SKIPPED_TRANSCRIPTION = "skipped_transcription"
    FAILED = "failed"


@dataclass
class PipelineOptions:
    """Opzioni di 'rt run'. I campi di setup servono solo quando l'input è audio."""
    date: Optional[str] = None
    materia: Optional[str] = None
    argomenti: Optional[str] = None
    dest_dir: Optional[str] = None
    model: Optional[str] = None
    skip_transcribe: bool = False
    force: bool = False
    mock: bool = False
    with_review: bool = False
    auto_accept: bool = False
    rename: bool = True
    channel: Optional[str] = None


@dataclass
class PipelineResult:
    status: PipelineStatus
    lesson_dir: Optional[str] = None
    decision: Optional[DecisionRequired] = None
    phase_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[BaseException] = None


class DecisionProvider(Protocol):
    """Chi risponde alle decisioni umane durante la run (es. la CLI interattiva)."""

    def approve_outline(self, lesson_dir: str, force: bool, force_mock: bool) -> None:
        """Ritorna quando l'outline è approvata (eventualmente dopo revisioni); può
        sollevare KeyboardInterrupt se l'utente rinuncia."""

    def review_science_issues(self, lesson_dir: str, channel: str, auto_accept: Optional[str]) -> bool:
        """True se la review è completa e si può procedere al build."""


class Notifier(Protocol):
    """Riceve la notifica di fine build (es. Telegram)."""

    def build_completed(self, lesson_dir: str, build_result: Dict[str, Any], lesson_title: str) -> None: ...


def is_audio_input(inputs: Sequence[str]) -> bool:
    from rt.pipeline.setup import is_audio_file
    return any(is_audio_file(x) for x in inputs)


def outline_needs_approval(lesson_dir: str, force: bool) -> bool:
    """Stessa regola di gating di confirm_or_revise_outline: si chiede conferma solo se il
    rewrite non è già VALID, oppure con force."""
    if force:
        return True
    from rt.core.idempotency import check_phase_status, PhaseStatus
    status, _ = check_phase_status(lesson_dir, "rewrite")
    return status != PhaseStatus.VALID


def lesson_title(lesson_dir: str) -> str:
    import os
    try:
        from rt.pipeline.outline import load_outline
        return load_outline(lesson_dir).lesson_title
    except Exception:
        return os.path.basename(os.path.abspath(lesson_dir))


def _resolve_channel(channel: Optional[str]) -> str:
    if channel:
        return channel
    from rt.core.config import load_config
    return load_config().telegram.default_channel


def _auto_accept_pending(lesson_dir: str, ctx: RunContext) -> List[Any]:
    """Senza DecisionProvider: applica l'auto-accept alle issue pendenti e restituisce
    quelle che richiedono ancora una decisione umana."""
    from rt.pipeline.issue_review import should_auto_accept_science
    from rt.pipeline.ledger import get_pending_issues, record_decision, sanitize_suggested_fix
    _, pending = get_pending_issues(lesson_dir)
    remaining = []
    accepted = 0
    for iss in pending:
        if should_auto_accept_science(iss, "all"):
            record_decision(lesson_dir, iss.id, "accepted", resolved_text=sanitize_suggested_fix(iss.suggested_fix), resolved_by="cli_auto")
            accepted += 1
        else:
            remaining.append(iss)
    if accepted:
        ctx.emit(Notice(message=f"⚡ Auto-approvati {accepted} casi in base ai filtri CLI."))
    return remaining


def _mark_ready_to_build(lesson_dir: str) -> None:
    import os
    from rt.core.lesson_paths import lesson_path
    from rt.core.state import transition_to, WorkflowState
    yaml_path = lesson_path(lesson_dir, "info.yaml")
    if os.path.isfile(yaml_path):
        try:
            transition_to(yaml_path, WorkflowState.READY_TO_BUILD, allow_force=True)
        except Exception:
            pass


def run_pipeline(
    inputs: Union[str, Sequence[str]],
    options: PipelineOptions,
    ctx: RunContext,
    decisions: Optional[DecisionProvider] = None,
    notifiers: Sequence[Notifier] = (),
) -> PipelineResult:
    """Esegue la pipeline completa. Le eccezioni diventano FAILED (con error), tranne
    KeyboardInterrupt e RunCancelled che vengono rilanciate."""
    raw_inputs = [inputs] if isinstance(inputs, str) else list(inputs)
    result = PipelineResult(status=PipelineStatus.FAILED)
    try:
        with ctx.activate():
            _run(raw_inputs, options, ctx, decisions, notifiers, result)
    except (KeyboardInterrupt, RunCancelled):
        raise
    except Exception as exc:  # noqa: BLE001 - lo stato FAILED porta l'eccezione al chiamante
        result.status = PipelineStatus.FAILED
        result.error = exc
    return result


def _run(raw_inputs, options: PipelineOptions, ctx: RunContext, decisions, notifiers, result: PipelineResult) -> None:
    from rt.pipeline.build import run_build
    from rt.pipeline.outline import run_outline
    from rt.pipeline.prepare import run_prepare
    from rt.pipeline.review import run_review
    from rt.pipeline.rewrite import run_rewrite
    from rt.pipeline.setup import MissingSetupFields, run_setup

    force, mock = options.force, options.mock
    ctx.force, ctx.force_mock = force, mock

    if is_audio_input(raw_inputs):
        try:
            with phase_scope(ctx, "setup") as scope:
                setup_res = _setup(run_setup, raw_inputs, options, ctx, decisions)
                scope.complete(setup_res)
        except MissingSetupFields as exc:
            # Nessuno può chiedere i metadati ora: la run aspetta che arrivino (API/worker).
            _wait(result, ctx, "setup_metadata", "setup", {"inputs": raw_inputs, "missing": exc.fields})
            return
        result.phase_results["setup"] = setup_res
        lesson_dir = setup_res["lesson_dir"]
        result.lesson_dir = lesson_dir
        if options.skip_transcribe and not mock:
            result.status = PipelineStatus.SKIPPED_TRANSCRIPTION
            return
    else:
        lesson_dir = raw_inputs[0] if raw_inputs else ""
        result.lesson_dir = lesson_dir
    ctx.lesson_dir = lesson_dir

    result.phase_results["prepare"] = run_prepare(lesson_dir, force=force, ctx=ctx)
    result.phase_results["outline"] = run_outline(lesson_dir, force=force, force_mock=mock, ctx=ctx)

    if outline_needs_approval(lesson_dir, force):
        if decisions is not None:
            decisions.approve_outline(lesson_dir, force=force, force_mock=mock)
        elif not options.auto_accept:
            _wait(result, ctx, "outline_approval", lesson_dir, {"lesson_dir": lesson_dir})
            return

    ctx.check_cancelled()
    result.phase_results["rewrite"] = run_rewrite(lesson_dir, force=force, force_mock=mock, ctx=ctx)

    channel = _resolve_channel(options.channel)
    if options.with_review:
        result.phase_results["review"] = run_review(lesson_dir, force=force, force_mock=mock, ctx=ctx)
        if decisions is not None:
            auto = "all" if options.auto_accept else None
            if not decisions.review_science_issues(lesson_dir, channel, auto):
                _wait(result, ctx, "science_issue", lesson_dir, {"lesson_dir": lesson_dir, "channel": channel})
                return
        else:
            remaining = _auto_accept_pending(lesson_dir, ctx) if options.auto_accept else _pending(lesson_dir)
            if remaining:
                _wait(result, ctx, "science_issue", lesson_dir,
                      {"lesson_dir": lesson_dir, "pending": [i.id for i in remaining]})
                return
            _mark_ready_to_build(lesson_dir)

    ctx.check_cancelled()
    bld_res = run_build(lesson_dir, force=force, rename_folder=options.rename, ctx=ctx)
    result.phase_results["build"] = bld_res
    final_dir = bld_res.get("lesson_dir") or lesson_dir
    result.lesson_dir = final_dir
    result.status = PipelineStatus.COMPLETED

    if not mock:
        title = lesson_title(final_dir)
        for notifier in notifiers:
            notifier.build_completed(final_dir, bld_res, title)


def _setup(run_setup, raw_inputs, options: PipelineOptions, ctx: RunContext, decisions) -> Dict[str, Any]:
    from rt.pipeline.setup import DEFAULT_MODEL
    prompter = getattr(decisions, "setup_prompter", None) if decisions is not None else None
    setup_res = run_setup(
        audio=raw_inputs,
        date=options.date,
        materia=options.materia,
        argomenti=options.argomenti,
        dest_dir=options.dest_dir,
        model=options.model or DEFAULT_MODEL,
        skip_transcribe=options.skip_transcribe,
        force=options.force,
        mock_asr=options.mock,
        interactive=prompter is not None,
        on_progress=lambda msg: ctx.emit(Notice(message=msg)),
        prompter=prompter,
        # Senza DecisionProvider (API/worker) i metadati mancanti non si inventano.
        strict=decisions is None,
    )
    return dict(setup_res, mock_asr=options.mock, skip_transcribe=options.skip_transcribe)


def _pending(lesson_dir: str) -> List[Any]:
    from rt.pipeline.ledger import get_pending_issues
    _, pending = get_pending_issues(lesson_dir)
    return list(pending)


def _wait(result: PipelineResult, ctx: RunContext, kind: str, lesson_dir: str, payload: Dict[str, Any]) -> None:
    import os
    decision = DecisionRequired(kind=kind, id=f"{kind}:{os.path.basename(os.path.abspath(lesson_dir))}", payload=payload)
    ctx.emit(decision)
    result.status = PipelineStatus.WAITING_FOR_DECISION
    result.decision = decision
