"""
rt.services.api_jobs
Tipi di job usati dall'API (fase E) oltre a quelli standard di rt/services/job_handlers.py:
rewrite di una sola unità, batch e rifornimento del recall, valutazione di una risposta aperta,
revisione dell'outline, prova di una credenziale, importazione di archivi ZIP di lezioni,
esportazione di un topic Telegram. Ogni handler chiama i servizi o le funzioni del motore che
usa la CLI per lo stesso comando, così il risultato è identico. Un tipo già registrato non
viene sostituito. Ai tipi che ricevono file caricati via API (run_pipeline, ingest_audio,
add_images, import_lesson_zips) si aggiunge la pulizia della cartella di upload.
"""
import os
from typing import Any, Callable, Dict

from pydantic import BaseModel

from rt.services.context import RunContext
from rt.services.jobs import JobInfo, JobState, json_safe
from rt.services.worker import JobOutcome, _HANDLERS, register_handler
from rt.storage import fs

REWRITE_UNIT = "rewrite_unit"
REVIEW_UNIT = "review_unit"
RECALL_BATCH = "recall_batch"
RECALL_EVALUATE = "recall_evaluate"
RECALL_REFILL = "recall_refill"
OUTLINE_REVISION = "outline_revision"
CREDENTIAL_TEST = "credential_test"
TELEGRAM_LISTEN_TOPICS = "telegram_listen_topics"
IMPORT_LESSON_ZIPS = "import_lesson_zips"
TELEGRAM_TOPIC_EXPORT = "telegram_topic_export"
UNIT_RELEVANCE = "unit_relevance"
UPLOAD_JOB_TYPES = ("run_pipeline", "ingest_audio", "add_images", IMPORT_LESSON_ZIPS)


def _done(result: Dict[str, Any], lesson_path=None) -> JobOutcome:
    return JobOutcome(state=JobState.SUCCEEDED, result=json_safe(result), lesson_path=lesson_path)


def rewrite_unit_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Come 'rt rewrite <cartella> --unit <id>'."""
    from rt.pipeline.rewrite import run_rewrite
    from rt.services.prompt_settings import extra_scope
    opts = job.payload.get("options") or {}
    extra = str(job.payload.get("extra_prompt") or "").strip()
    # Istruzioni nuove: l'unità va riscritta anche se l'impronta dice che è già valida.
    force, mock = bool(opts.get("force")) or bool(extra), bool(opts.get("mock"))
    ctx.lesson_dir, ctx.force, ctx.force_mock = job.lesson_path, force, mock
    from rt.pipeline.unit_failures import raise_if_incomplete
    results = []
    with extra_scope(job.lesson_path, "rewrite", job.payload), ctx.activate():
        for unit in job.payload.get("units") or [job.payload["unit"]]:
            res = run_rewrite(job.lesson_path, target_unit_id=unit, force=force, force_mock=mock, ctx=ctx)
            raise_if_incomplete("rewrite", res)
            results.append({"unit": unit, "result": res})
    return _done({"phase": "rewrite", "units": results}, lesson_path=job.lesson_path)


def review_unit_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    from rt.pipeline.review import run_review_unit
    from rt.services.prompt_settings import extra_scope
    from rt.pipeline.rewrite import load_draft
    present = {unit.unit_id for unit in load_draft(job.lesson_path).units}
    results = []
    with extra_scope(job.lesson_path, "review", job.payload), ctx.activate():
        for unit in job.payload.get("units") or [job.payload["unit"]]:
            if unit not in present:
                results.append({"unit": unit, "status": "skipped", "reason": "Unità non presente nella bozza"})
                continue
            results.append(run_review_unit(job.lesson_path, unit,
                                           force_mock=bool((job.payload.get("options") or {}).get("mock"))))
    return _done({"phase": "review", "units": results}, lesson_path=job.lesson_path)


def _cleanup_upload(payload: Dict[str, Any]) -> None:
    """I file caricati via API stanno in una cartella temporanea (<radice>/.rt/uploads/<id>):
    a job concluso l'audio o le immagini sono già copiati nella lezione."""
    import shutil
    upload_dir = payload.get("upload_dir")
    if upload_dir and os.path.basename(os.path.dirname(upload_dir)) == "uploads":
        fs.rmtree(upload_dir, ignore_errors=True)


def with_upload_cleanup(handler: Callable[[JobInfo, RunContext], JobOutcome]):
    """Pulisce la cartella di upload quando il job finisce (non se si ferma su una decisione:
    i file servono ancora alla ripresa; non se fallisce: servono a 'Riprova', e li pulisce il
    job ripreso quando finisce, o sweep_stale_uploads dopo UPLOAD_MAX_AGE_DAYS)."""
    def wrapped(job: JobInfo, ctx: RunContext) -> JobOutcome:
        from rt.services.context import RunCancelled
        try:
            outcome = handler(job, ctx)
        except RunCancelled:
            _cleanup_upload(job.payload)
            raise
        if outcome.state != JobState.WAITING_FOR_DECISION:
            _cleanup_upload(job.payload)
        return outcome
    wrapped.upload_cleanup = True
    return wrapped


UPLOAD_MAX_AGE_DAYS = 7


def sweep_stale_uploads(uploads_root: str, queue, max_age_days: float = UPLOAD_MAX_AGE_DAYS) -> int:
    """Cancella le cartelle di upload più vecchie di max_age_days che nessun job attivo usa
    (restano quelle dei job falliti non ripresi). Restituisce quante ne ha cancellate."""
    import time
    from rt.services.jobs import ACTIVE_STATES
    if not fs.isdir(uploads_root):
        return 0
    in_use = {os.path.abspath(j.payload.get("upload_dir")) for j in queue.list(state=list(ACTIVE_STATES), limit=500)
              if j.payload.get("upload_dir")}
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for name in os.listdir(uploads_root):
        path = os.path.abspath(os.path.join(uploads_root, name))
        if path in in_use or not os.path.isdir(path) or os.path.getmtime(path) > cutoff:
            continue
        fs.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


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
    from rt.services.unit_relevance import list_units, mode
    from rt.services.events import Notice
    with ctx.activate():
        generated = generate_recall_batch(job.lesson_path, qtype, count, examples, force_mock=bool(p.get("mock")))
        units = list_units(job.lesson_path)["units"] if mode() != "disabled" else []
        excluded = [u["unit_id"] for u in units if u["effective"] != "didactic"]
        message = f"Recall {qtype.value}: richieste {count}, generate {len(generated)}."
        if excluded:
            label = "escluse" if mode() == "active" else "non didattiche rilevate (gate in ombra)"
            message += f" Unità {label}: {len(excluded)} ({', '.join(excluded[:12])}{'…' if len(excluded) > 12 else ''})."
        ctx.emit(Notice(message=message))
    return _done(recall_overview(job.lesson_path), lesson_path=job.lesson_path)


MOCK_VOICE_TRANSCRIPT = "Risposta vocale di prova (trascrizione mock)."


def recall_evaluate_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Valuta una risposta aperta (scritta o vocale) e la salva, come il recall da terminale."""
    from rt.services.recall_service import handle_recall_answer
    p = job.payload
    answer, is_voice = p.get("answer") or "", False
    if p.get("audio_path"):
        if p.get("mock"):
            answer = MOCK_VOICE_TRANSCRIPT  # in mock niente STT: il file resta solo una prova
        else:
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


def unit_relevance_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Come 'rt relevance': etichette JEV per le unità nuove o cambiate (force: tutte)."""
    from rt.services.unit_relevance import list_units, refresh
    with ctx.activate():
        refresh(job.lesson_path, force_mock=bool(job.payload.get("mock")), ctx=ctx,
                force=bool(job.payload.get("force")))
    overview = list_units(job.lesson_path)
    return _done({"mode": overview["mode"], "units": len(overview["units"]),
                  "errors": sum(1 for unit in overview["units"] if unit.get("error")),
                  "excluded": sum(1 for unit in overview["units"] if unit["effective"] != "didactic")},
                 lesson_path=job.lesson_path)


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


def telegram_listen_topics_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Ascolta i messaggi al bot per rilevare chat e topic: l'esito (anche un errore) è il risultato."""
    from rt.services.telegram_topics import TopicListenError, known_materie, listen_topics, listen_existing_daemon, match_materia
    try:
        found = (listen_existing_daemon if job.payload.get("existing_daemon") else listen_topics)(
            seconds=int(job.payload.get("seconds") or 20))
    except TopicListenError as exc:
        return _done({"ok": False, "message": str(exc), "chat_id": None, "topics": []})
    n = len(found["topics"])
    message = (f"Rilevati {n} topic. Assegna una materia a ciascuno e salva." if n
               else "Nessun topic rilevato. Invia un messaggio in un topic e riprova.")
    # Nome del topic dal Bot API e, se coincide con una materia nota, la materia proposta.
    materie = known_materie() if found.get("names") else []
    found["materie"] = {topic: m for topic, name in found.get("names", {}).items()
                        if (m := match_materia(name, materie))}
    return _done({"ok": True, "message": message, **found})


def import_lesson_zips_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Importa gli archivi ZIP completi caricati via API, uno alla volta: un archivio rifiutato
    (anche già alla richiesta, per nome o firma) non ferma gli altri. Il risultato elenca per
    ogni file l'esito e l'id della lezione creata."""
    import zipfile
    from rt.services.context import RunCancelled, _sanitize
    from rt.services.errors import ServiceError
    from rt.services.lesson_import_service import import_archive
    entries = [e for e in job.payload.get("archives") or [] if isinstance(e, dict)]
    total, results = len(entries), []
    for index, entry in enumerate(entries):
        ctx.check_cancelled()
        name = str(entry.get("file") or "")
        ctx.progress(IMPORT_LESSON_ZIPS, index, total, message=f"Importo {name}")
        path = entry.get("path")
        if entry.get("reason") or not path or not os.path.isfile(path):
            results.append({"file": name, "status": "rejected",
                            "reason": entry.get("reason") or "Archivio non più disponibile: caricalo di nuovo."})
            continue
        try:
            lesson_id = import_archive(path)
        except RunCancelled:
            raise
        except ServiceError as exc:
            results.append({"file": name, "status": "rejected", "reason": exc.message})
        except (zipfile.BadZipFile, ValueError):
            results.append({"file": name, "status": "rejected", "reason": "Archivio ZIP non valido."})
        except Exception as exc:  # noqa: BLE001 - l'esito del singolo archivio va nel risultato
            results.append({"file": name, "status": "rejected",
                            "reason": _sanitize(f"Importazione non riuscita: {type(exc).__name__}: {exc}")[:500]})
        else:
            results.append({"file": name, "status": "imported", "lesson_id": lesson_id})
    imported = sum(1 for r in results if r["status"] == "imported")
    ctx.progress(IMPORT_LESSON_ZIPS, total, total, message=f"Importate {imported} su {total}")
    return _done({"results": results, "imported": imported, "rejected": total - imported})


EXPORT_MAX_AGE_HOURS = 24


def exports_root() -> str:
    """Archivi prodotti dai job (es. export di un topic Telegram), sullo stesso disco delle
    lezioni come gli upload: li serve l'API anche se il worker gira in un altro processo."""
    from rt.services.lesson_service import lessons_root
    base = lessons_root() or os.path.expanduser("~")
    return os.path.join(base, ".rt", "exports")


def job_export_path(job_id: str, filename: str) -> str:
    return os.path.join(exports_root(), os.path.basename(job_id), os.path.basename(filename))


def sweep_stale_exports(max_age_hours: float = EXPORT_MAX_AGE_HOURS) -> int:
    """Cancella gli archivi prodotti da più di max_age_hours: fino ad allora si possono
    scaricare di nuovo. Restituisce quanti ne ha cancellati."""
    import time
    root = exports_root()
    if not os.path.isdir(root):
        return 0
    cutoff, removed = time.time() - max_age_hours * 3600, 0
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path) and not os.path.islink(path) and os.path.getmtime(path) < cutoff:
            fs.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def telegram_topic_export_job(job: JobInfo, ctx: RunContext) -> JobOutcome:
    """Esporta cronologia e media di un topic con l'account utente e lascia lo ZIP in
    exports_root()/<job_id>/: lo scarica GET /settings/telegram/user/archives/{job_id}."""
    import asyncio
    import shutil
    import time
    from rt.services.telegram_user_archive import export_topic
    chat_id, topic_id = int(job.payload["chat_id"]), int(job.payload["topic_id"])
    sweep_stale_exports()
    counted = {"messages": 0, "bytes": 0, "last": 0.0}

    def progress(messages: int, media_bytes: int) -> None:
        ctx.check_cancelled()
        counted.update(messages=messages, bytes=media_bytes)
        now = time.monotonic()
        if now - counted["last"] >= 1.0:  # al massimo un evento al secondo, non uno per messaggio
            counted["last"] = now
            ctx.progress(TELEGRAM_TOPIC_EXPORT, messages, None,
                         message=f"{messages} messaggi, {media_bytes / (1024 * 1024):.0f} MB di media")

    ctx.progress(TELEGRAM_TOPIC_EXPORT, 0, None, message="Collegamento a Telegram")
    # Gli errori di dominio (ServiceError: sessione scaduta, topic troppo grande, media non
    # scaricato) diventano l'errore del job con il loro messaggio (job_error_message).
    path, folder = asyncio.run(export_topic(chat_id, topic_id, progress=progress))
    filename = f"telegram-topic-{topic_id}.zip"
    target = job_export_path(job.id, filename)
    try:
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        shutil.move(path, target)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    ctx.progress(TELEGRAM_TOPIC_EXPORT, counted["messages"], counted["messages"],
                 message=f"Archivio pronto: {counted['messages']} messaggi")
    return _done({"topic_id": topic_id, "file": filename, "size": os.path.getsize(target),
                  "messages": counted["messages"], "media_bytes": counted["bytes"]})


for _type, _handler in (
    (REWRITE_UNIT, rewrite_unit_job), (REVIEW_UNIT, review_unit_job), (RECALL_BATCH, recall_batch_job), (RECALL_EVALUATE, recall_evaluate_job),
    (RECALL_REFILL, recall_refill_job), (UNIT_RELEVANCE, unit_relevance_job),
    (OUTLINE_REVISION, outline_revision_job), (CREDENTIAL_TEST, credential_test_job),
    (TELEGRAM_LISTEN_TOPICS, telegram_listen_topics_job),
    (IMPORT_LESSON_ZIPS, import_lesson_zips_job), (TELEGRAM_TOPIC_EXPORT, telegram_topic_export_job),
):
    if _type not in _HANDLERS:
        register_handler(_type, _handler)

import rt.services.job_handlers  # noqa: E402,F401 - i tipi standard prima di avvolgerli

for _type in UPLOAD_JOB_TYPES:
    if _type in _HANDLERS and not getattr(_HANDLERS[_type], "upload_cleanup", False):
        _HANDLERS[_type] = with_upload_cleanup(_HANDLERS[_type])
