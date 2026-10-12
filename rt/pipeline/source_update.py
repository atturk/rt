"""Preparazione incrementale richiesta dall'utente; gli originali restano intatti."""
import json
import os
import re
import subprocess
import tempfile
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
    with fs.materialize(path) as real:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", real],
                                capture_output=True, text=True, check=True, timeout=60)
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError("Audio senza durata valida")
    return duration


def _transcribe(path, mock=False):
    """Riusa motore e comando dell'import, soltanto per il nuovo file."""
    from rt.core.config import load_config, load_env_file
    from rt.pipeline.setup import (find_macparakeet_binary, DEFAULT_MODEL,
                                   generate_deterministic_mock_asr, _run_transcribe_with_spinner)
    stt = load_config().transcription
    with fs.materialize(path) as real, tempfile.TemporaryDirectory(prefix="rt-source-") as temp:
        if mock:
            raw_path, _ = generate_deterministic_mock_asr(real, "2026-01-01", "Appunti", "", temp)
        elif stt.engine == "custom":
            from rt.core.custom_stt import transcribe_custom
            load_env_file()
            data = transcribe_custom(real, stt.base_url, stt.model, stt.timeout_seconds)
            raw_path = os.path.join(temp, "raw.json")
            with open(raw_path, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
        else:
            binary = find_macparakeet_binary()
            if not binary:
                raise ValueError("macparakeet-cli non disponibile")
            result = _run_transcribe_with_spinner(
                [binary, "transcribe", "--format", "json", "--no-diarize", "--output-dir", temp,
                 "--parakeet-model", DEFAULT_MODEL.removeprefix("parakeet-"), real], "Trascrizione della nuova fonte")
            candidates = [os.path.join(temp, f) for f in os.listdir(temp) if f.endswith(".json")]
            if result.returncode or not candidates:
                raise ValueError("Trascrizione della nuova fonte fallita")
            raw_path = candidates[0]
        return parse_segments_from_json(raw_path)


def sources_pending(lesson_dir):
    sources = load_sources(lesson_dir)
    state = _read_state(lesson_dir)
    used = state.get("used")
    if used is None:
        used = [s.id for s in sources if s.id == "src_000001"] if fs.isfile(lesson_path(lesson_dir, "segments.json")) else []
    return used != [s.id for s in sources]


def prepare_source_update(lesson_dir, *, mock=False, ctx=None):
    sources = load_sources(lesson_dir)
    if not sources:
        raise ValueError("La lezione deve avere almeno una fonte")
    if any(s.tipo == "materiale" for s in sources):
        raise ValueError("I materiali saranno disponibili nel prossimo lotto")
    state = _read_state(lesson_dir)
    cache = state["sources"]
    segment_path = lesson_path(lesson_dir, "segments.json")
    previous = load_segments_json(segment_path).segments if fs.isfile(segment_path) else []
    state["next_segment"] = max(state["next_segment"], max((int(s.id[4:]) for s in previous), default=0) + 1)
    # Una sola volta: attribuisce alla prima fonte i segmenti storici già preparati.
    legacy = next((s for s in sources if s.id == "src_000001"), None)
    if legacy and legacy.id not in cache and previous:
        originals = [s.model_copy(update={"source_file": legacy.id}) for s in previous]
        legacy_path = os.path.join(lesson_dir, legacy.file)
        # Audio storico mancante: la durata è la fine dell'ultimo segmento già preparato.
        duration = _duration(legacy_path) if fs.isfile(legacy_path) else previous[-1].end_seconds
        cache[legacy.id] = {"segments": [s.model_dump() for s in originals], "duration": duration}
    offset = 0.0
    ordered = []
    for source in sources:
        if ctx:
            ctx.check_cancelled()
        path = os.path.join(lesson_dir, source.file)
        from rt.core.idempotency import compute_file_sha256
        missing_but_prepared = source.id in cache and not fs.isfile(path)
        if source.impronta and not missing_but_prepared and compute_file_sha256(path) != source.impronta:
            raise ValueError("Una fonte originale è cambiata: aggiungila come nuova fonte")
        if source.id not in cache:
            if source.tipo == "audio":
                incoming = _transcribe(path, mock)
                duration = _duration(path)
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
            # Cache privata: una ripresa non trascrive nuovamente le parti già completate.
            _write_state(lesson_dir, state)
        for item in cache[source.id]["segments"]:
            segment = Segment.model_validate(item)
            start, end = segment.start_seconds + offset, segment.end_seconds + offset
            ordered.append(segment.model_copy(update={"index": len(ordered) + 1,
                           "start_seconds": start, "end_seconds": end,
                           "start_formatted": format_timestamp(start), "end_formatted": format_timestamp(end)}))
        offset += cache[source.id]["duration"]
    audio_sources = [s for s in sources if s.tipo == "audio"]
    audio_file = ""
    if audio_sources:
        from rt.pipeline.setup import merge_audio_for_transcription
        if len(audio_sources) == 1:
            audio_file = audio_sources[0].file
        else:
            audio_file = "audio-" + uuid4().hex + ".m4a"
            with ExitStack() as stack:
                paths = [stack.enter_context(fs.materialize(os.path.join(lesson_dir, s.file))) for s in audio_sources]
                target = stack.enter_context(fs.external_output(os.path.join(lesson_dir, audio_file)))
                merge_audio_for_transcription(paths, target)
    save_segments_json(ordered, segment_path, lesson_id=os.path.basename(lesson_dir), audio_duration_seconds=offset)
    export_normalized_transcript_md(ordered, lesson_path(lesson_dir, "transcript_normalized.md"))
    update_info_yaml(lesson_path(lesson_dir, "info.yaml"), {"file_audio": audio_file})
    state["used"] = [s.id for s in sources]
    _write_state(lesson_dir, state)
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


def run_source_update(lesson_dir, *, mode="extend", mock=False, ctx=None):
    from rt.pipeline.outline import load_outline
    from rt.core.update_history import begin_update, finish_update, abort_update
    if mode not in ("extend", "rebuild"):
        raise ValueError("Modalità di aggiornamento non valida")
    old_outline = load_outline(lesson_dir) if fs.isfile(lesson_path(lesson_dir, "outline.json")) else None
    load_sources(lesson_dir)
    if mode == "extend" and old_outline:
        _check_extend_keeps_units(lesson_dir, old_outline)
    previous_snapshot = begin_update(lesson_dir)
    try:
        result = _run_source_update(lesson_dir, old_outline, mode=mode, mock=mock, ctx=ctx)
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


def _run_source_update(lesson_dir, old_outline, *, mode, mock, ctx):
    from rt.pipeline.outline import load_outline, run_outline
    from rt.pipeline.outline_extension import extend_outline
    from rt.pipeline.rewrite import run_rewrite
    from rt.core.idempotency import compute_source_fingerprint, compute_file_sha256, record_phase_fingerprint
    from rt.core.state import transition_to, WorkflowState
    prepared = prepare_source_update(lesson_dir, mock=mock, ctx=ctx)
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
    outline = load_outline(lesson_dir)
    selected = changed_units(old_outline, prepared["previous_segments"], outline, prepared["segments"])
    result = run_rewrite(lesson_dir, force_mock=mock, ctx=ctx,
                         changed_unit_ids=selected if mode == "extend" else None, force=mode == "rebuild")
    if result["status"] != "draft_validated" or result.get("failed_units"):
        raise RuntimeError("Aggiornamento incompleto: la lezione è tornata com'era, puoi riprovare.")
    from rt.services.sources_view import record_update_summary
    record_update_summary(lesson_dir, mode, old_outline, outline, selected)
    result["changed_units"] = selected
    return result
