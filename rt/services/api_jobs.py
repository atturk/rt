"""
rt.services.api_jobs
Tipi di job usati dall'API (fase E) oltre a quelli standard di rt/services/job_handlers.py:
rewrite di una sola unità, batch e rifornimento del recall, valutazione di una risposta aperta,
revisione dell'outline, prova di una credenziale. Ogni handler chiama i servizi o le funzioni
del motore che usa la CLI per lo stesso comando, così il risultato è identico. Un tipo già
registrato non viene sostituito. Ai tipi standard che ricevono file caricati via API
(run_pipeline, ingest_audio, add_images) si aggiunge la pulizia della cartella di upload.
"""
import os
from typing import Any, Callable, Dict

from pydantic import BaseModel

from rt.services.context import RunContext
from rt.services.jobs import JobInfo, JobState, json_safe
from rt.services.worker import JobOutcome, _HANDLERS, register_handler

REWRITE_UNIT = "rewrite_unit"
RECALL_BATCH = "recall_batch"
RECALL_EVALUATE = "recall_evaluate"
RECALL_REFILL = "recall_refill"
OUTLINE_REVISION = "outline_revision"
CREDENTIAL_TEST = "credential_test"
UPLOAD_JOB_TYPES = ("run_pipeline", "ingest_audio", "add_images")


def _done(result: Dict[str, Any], lesson_path=None) -> JobOutcome:
    return JobOutcome(state=JobState.SUCCEEDED, result=json_safe(result), lesson_path=lesson_path)


def rewrite_unit_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Come 'rt rewrite <cartella> --unit <id>'."""
    from rt.pipeline.rewrite import run_rewrite
    opts = job.payload.get("options") or {}
    force, mock = bool(opts.get("force")), bool(opts.get("mock"))
    ctx.lesson_dir, ctx.force, ctx.force_mock = job.lesson_path, force, mock
    with ctx.activate():
        res = run_rewrite(job.lesson_path, target_unit_id=job.payload["unit"], force=force, force_mock=mock, ctx=ctx)
    return _done({"phase": "rewrite", "unit": job.payload["unit"], "result": res}, lesson_path=job.lesson_path)


def _cleanup_upload(payload: Dict[str, Any]) -> None:
    """I file caricati via API stanno in una cartella temporanea (<radice>/.rt/uploads/<id>):
    a job concluso l'audio o le immagini sono già copiati nella lezione."""
    import shutil
    upload_dir = payload.get("upload_dir")
    if upload_dir and os.path.basename(os.path.dirname(upload_dir)) == "uploads":
        shutil.rmtree(upload_dir, ignore_errors=True)


def with_upload_cleanup(handler: Callable[[JobInfo, RunContext], JobOutcome]):
    """Pulisce la cartella di upload quando il job finisce (non se si ferma su una decisione:
    i file servono ancora alla ripresa)."""
    def wrapped(job: JobInfo, ctx: RunContext) -> JobOutcome:
        try:
            outcome = handler(job, ctx)
        except Exception:  # fallito o annullato; un arresto del worker (BaseException) lo rimette in coda
            _cleanup_upload(job.payload)
            raise
        if outcome.state != JobState.WAITING_FOR_DECISION:
            _cleanup_upload(job.payload)
        return outcome
    wrapped.upload_cleanup = True
    return wrapped


def recall_batch_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Genera un batch di domande di un tipo (come la ricarica della riserva nel recall)."""
    from rt.core.config import load_config
    from rt.core.models import RecallQuestionType
    from rt.pipeline.recall import generate_recall_batch, load_fewshot_examples
    from rt.services.recall_service import recall_overview
    p = job.payload
    qtype = RecallQuestionType(p["qtype"])
    cfg = load_config()
    count = int(p.get("count") or cfg.telegram.recall.reserve_targets.get(qtype.value, 5))
    examples = load_fewshot_examples(qtype, state_dir=cfg.telegram.state_dir)
    with ctx.activate():
        generate_recall_batch(job.lesson_path, qtype, count, examples, force_mock=bool(p.get("mock")))
    return _done(recall_overview(job.lesson_path), lesson_path=job.lesson_path)


def recall_evaluate_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Valuta una risposta aperta (scritta o vocale) e la salva, come il recall da terminale."""
    from rt.services.recall_service import handle_recall_answer
    p = job.payload
    answer, is_voice = p.get("answer") or "", False
    if p.get("audio_path"):
        from rt.core.config import load_config
        from rt.core.recall_stt import transcribe_voice_answer
        answer = transcribe_voice_answer(p["audio_path"], load_config().telegram.recall.stt_engine)
        is_voice = True
        _cleanup_upload(p)
    evaluation = handle_recall_answer(job.lesson_path, p["question_id"], answer, is_voice=is_voice,
                                      force_mock=bool(p.get("mock")))
    if evaluation is None:
        raise ValueError("Domanda inesistente o a scelta multipla.")
    return _done({"question_id": p["question_id"], "answer": answer, "evaluation": evaluation},
                 lesson_path=job.lesson_path)


def recall_refill_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Rifornisce la riserva di un tipo sotto soglia (dopo una domanda mostrata)."""
    from rt.core.models import RecallQuestionType
    from rt.services.recall_service import recall_overview, refill_active_type_if_low
    with ctx.activate():
        refill_active_type_if_low(job.lesson_path, RecallQuestionType(job.payload["qtype"]),
                                  force_mock=bool(job.payload.get("mock")))
    return _done(recall_overview(job.lesson_path), lesson_path=job.lesson_path)


def outline_revision_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.services.outline_service import get_outline_review, request_outline_revision
    ctx.force_mock = bool(job.payload.get("mock"))
    res = request_outline_revision(job.lesson_path, job.payload["feedback"], ctx=ctx)
    return _done({"result": res, "outline": get_outline_review(job.lesson_path)}, lesson_path=job.lesson_path)


class _Ping(BaseModel):
    ok: bool


def credential_test_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Chiamata minima al provider con una credenziale: esito sanificato, mai la chiave."""
    p = job.payload
    if p.get("mock"):
        return _done({"ok": True, "credential": p["credential"], "message": "Mock: nessuna chiamata di rete."})
    from rt.core.config import load_config
    from rt.llm.client import LLMClient
    from rt.services.settings_service import general_config_path, _read_yaml
    load_config()  # registra le credenziali dichiarate
    declared = {c.get("name"): c for c in _read_yaml(general_config_path(None)).get("credentials") or []
                if isinstance(c, dict)}
    provider = p.get("provider") or (declared.get(p["credential"]) or {}).get("provider")
    try:
        LLMClient().call_structured(
            prompt='Rispondi con {"ok": true}.', system_prompt="Rispondi solo con JSON.",
            response_model=_Ping, job_name="outline", max_retries=0,
            override_provider=provider, override_model=p["model"], override_base_url=p.get("base_url") or None,
            override_credential=p["credential"], stream=False, show_monitor=False,
        )
    except Exception as exc:  # noqa: BLE001 - l'esito è il risultato del job
        from rt.services.context import _sanitize
        return _done({"ok": False, "credential": p["credential"], "message": _sanitize(f"{type(exc).__name__}: {exc}")[:500]})
    return _done({"ok": True, "credential": p["credential"], "message": "Credenziale valida."})


for _type, _handler in (
    (REWRITE_UNIT, rewrite_unit_job), (RECALL_BATCH, recall_batch_job), (RECALL_EVALUATE, recall_evaluate_job),
    (RECALL_REFILL, recall_refill_job),
    (OUTLINE_REVISION, outline_revision_job), (CREDENTIAL_TEST, credential_test_job),
):
    if _type not in _HANDLERS:
        register_handler(_type, _handler)

import rt.services.job_handlers  # noqa: E402,F401 - i tipi standard prima di avvolgerli

for _type in UPLOAD_JOB_TYPES:
    if _type in _HANDLERS and not getattr(_HANDLERS[_type], "upload_cleanup", False):
        _HANDLERS[_type] = with_upload_cleanup(_HANDLERS[_type])
