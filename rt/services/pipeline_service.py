"""
rt.services.pipeline_service
Orchestratore della pipeline end-to-end (setup → prepare → outline → rewrite → review →
build), riusabile da CLI, API e worker. Non stampa, non legge da stdin e non chiama
sys.exit(): comunica con eventi sul RunContext e restituisce un PipelineResult con uno
stato finale esplicito.

Le decisioni umane (approvazione outline, issue scientifiche, metadati mancanti) non vengono
chieste da qui: la pipeline si ferma con WAITING_FOR_DECISION e la DecisionRequired pendente,
che si prende nella web.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence, Union

from rt.services.context import RunCancelled, RunContext, phase_scope
from rt.pipeline.outline_review import outline_needs_approval
from rt.pipeline.unit_failures import raise_if_incomplete
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
    docente: Optional[str] = None
    ora: Optional[str] = None
    dest_dir: Optional[str] = None
    model: Optional[str] = None
    skip_transcribe: bool = False
    force: bool = False
    skip_prefilter: bool = False
    mock: bool = False
    with_review: bool = False
    with_enrichment: Optional[bool] = None
    auto_accept: bool = False
    rename: bool = True
    # chi ha lanciato la pipeline: canale delle decisioni automatiche nel ledger ("cli" o "api")
    source: str = "api"


@dataclass
class PipelineResult:
    status: PipelineStatus
    lesson_dir: Optional[str] = None
    decision: Optional[DecisionRequired] = None
    phase_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[BaseException] = None


class Notifier(Protocol):
    """Riceve la notifica di fine build (es. Telegram). Restituisce True se ha inviato
    qualcosa (None/False: non configurato o niente da fare)."""

    def build_completed(self, lesson_dir: str, build_result: Dict[str, Any], lesson_title: str) -> Optional[bool]: ...


_BUILD_NOTIFIERS: List[Notifier] = []


def register_build_notifier(notifier: Notifier) -> None:
    """Notifier di fine build usati dai job del worker (run_pipeline, run_phase build). Li
    registra chi avvia il worker ('rt worker', e quindi 'rt web'): il service layer non
    conosce Telegram. Un notifier dello stesso tipo già registrato viene sostituito."""
    _BUILD_NOTIFIERS[:] = [n for n in _BUILD_NOTIFIERS if type(n) is not type(notifier)] + [notifier]


def unregister_build_notifiers() -> None:
    _BUILD_NOTIFIERS.clear()


def build_notifiers() -> List[Notifier]:
    return list(_BUILD_NOTIFIERS)


def is_audio_input(inputs: Sequence[str]) -> bool:
    from rt.pipeline.setup import is_audio_file
    return any(is_audio_file(x) for x in inputs)


def lesson_title(lesson_dir: str) -> str:
    import os
    try:
        from rt.pipeline.outline import load_outline
        return load_outline(lesson_dir).lesson_title
    except Exception:
        return os.path.basename(os.path.abspath(lesson_dir))


def _auto_accept_pending(lesson_dir: str, ctx: RunContext, channel: str = "api") -> List[Any]:
    """Applica l'auto-accept alle issue pendenti e restituisce quelle che richiedono ancora
    una decisione umana."""
    from rt.services.review_service import auto_accept_pending
    accepted, remaining = auto_accept_pending(lesson_dir, "all", channel=channel)
    if accepted:
        ctx.emit(Notice(message=f"⚡ Auto-approvati {len(accepted)} casi in base ai filtri CLI."))
    return remaining


def run_pipeline(
    inputs: Union[str, Sequence[str]],
    options: PipelineOptions,
    ctx: RunContext,
    notifiers: Sequence[Notifier] = (),
) -> PipelineResult:
    """Esegue la pipeline completa. Le eccezioni diventano FAILED (con error), tranne
    KeyboardInterrupt e RunCancelled che vengono rilanciate."""
    raw_inputs = [inputs] if isinstance(inputs, str) else list(inputs)
    result = PipelineResult(status=PipelineStatus.FAILED)
    try:
        with ctx.activate():
            _run(raw_inputs, options, ctx, notifiers, result)
    except (KeyboardInterrupt, RunCancelled):
        raise
    except Exception as exc:  # noqa: BLE001 - lo stato FAILED porta l'eccezione al chiamante
        from rt.llm.errors import DeferredCall, DeferredPhase
        if isinstance(exc, (DeferredCall, DeferredPhase)):
            raise
        result.status = PipelineStatus.FAILED
        result.error = exc
    return result


def _run(raw_inputs, options: PipelineOptions, ctx: RunContext, notifiers, result: PipelineResult) -> None:
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
                setup_res = _setup(run_setup, raw_inputs, options, ctx)
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
        from rt.core.config import load_config
        from rt.services import outline_service
        if options.auto_accept:
            outline_service.approve_outline(lesson_dir, actor="auto_accept", channel=options.source)
        elif not outline_service.is_outline_approved(lesson_dir):
            mode = getattr(load_config().ui, "outline_mode", "auto")
            if mode == "auto":
                outline_service.approve_outline(lesson_dir, actor="server", channel="server")
            else:
                if mode == "timer":
                    outline_service.start_outline_timer(lesson_dir)
                _wait(result, ctx, "outline_approval", lesson_dir,
                      {"lesson_dir": lesson_dir, "outline": outline_service.get_outline_review(lesson_dir)})
                return

    ctx.check_cancelled()
    result.phase_results["rewrite"] = run_rewrite(lesson_dir, force=force, force_mock=mock, ctx=ctx)
    # Unità non riuscite: le fasi successive lavorerebbero su un draft incompleto. La run si
    # ferma qui (FAILED con il motivo); rilanciarla rifà solo le unità mancanti.
    raise_if_incomplete("rewrite", result.phase_results["rewrite"])

    if options.with_review:
        result.phase_results["review"] = run_review(lesson_dir, force=force, force_mock=mock, ctx=ctx)
        raise_if_incomplete("review", result.phase_results["review"])
        remaining = _auto_accept_pending(lesson_dir, ctx, options.source) if options.auto_accept else _pending(lesson_dir)
        # Nella lavorazione completa basta «Lezione pronta» (o «Issue da decidere»): niente doppioni.
        if remaining:
            _wait(result, ctx, "science_issue", lesson_dir,
                  {"lesson_dir": lesson_dir, "pending": [i.id for i in remaining]})
            return
        from rt.services.review_service import mark_ready_to_build
        mark_ready_to_build(lesson_dir)

    ctx.check_cancelled()
    result.phase_results["enrichment"] = automatic_enrichment(lesson_dir, mock, ctx, with_enrichment=options.with_enrichment)
    bld_res = run_build(lesson_dir, force=force, rename_folder=options.rename, ctx=ctx)
    result.phase_results["build"] = bld_res
    final_dir = bld_res.get("lesson_dir") or lesson_dir
    result.lesson_dir = final_dir
    result.status = PipelineStatus.COMPLETED
    if not mock:
        notify_build_completed(final_dir, bld_res, ctx, notifiers)



def notify_build_completed(lesson_dir: str, build_result: Dict[str, Any], ctx: RunContext,
                           notifiers: Sequence[Notifier]) -> None:
    """Avvisa i notifier (es. Telegram) che il documento è pronto. Un errore di invio non fa
    fallire la run: diventa un avviso negli eventi."""
    if not notifiers:
        return
    title = lesson_title(lesson_dir)
    for notifier in notifiers:
        try:
            sent = notifier.build_completed(lesson_dir, build_result, title)
        except Exception as exc:  # noqa: BLE001 - la notifica non deve mai far fallire la run
            from rt.services.context import _sanitize
            ctx.emit(Notice(level="warning", message=f"Notifica di fine lavorazione non inviata: {_sanitize(str(exc))}"))
            continue
        if sent:
            ctx.emit(Notice(message=f"Notifica di fine lavorazione inviata ({getattr(notifier, 'channel', 'notifica')})."))


def notify_review_completed(lesson_dir: str, pending_count: int, ctx: RunContext,
                            notifiers: Sequence[Notifier]) -> None:
    """Avvisa i notifier (es. Telegram) che la verifica è completata."""
    if not notifiers:
        return
    title = lesson_title(lesson_dir)
    for notifier in notifiers:
        fn = getattr(notifier, "review_completed", None)
        if fn is None:
            continue
        try:
            sent = fn(lesson_dir, pending_count, title)
        except Exception as exc:  # noqa: BLE001 - la notifica non deve mai far fallire la run
            from rt.services.context import _sanitize
            ctx.emit(Notice(level="warning", message=f"Notifica di fine verifica non inviata: {_sanitize(str(exc))}"))
            continue
        if sent:
            ctx.emit(Notice(message=f"Notifica di fine verifica inviata ({getattr(notifier, 'channel', 'notifica')})."))


def emit_stt_progress(ctx: RunContext, phase: str, msg: str) -> None:
    if msg.startswith("✔"):
        ctx.emit(Notice(message=msg))
        return
    import re
    pct = None
    match = re.search(r"\b(\d{1,3})%", msg)
    if match and ("Scarico" in msg or "modello di trascrizione" in msg):
        pct = min(100, int(match.group(1)))
    ctx.progress(phase, pct, 100 if pct is not None else None, msg)


def _setup_progress(ctx: RunContext, msg: str) -> None:
    emit_stt_progress(ctx, "setup", msg)


def _setup(run_setup, raw_inputs, options: PipelineOptions, ctx: RunContext) -> Dict[str, Any]:
    from rt.pipeline.setup import DEFAULT_MODEL
    setup_res = run_setup(
        audio=raw_inputs,
        date=options.date,
        materia=options.materia,
        docente=options.docente,
        ora=options.ora,
        dest_dir=options.dest_dir,
        model=options.model or DEFAULT_MODEL,
        skip_transcribe=options.skip_transcribe,
        force=options.force,
        mock_asr=options.mock,
        interactive=False,
        on_progress=lambda msg: _setup_progress(ctx, msg),
        on_lesson_created=lambda d: _lesson_created(ctx, d),
        # Percentuale di macparakeet: la barra del job avanza durante la trascrizione.
        on_transcription_progress=lambda pct: ctx.progress("setup", pct, 100, f"Trascrizione audio: {pct}%"),
        # I metadati mancanti non si inventano: la run aspetta che arrivino.
        strict=True,
        cancel_token=ctx.cancel_token,
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


# ---------------------------------------------------------------- job singoli (fase D)

RUNNABLE_PHASES = ("prepare", "outline", "rewrite", "review", "build")


def automatic_enrichment(lesson_dir: str, mock: bool, ctx: RunContext,
                         with_enrichment: Optional[bool] = None) -> Dict[str, Any]:
    """Optional analysis: failures do not prevent the lesson from being built."""
    from rt.core.config import load_config
    cfg = load_config()
    from rt.core.config import classifier_job
    enrichment_mode = classifier_job(cfg, "enrichment").mode
    if enrichment_mode == "off":
        return {"skipped": "disabled"}
    should_run = (with_enrichment is True) or (with_enrichment is None and enrichment_mode == "pipeline")
    if not should_run:
        return {"skipped": "manual" if enrichment_mode == "manual" else "disabled"}
    route = cfg.jobs.get("enrichment_writer")
    if not mock and (not route or not route.primary.is_configured):
        ctx.emit(Notice(message="Arricchimento automatico disponibile dopo aver configurato l'Arricchitore in Modelli."))
        return {"skipped": "not_configured"}
    try:
        from rt.services.enrichment_service import analyze
        return analyze(lesson_dir, mock=mock, ctx=ctx)
    except RunCancelled:
        raise
    except Exception as exc:
        from rt.llm.errors import DeferredCall, DeferredPhase
        if isinstance(exc, (DeferredCall, DeferredPhase)):
            raise
        from rt.services.context import _sanitize
        ctx.emit(Notice(level="warning", message=f"Analisi di arricchimento da riprovare: {_sanitize(str(exc))}"))
        return {"error": _sanitize(str(exc))}


class TranscriptionUnavailable(RuntimeError):
    """La trascrizione con macparakeet non può girare su questa macchina."""


def transcription_unavailable_reason(mock: bool = False, skip_transcribe: bool = False) -> Optional[str]:
    """Motivo per cui l'ingest audio non può trascrivere qui (None se può). macparakeet-cli
    esiste solo su macOS; il motore STT 'custom', Parakeet ONNX e la modalità mock girano ovunque."""
    import sys
    if mock or skip_transcribe:
        return None
    try:
        from rt.core.config import effective_engine, load_config
        engine = effective_engine(load_config().transcription)
        if engine == "custom":
            return None
        if engine == "parakeet":
            from rt.core.onnx_stt import available
            if available():
                return None
            return ("Parakeet ONNX scelto ma il pacchetto onnx-asr non è installato. "
                    "Reinstalla RT oppure scegli un altro motore in Impostazioni.")
        if sys.platform == "darwin":
            from rt.pipeline.setup import find_macparakeet_binary
            if find_macparakeet_binary():
                return None
            return ("macparakeet-cli non trovato e Parakeet ONNX non è disponibile. "
                    "Installa macparakeet-cli oppure reinstalla RT.")
    except Exception:
        if sys.platform == "darwin":
            return None
    return ("La trascrizione con macparakeet funziona solo su macOS: in Impostazioni scegli "
            "Parakeet ONNX (locale) o un server di trascrizione compatibile.")


def _lesson_created(ctx: RunContext, lesson_dir: str) -> None:
    # Il job che fallisce dopo il setup sa ancora quale lezione ha creato (collegamento al calendario).
    ctx.lesson_dir = lesson_dir
    ctx.progress("setup", message="Lezione creata", lesson_dir=lesson_dir)


def ingest_audio(inputs: Union[str, Sequence[str]], options: PipelineOptions, ctx: RunContext) -> PipelineResult:
    """Solo setup + trascrizione (job ingest_audio). Metadati mancanti → WAITING_FOR_DECISION."""
    from rt.pipeline.setup import MissingSetupFields, run_setup
    raw_inputs = [inputs] if isinstance(inputs, str) else list(inputs)
    reason = transcription_unavailable_reason(options.mock, options.skip_transcribe)
    if reason:
        raise TranscriptionUnavailable(reason)
    result = PipelineResult(status=PipelineStatus.FAILED)
    with ctx.activate():
        try:
            with phase_scope(ctx, "setup") as scope:
                setup_res = _setup(run_setup, raw_inputs, options, ctx)
                scope.complete(setup_res)
        except MissingSetupFields as exc:
            _wait(result, ctx, "setup_metadata", "setup", {"inputs": raw_inputs, "missing": exc.fields})
            return result
    result.phase_results["setup"] = setup_res
    result.lesson_dir = setup_res["lesson_dir"]
    result.status = (PipelineStatus.SKIPPED_TRANSCRIPTION if options.skip_transcribe and not options.mock
                     else PipelineStatus.COMPLETED)
    return result


def run_phase(lesson_dir: str, phase: str, options: PipelineOptions, ctx: RunContext,
              notifiers: Sequence[Notifier] = ()) -> PipelineResult:
    """Esegue una sola fase su una lezione esistente (job run_phase), con la stessa
    idempotenza dei comandi 'rt prepare|outline|rewrite|review|build'."""
    if phase not in RUNNABLE_PHASES:
        raise ValueError(f"Fase sconosciuta: {phase} (valide: {', '.join(RUNNABLE_PHASES)})")
    from rt.pipeline.build import run_build
    from rt.pipeline.outline import run_outline
    from rt.pipeline.prepare import run_prepare
    from rt.pipeline.review import run_review
    from rt.pipeline.rewrite import run_rewrite

    force, mock = options.force, options.mock
    ctx.lesson_dir, ctx.force, ctx.force_mock = lesson_dir, force, mock
    result = PipelineResult(status=PipelineStatus.COMPLETED, lesson_dir=lesson_dir)
    with ctx.activate():
        if phase == "prepare":
            res = run_prepare(lesson_dir, force=force, ctx=ctx)
        elif phase == "outline":
            res = run_outline(lesson_dir, force=force, force_mock=mock, ctx=ctx)
        elif phase == "rewrite":
            res = run_rewrite(lesson_dir, force=force, force_mock=mock, ctx=ctx)
        elif phase == "review":
            res = run_review(lesson_dir, force=force, force_mock=mock, ctx=ctx,
                             **({"skip_prefilter": True} if options.skip_prefilter else {}))
        else:
            result.phase_results["enrichment"] = automatic_enrichment(lesson_dir, mock, ctx)
            res = run_build(lesson_dir, force=force, rename_folder=options.rename, ctx=ctx)
            result.lesson_dir = res.get("lesson_dir") or lesson_dir
    result.phase_results[phase] = res
    raise_if_incomplete(phase, res)
    if phase == "review":
        notify_review_completed(lesson_dir, len(_pending(lesson_dir)), ctx, notifiers)
    if phase in ("rewrite", "review"):
        with ctx.activate():
            result.phase_results["enrichment"] = automatic_enrichment(lesson_dir, mock, ctx)
    return result
