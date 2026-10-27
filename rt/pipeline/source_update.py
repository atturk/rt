"""Preparazione incrementale richiesta dall'utente; gli originali restano intatti."""
import json
import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from contextlib import ExitStack
from uuid import uuid4

from rt.core.models import Segment
from rt.core.segments import (load_segments_json, parse_segments_from_json,
                              save_segments_json, export_normalized_transcript_md)
from rt.core.lesson_paths import lesson_path
from rt.core.sources import load_sources
from rt.core.timestamp import format_timestamp
from rt.core.state import update_info_yaml
from rt.storage import fs


def _read_state(lesson_dir):
    path = lesson_path(lesson_dir, "source_update.json")
    if not fs.isfile(path):
        return {"next_segment": 1, "sources": {}}
    with fs.open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _write_state(lesson_dir, state):
    path = lesson_path(lesson_dir, "source_update.json")
    with fs.open(path + ".tmp", "w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
    fs.replace(path + ".tmp", path)


def _duration(path):
    from rt.core.media_tools import audio_duration
    with fs.materialize(path) as real:
        return audio_duration(real)


def _transcribe(path, mock=False, ctx=None):
    """Riusa motore e comando dell'import, soltanto per il nuovo file."""
    from rt.core.config import load_config, load_env_file
    from rt.pipeline.setup import (find_macparakeet_binary, DEFAULT_MODEL,
                                   generate_deterministic_mock_asr, _run_transcribe_with_spinner)
    from rt.core.archive import cached_transcript, store_transcript, transcript_engine
    from rt.core.idempotency import compute_file_sha256
    sha, engine = compute_file_sha256(path), transcript_engine(mock)
    cached = cached_transcript(sha, engine)
    if cached:
        return [Segment.model_validate(item) for item in cached['segments']]
    stt = load_config().transcription
    with fs.materialize(path) as real, tempfile.TemporaryDirectory(prefix="rt-source-") as temp:
        if mock:
            raw_path, _ = generate_deterministic_mock_asr(real, "2026-01-01", "Appunti", "", temp)
        elif stt.engine in ("custom", "parakeet"):
            from rt.core.custom_stt import transcribe_custom
            from rt.core.onnx_stt import transcribe_onnx
            load_env_file()
            if stt.engine == "parakeet":
                from rt.core.stt_slot import local_transcription_slot
                with local_transcription_slot(
                    on_wait=(lambda msg: ctx.progress('prepare', message=msg)) if ctx else None,
                    cancel_token=ctx.cancel_token if ctx else None,
                ):
                    data = transcribe_onnx(real)
            else:
                data = transcribe_custom(real, stt.base_url, stt.model, stt.timeout_seconds)
            raw_path = os.path.join(temp, "raw.json")
            with open(raw_path, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
        else:
            binary = find_macparakeet_binary()
            if not binary:
                raise ValueError("macparakeet-cli non disponibile")
            from rt.core.stt_slot import local_transcription_slot
            with local_transcription_slot(
                on_wait=(lambda msg: ctx.progress('prepare', message=msg)) if ctx else None,
                cancel_token=ctx.cancel_token if ctx else None,
            ):
                result = _run_transcribe_with_spinner(
                    [binary, "transcribe", "--format", "json", "--no-diarize", "--output-dir", temp,
                     "--parakeet-model", DEFAULT_MODEL.removeprefix("parakeet-"), real], "Trascrizione della nuova fonte",
                    **({'on_message': lambda message: ctx.progress('prepare', message=message),
                        'cancel_token': ctx.cancel_token} if ctx else {}))
            candidates = [os.path.join(temp, f) for f in os.listdir(temp) if f.endswith(".json")]
            if result.returncode or not candidates:
                raise ValueError("Trascrizione della nuova fonte fallita")
            raw_path = candidates[0]
        segments = parse_segments_from_json(raw_path)
        store_transcript(sha, engine, {'segments': [s.model_dump() for s in segments],
                                     'duration': max((s.end_seconds for s in segments), default=0)})
        return segments


def sources_pending(lesson_dir):
    sources = load_sources(lesson_dir)
    state = _read_state(lesson_dir)
    used = state.get("used")
    if used is None:
        used = [s.id for s in sources if s.id == "src_000001"] if fs.isfile(lesson_path(lesson_dir, "segments.json")) else []
    return any(s.id not in used for s in sources)


def segment_source_ids(sources, state, primary):
    """La principale guida la scaletta; le fonti Integra vi partecipano sempre."""
    sources = [s for s in sources if not s.rimossa_il]
    primary_source = next((s for s in sources if s.id == primary), None)
    if primary_source is not None and (primary_source.tipo == "materiale" or (
            primary_source.tipo != "audio" and state.get("primary_explicit"))):
        selected = {primary}
    else:
        selected = {s.id for s in sources if s.tipo != "materiale"} or {primary}
    return selected | {s.id for s in sources if s.uso == "integra" and s.estrai != "solo_immagini"}


def reingest_availability(lesson_dir, sources=None):
    """Una cache non sostituisce gli originali necessari per ricominciare da capo."""
    sources = load_sources(lesson_dir) if sources is None else sources
    if not sources:
        return {"reingest_available": False, "reingest_reason": "La lezione non ha fonti registrate."}
    for source in sources:
        if not fs.isfile(os.path.join(lesson_dir, source.file)):
            label = {"audio": "Audio originale non disponibile", "materiale": "Documento originale non disponibile",
                     "appunti": "Appunti originali non disponibili"}[source.tipo]
            return {"reingest_available": False, "reingest_reason": label + "."}
    return {"reingest_available": True, "reingest_reason": None}


def prepare_source_update(lesson_dir, *, mock=False, ctx=None, reingest=False):
    from rt.core.materials import material_pages, _elapsed
    from rt.core.idempotency import compute_file_sha256
    from rt.services.context import RunContext, CancelToken
    started = time.monotonic()
    timing = {'transcription_seconds': 0.0, 'materials_seconds': 0.0, 'merge_seconds': 0.0,
              'audio': [], 'materials': [], 'parallel': False}
    sources = load_sources(lesson_dir)
    if not sources:
        raise ValueError("La lezione deve avere almeno una fonte")
    state = _read_state(lesson_dir)
    cache = state["sources"]
    segment_path = lesson_path(lesson_dir, "segments.json")
    previous = load_segments_json(segment_path).segments if fs.isfile(segment_path) else []
    state["next_segment"] = max(state["next_segment"], max((int(s.id[4:]) for s in previous), default=0) + 1)
    # Una sola volta: attribuisce alla prima fonte i segmenti storici già preparati.
    legacy = next((s for s in sources if s.id == "src_000001"), None)
    if legacy and legacy.id not in cache and previous and not reingest:
        originals = [s.model_copy(update={"source_file": legacy.id}) for s in previous]
        legacy_path = os.path.join(lesson_dir, legacy.file)
        # Audio storico mancante: la durata è la fine dell'ultimo segmento già preparato.
        duration = _duration(legacy_path) if fs.isfile(legacy_path) else previous[-1].end_seconds
        cache[legacy.id] = {"segments": [s.model_dump() for s in originals], "duration": duration}
    from rt.core.source_selection import selection
    primary = selection(lesson_dir)["principale"]
    in_segments = segment_source_ids(sources, state, primary)
    offset = 0.0
    ordered = []
    source_offsets = {}
    # Un solo hash per fonte, condiviso con material_pages tramite checked=True.
    for source in sources:
        if ctx:
            ctx.check_cancelled()
        path = os.path.join(lesson_dir, source.file)
        missing_but_prepared = source.id in cache and not fs.isfile(path)
        if source.impronta and not missing_but_prepared and compute_file_sha256(path) != source.impronta:
            raise ValueError("Una fonte originale è cambiata: aggiungila come nuova fonte")
    material_ctx = replace(ctx, cancel_token=CancelToken()) if ctx else RunContext(lesson_dir=lesson_dir, force_mock=mock)
    unsubscribe = ctx.cancel_token.on_cancel(material_ctx.cancel_token.cancel) if ctx else lambda: None
    audio_pending = [s for s in sources if s.tipo == 'audio' and s.id not in cache]
    materials_pending = [s for s in sources if s.tipo == 'materiale' and s.id not in cache]
    timing['parallel'] = bool(audio_pending and materials_pending)

    def read_material(source):
        material_ctx.check_cancelled()
        stats = {'file': os.path.basename(source.file)}
        with material_ctx.activate():
            pages = material_pages(lesson_dir, source, mock=mock, ctx=material_ctx,
                                   refresh=reingest, checked=True, timing=stats)
        timing['materials'].append(stats)
        timing['materials_seconds'] += stats['seconds']
        return pages

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='rt-materials') as pool:
        futures = {s.id: pool.submit(copy_context().run, read_material, s) for s in materials_pending}
        try:
            for source in sources:
                if ctx:
                    ctx.check_cancelled()
                path = os.path.join(lesson_dir, source.file)
                if source.id not in cache:
                    # Un errore nella lettura dei materiali si mostra subito, non a trascrizione finita.
                    for future in futures.values():
                        if future.done() and not future.cancelled() and future.exception() is not None:
                            future.result()
                    if source.tipo == "audio":
                        number = next(i for i, item in enumerate(audio_pending, 1) if item.id == source.id)
                        name = os.path.basename(source.file)
                        duration = _duration(path)
                        if ctx:
                            ctx.progress('prepare', message=f'Trascrizione di {name} ({number} di {len(audio_pending)})')
                            ctx.progress('prepare', message=f'Trascrizione di {name} (durata audio {_elapsed(duration)}): avvio del motore')
                        before = time.monotonic()
                        incoming = _transcribe(path, mock, **({'ctx': ctx} if ctx else {}))
                        seconds = time.monotonic() - before
                        timing['transcription_seconds'] += seconds
                        timing['audio'].append({'file': name, 'audio_seconds': duration, 'seconds': seconds})
                        if ctx:
                            ctx.progress('prepare', message=f'Trascrizione di {name}: finita in {_elapsed(seconds)}')
                    elif source.tipo == "materiale":
                        pages = futures[source.id].result()
                        incoming = [Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=.001,
                            start_formatted="00:00", end_formatted="00:00",
                            text_raw=page["testo"] or f"Pagina {page['numero']} senza testo leggibile",
                            flags=["materiale"]) for page in pages]
                        duration = 0.0
                    else:
                        with fs.open(path, encoding="utf-8") as stream:
                            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", stream.read()) if p.strip()]
                        if not paragraphs:
                            raise ValueError("Gli appunti sono vuoti")
                        incoming = [Segment(id="seg_000001", index=1, start_seconds=0, end_seconds=.001,
                                            start_formatted="00:00", end_formatted="00:00", text_raw=p,
                                            flags=["appunti"]) for p in paragraphs]
                        duration = 0.0
                    assigned = []
                    for segment in incoming:
                        assigned.append(segment.model_copy(update={"id": f"seg_{state['next_segment']:06d}", "source_file": source.id}))
                        state["next_segment"] += 1
                    cache[source.id] = {"segments": [s.model_dump() for s in assigned], "duration": duration}
                    if source.tipo == 'audio':
                        from rt.core.archive import transcript_engine
                        cache[source.id]['motore'] = transcript_engine(mock)
                    # Cache privata: una ripresa non trascrive nuovamente le parti già completate.
                    _write_state(lesson_dir, state)
                source_offsets[source.id] = offset
                offset += cache[source.id]["duration"]
        except BaseException:
            material_ctx.cancel_token.cancel()
            for future in futures.values():
                future.cancel()
            raise
        finally:
            unsubscribe()
    # Le fonti Integra aggiuntive seguono i segmenti ordinari. Gli offset restano
    # quelli dell'audio originale: pagine e appunti non consumano tempo.
    segment_sources = sorted((s for s in sources if s.id in in_segments),
                             key=lambda s: s.uso == "integra" and s.id != primary)
    for source in segment_sources:
        for item in cache[source.id]["segments"]:
            segment = Segment.model_validate(item)
            start = segment.start_seconds + source_offsets[source.id]
            end = segment.end_seconds + source_offsets[source.id]
            ordered.append(segment.model_copy(update={"index": len(ordered) + 1,
                           "start_seconds": start, "end_seconds": end,
                           "start_formatted": format_timestamp(start), "end_formatted": format_timestamp(end),
                           "integra": source.uso == "integra",
                           "fonte": os.path.basename(source.file) if source.uso == "integra" else None}))
    info_path = lesson_path(lesson_dir, "info.yaml")
    old_audio = ""
    if fs.isfile(info_path):
        from rt.core.state import read_info_yaml
        old_info = read_info_yaml(info_path)
        old_audio = old_info.get("file_audio") or ""
    audio_sources = [s for s in sources if s.tipo == "audio"]
    audio_file = ""
    if audio_sources:
        from rt.pipeline.setup import merge_audio_for_transcription
        if len(audio_sources) == 1:
            audio_file = audio_sources[0].file
        else:
            audio_file = "audio-" + uuid4().hex + ".m4a"
            if ctx:
                ctx.check_cancelled()
                ctx.progress('prepare', message='Unione degli audio')
            before = time.monotonic()
            with ExitStack() as stack:
                paths = [stack.enter_context(fs.materialize(os.path.join(lesson_dir, s.file))) for s in audio_sources]
                target = stack.enter_context(fs.external_output(os.path.join(lesson_dir, audio_file)))
                merge_audio_for_transcription(paths, target)
            timing['merge_seconds'] = time.monotonic() - before
            if ctx:
                ctx.progress('prepare', message=f"Unione degli audio: finita in {_elapsed(timing['merge_seconds'])}")
    save_segments_json(ordered, segment_path, lesson_id=os.path.basename(lesson_dir), audio_duration_seconds=offset)
    export_normalized_transcript_md(ordered, lesson_path(lesson_dir, "transcript_normalized.md"))
    update_info_yaml(info_path, {"file_audio": audio_file})
    if old_audio and old_audio != audio_file:
        # Gli audio uniti vecchi si cancellano solo quando nessuna fotografia (Annulla,
        # Versioni) li indica più: così ripristinare una versione ritrova il suo audio.
        from rt.services.audio_compaction import _orphan_candidates, referenced_audio_files
        referenced = referenced_audio_files(lesson_dir)
        for candidate in _orphan_candidates(lesson_dir):
            if os.path.normpath(candidate) not in referenced and fs.isfile(os.path.join(lesson_dir, candidate)):
                fs.remove(os.path.join(lesson_dir, candidate))
    state["used"] = [s.id for s in sources]
    _write_state(lesson_dir, state)
    from rt.core.source_selection import record_used_selection
    record_used_selection(lesson_dir)
    timing['total_seconds'] = time.monotonic() - started
    summary = (f"Preparazione finita in {_elapsed(timing['total_seconds'])}: "
               f"trascrizione {_elapsed(timing['transcription_seconds'])}, "
               f"lettura materiali {_elapsed(timing['materials_seconds'])}"
               f"{' (in parallelo)' if timing['parallel'] else ''}, "
               f"unione audio {_elapsed(timing['merge_seconds'])}")
    if ctx:
        ctx.progress('prepare', message=summary)
    # I tempi sono solo diagnostica: un errore di scrittura non fa fallire una preparazione finita.
    try:
        timing_path = lesson_path(lesson_dir, 'prepare_timing.json')
        with fs.open(timing_path + '.tmp', 'w', encoding='utf-8') as stream:
            json.dump(timing, stream, ensure_ascii=False, indent=2)
        fs.replace(timing_path + '.tmp', timing_path)
        from rt.services.logs_service import log_path
        worker_log = log_path('worker')
        os.makedirs(os.path.dirname(worker_log), exist_ok=True)
        from rt.core.log_stamp import stamp
        with open(worker_log, 'a', encoding='utf-8') as stream:
            stream.write(stamp() + json.dumps({'lesson': lesson_dir, 'message': summary, **timing}, ensure_ascii=False) + '\n')
    except OSError as exc:
        logging.getLogger(__name__).warning("Tempi della preparazione non salvati: %s", exc)
    return {"previous_segments": previous, "segments": ordered}


def changed_units(previous_outline, previous_segments, outline, segments):
    """Gli offset audio non cambiano il contenuto; confronta ID, testo e flag."""
    def signatures(structure, items):
        positions = {s.id: i for i, s in enumerate(items)}
        return {u.id: (u.title, [(s.id, s.text_raw, s.flags) for s in
                items[positions[u.start_segment_id]:positions[u.end_segment_id] + 1]])
                for macro in structure.macro_sections for u in macro.units}
    old = signatures(previous_outline, previous_segments) if previous_outline else {}
    return [uid for uid, signature in signatures(outline, segments).items() if old.get(uid) != signature]


def _check_extend_keeps_units(lesson_dir, outline):
    """Prima di scrivere qualsiasi cosa: Estendi non può svuotare un'unità esistente."""
    from rt.pipeline.validator import ValidationError
    segment_path = lesson_path(lesson_dir, "segments.json")
    previous = load_segments_json(segment_path).segments if fs.isfile(segment_path) else []
    cache = _read_state(lesson_dir)["sources"]
    surviving = set()
    for source in load_sources(lesson_dir):
        if source.id in cache:
            surviving.update(item["id"] for item in cache[source.id]["segments"])
        elif source.id == "src_000001":
            # Come in prepare_source_update: la prima volta i segmenti storici sono della fonte originale.
            surviving.update(s.id for s in previous)
    positions = {s.id: i for i, s in enumerate(previous)}
    for macro in outline.macro_sections:
        for unit in macro.units:
            if unit.start_segment_id not in positions or unit.end_segment_id not in positions:
                continue
            owned = previous[positions[unit.start_segment_id]:positions[unit.end_segment_id] + 1]
            if not any(s.id in surviving for s in owned):
                raise ValidationError("Una fonte rimossa svuota un'unità: usa Ricostruisci")


def run_source_update(lesson_dir, *, mode="extend", mock=False, ctx=None, reingest=False, with_review=False):
    from rt.pipeline.outline import load_outline
    from rt.core.update_history import begin_update, finish_update, abort_update
    if mode not in ("extend", "rebuild"):
        raise ValueError("Modalità di aggiornamento non valida")
    if reingest:
        if mode != "rebuild":
            raise ValueError("Per rileggere le fonti usa Ricostruisci.")
        available = reingest_availability(lesson_dir)
        if not available["reingest_available"]:
            raise ValueError(available["reingest_reason"])
    from rt.core.source_selection import selection
    if mode == "extend" and selection(lesson_dir)["solo_ricostruzione"]:
        raise ValueError("Ordine, principale o uso Integra cambiati: usa Ricostruisci")
    old_outline = load_outline(lesson_dir) if fs.isfile(lesson_path(lesson_dir, "outline.json")) else None
    load_sources(lesson_dir)
    if mode == "extend" and old_outline:
        _check_extend_keeps_units(lesson_dir, old_outline)
    previously_used = _read_state(lesson_dir).get("used", [s.id for s in load_sources(lesson_dir) if s.id == "src_000001"])
    # Negli aggiornamenti normali una nuova conversione resta riutilizzabile dopo un errore.
    previous_snapshot = begin_update(lesson_dir, include_material_cache=reingest)
    try:
        if reingest:
            state = _read_state(lesson_dir)
            # Anche gli appunti hanno una cache: si rileggono tutti gli originali, senza riusare ID.
            state["sources"] = {}
            _write_state(lesson_dir, state)
        options = {"reingest": reingest, "with_review": with_review} if reingest or with_review else {}
        result = _run_source_update(lesson_dir, old_outline, mode=mode, mock=mock, ctx=ctx, **options)
        from rt.core.update_history import record_version
        summary = _read_state(lesson_dir)["ultimo_aggiornamento"]
        record_version(lesson_dir, mode,
            added=[s.id for s in load_sources(lesson_dir) if s.id not in previously_used],
            new=summary["unita_nuove"], changed=summary["unita_cambiate"])
    except BaseException:
        # Qualsiasi errore (anche annullamento) riporta la lezione com'era prima dell'aggiornamento:
        # fonti nuove ancora da usare e fotografia dell'aggiornamento precedente per Annulla.
        try:
            abort_update(lesson_dir, previous_snapshot)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Ripristino dopo aggiornamento fallito non riuscito")
        raise
    finish_update(lesson_dir, previous_snapshot)
    return result


def _run_source_update(lesson_dir, old_outline, *, mode, mock, ctx, reingest=False, with_review=False):
    from rt.pipeline.outline import load_outline, run_outline
    from rt.pipeline.outline_extension import extend_outline
    from rt.pipeline.rewrite import run_rewrite
    from rt.core.idempotency import compute_source_fingerprint, compute_file_sha256, record_phase_fingerprint
    from rt.core.state import transition_to, WorkflowState
    prepared = prepare_source_update(lesson_dir, mock=mock, ctx=ctx, **({"reingest": True} if reingest else {}))
    from rt.core.manifest import init_or_update_manifest, save_manifest
    from rt.core.state import read_info_yaml
    info = read_info_yaml(lesson_path(lesson_dir, "info.yaml"))
    source_state = _read_state(lesson_dir)
    duration = sum(source_state["sources"][s.id]["duration"] for s in load_sources(lesson_dir))
    manifest = init_or_update_manifest(lesson_dir, lesson_id=os.path.basename(lesson_dir),
                            date=info.get("data", ""), subject=info.get("materia", ""),
                            current_state=WorkflowState.PREPARED.value,
                            topics=info.get("argomenti", ""), segment_count=len(prepared["segments"]),
                            audio_file=info.get("file_audio"),
                            audio_duration_seconds=duration)
    manifest.audio_file = info.get("file_audio") or None
    manifest.audio_duration_seconds = duration or None
    save_manifest(manifest, lesson_dir)
    record_phase_fingerprint(lesson_dir, "prepare", compute_source_fingerprint(lesson_dir, "prepare"),
                             {"segments.json": compute_file_sha256(lesson_path(lesson_dir, "segments.json"))})
    transition_to(lesson_path(lesson_dir, "info.yaml"), WorkflowState.PREPARED, allow_force=True)
    if mode == "extend" and old_outline:
        extend_outline(lesson_dir, prepared["previous_segments"], mock=mock, ctx=ctx)
        record_phase_fingerprint(lesson_dir, "outline", compute_source_fingerprint(lesson_dir, "outline"),
                                 {"outline.json": compute_file_sha256(lesson_path(lesson_dir, "outline.json"))})
        transition_to(lesson_path(lesson_dir, "info.yaml"), WorkflowState.OUTLINE_VALIDATED, allow_force=True)
    else:
        run_outline(lesson_dir, force=True, force_mock=mock, ctx=ctx)
    # L'aggiornamento passa direttamente alla riscrittura, senza chiedere conferma:
    # l'approvazione evita che la scheda disattivata nasconda il documento.
    # Non risvegliare eventuali altri job in attesa sulla stessa lezione.
    from rt.services.outline_service import approve_outline
    approve_outline(lesson_dir, actor="source_update", channel="server", resume=False)
    outline = load_outline(lesson_dir)
    selected = changed_units(old_outline, prepared["previous_segments"], outline, prepared["segments"])
    result = run_rewrite(lesson_dir, force_mock=mock, ctx=ctx,
                         changed_unit_ids=selected if mode == "extend" else None, force=mode == "rebuild")
    if result["status"] != "draft_validated" or result.get("failed_units"):
        raise RuntimeError("Aggiornamento incompleto: la lezione è tornata com'era, puoi riprovare.")
    if reingest or with_review:
        from rt.pipeline.build import run_build, write_automatic_documents
        if with_review:
            from rt.pipeline.review import run_review
            from rt.services.pipeline_service import raise_if_incomplete
            from rt.pipeline.ledger import get_pending_issues
            review = run_review(lesson_dir, force=True, force_mock=mock, ctx=ctx)
            raise_if_incomplete("review", review)
            result["review"] = review
            _, pending = get_pending_issues(lesson_dir)
        else:
            pending = []
        if ctx:
            ctx.check_cancelled()
        # Le correzioni scientifiche non si approvano da sole: il documento resta un'anteprima.
        result["build"] = (write_automatic_documents(lesson_dir) if pending
                           else run_build(lesson_dir, force=True, ctx=ctx))
        result["pending_review"] = len(pending)
        if reingest and not pending:
            from rt.services.context import RunContext
            from rt.services.pipeline_service import automatic_enrichment
            result["enrichment"] = automatic_enrichment(
                lesson_dir, mock, ctx or RunContext(lesson_dir=lesson_dir, force_mock=mock))
    from rt.services.sources_view import record_update_summary
    record_update_summary(lesson_dir, mode, old_outline, outline, selected)
    from rt.core.source_selection import record_used_selection
    record_used_selection(lesson_dir)
    result["changed_units"] = selected
    return result
