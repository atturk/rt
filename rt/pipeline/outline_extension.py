"""Scaletta estesa: la struttura precedente è un vincolo, non un suggerimento."""
from rt.core.models import OutlineUnit
from rt.core.lesson_paths import lesson_path
from rt.core.segments import load_segments_json, segment_content
from rt.pipeline.outline import load_outline, save_outline, _generate_validated_outline
from rt.pipeline.validator import validate_outline, ValidationError
from rt.llm.client import LLMClient
from rt.llm.prompts import OUTLINE_SYSTEM_PROMPT, INTEGRA_OUTLINE_RULE
from rt.services.prompt_settings import effective_system


def validate_extension(candidate, previous, old_segments, current):
    report = validate_outline(candidate, current)
    if report["omitted_count"] or report["duplicate_count"]:
        raise ValidationError("Estendi deve coprire ogni segmento esattamente una volta")
    old_units = [u for m in previous.macro_sections for u in m.units]
    new_units = [u for m in candidate.macro_sections for u in m.units]
    old_ids = [u.id for u in old_units]
    if [u.id for u in new_units if u.id in old_ids] != old_ids:
        raise ValidationError("Le unità esistenti non possono essere eliminate o spostate: usa Ricostruisci")
    old_positions = {s.id: i for i, s in enumerate(old_segments)}
    current_positions = {s.id: i for i, s in enumerate(current.segments)}
    new_map = {u.id: u for u in new_units}
    surviving = set(current_positions)
    for old in old_units:
        new = new_map[old.id]
        if new.title != old.title:
            raise ValidationError("Il titolo di un'unità esistente è fisso")
        expected = {s.id for s in old_segments[old_positions[old.start_segment_id]:old_positions[old.end_segment_id] + 1]} & surviving
        actual = {s.id for s in current.segments[current_positions[new.start_segment_id]:current_positions[new.end_segment_id] + 1]}
        original = set(old_positions)
        if not expected or actual & original != expected:
            raise ValidationError("Non si possono spostare segmenti esistenti in altre unità: usa Ricostruisci")
    # Anche macrosezioni, ID e titoli restano fissi e mantengono le proprie unità.
    macros = {m.id: m for m in candidate.macro_sections}
    for old in previous.macro_sections:
        new = macros.get(old.id)
        if new is None or new.title != old.title or any(u.id not in {x.id for x in new.units} for u in old.units):
            raise ValidationError("Le macrosezioni esistenti sono fisse")
    return report


def _mock_extension(previous, old_segments, current):
    result = previous.model_copy(deep=True)
    positions = {s.id: i for i, s in enumerate(old_segments)}
    current_ids = {s.id for s in current.segments}
    owned = set()
    for macro in result.macro_sections:
        for unit in macro.units:
            kept = [s.id for s in old_segments[positions[unit.start_segment_id]:positions[unit.end_segment_id] + 1] if s.id in current_ids]
            if not kept:
                raise ValidationError("Una fonte rimossa svuota un'unità: usa Ricostruisci")
            unit.start_segment_id, unit.end_segment_id = kept[0], kept[-1]
            start = next(s.index for s in current.segments if s.id == kept[0])
            end = next(s.index for s in current.segments if s.id == kept[-1])
            owned.update(s.id for s in current.segments[start - 1:end])
    # I gruppi non coperti diventano nuove unità; non cambia mai un titolo esistente.
    groups = []
    for segment in current.segments:
        if segment.id in owned:
            continue
        if groups and groups[-1][-1].index + 1 == segment.index:
            groups[-1].append(segment)
        else:
            groups.append([segment])
    used = {u.id for m in result.macro_sections for u in m.units}
    for group in groups:
        macro = next((m for m in result.macro_sections if any(
            next(s.index for s in current.segments if s.id == u.end_segment_id) >= group[0].index for u in m.units)), result.macro_sections[-1])
        counter = 1
        while f"{macro.id}.{counter}" in used:
            counter += 1
        uid = f"{macro.id}.{counter}"
        used.add(uid)
        macro.units.append(OutlineUnit(id=uid, title="Nuova parte", start_segment_id=group[0].id, end_segment_id=group[-1].id))
        macro.units.sort(key=lambda u: next(s.index for s in current.segments if s.id == u.start_segment_id))
    return result


def extend_outline(lesson_dir, previous_segments, *, mock=False, ctx=None):
    previous = load_outline(lesson_dir)
    current = load_segments_json(lesson_path(lesson_dir, "segments.json"))
    old_ids = {s.id for s in previous_segments}
    prompt = (
        "Estendi la scaletta fissa: conserva ID, titoli, ordine, macrosezioni e appartenenza dei segmenti esistenti. "
        "Puoi aggiungere nuove unità o allungare le confinanti solo con segmenti nuovi. "
        "Copri tutti i segmenti esattamente una volta. Non spostare alcuna unità esistente.\n"
        + INTEGRA_OUTLINE_RULE + "\n"
        "SCALETTA FISSA:\n" + previous.model_dump_json() + "\n"
        "SEGMENTI NELL'ORDINE ATTUALE (testo solo dei nuovi):\n" + "\n".join(
            f"[{s.id}] " + (segment_content(s) if s.id not in old_ids else "(esistente, fisso)") for s in current.segments)
    )
    validator = lambda candidate: validate_extension(candidate, previous, previous_segments, current)
    if mock:
        candidate = _mock_extension(previous, previous_segments, current)
        report = validator(candidate)
    else:
        candidate, report = _generate_validated_outline(
            LLMClient(), effective_system("outline", OUTLINE_SYSTEM_PROMPT), [], prompt,
            current, lesson_dir, additional_validation=validator)
    save_outline(candidate, lesson_dir)
    return {"status": "outline_validated", "validation_report": report}
