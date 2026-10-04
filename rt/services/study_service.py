"""Studio (RT 4.2): le unità della lezione da leggere una alla volta, con il tratto d'audio e le
domande del pool che riguardano ciascuna. Lo usano la web app (GET /lessons/{id}/study) e la
mini app di Telegram (Leggi e ripeti)."""
from typing import Any, Dict, List


def unit_pending(pending, unit_id: str) -> Dict[str, int]:
    """Domande da porre dell'unità per tipo (le stesse di POST /recall/next?unit_id=)."""
    from rt.pipeline.recall import on_unit
    counts: Dict[str, int] = {}
    for q in pending:
        if on_unit(q, unit_id):
            counts[q.type.value] = counts.get(q.type.value, 0) + 1
    return counts


def study_units(lesson_dir: str) -> List[Dict[str, Any]]:
    """Unità del draft nell'ordine della lezione: titolo (con le modifiche dell'anteprima), testo
    Markdown, inizio e fine nell'audio (secondi, da segments.json) e domande da porre."""
    from rt.pipeline.document_edits import load_document_edits, unit_title
    from rt.pipeline.ledger import load_resolved_draft
    from rt.pipeline.recall import load_recall_bank
    from rt.services.lesson_service import document_sections
    pending = [q for q in load_recall_bank(lesson_dir).questions if q.status.value == "pending"]
    draft = load_resolved_draft(lesson_dir)
    sections = {s["unit_id"]: s for s in document_sections(lesson_dir)}
    edits = load_document_edits(lesson_dir)
    out = []
    for u in draft.units:
        s = sections.get(u.unit_id, {})
        out.append({"id": u.unit_id, "title": unit_title(edits, u.unit_id, u.title), "content": u.content,
                    "start": s.get("start_seconds"), "end": s.get("end_seconds"),
                    "pending": unit_pending(pending, u.unit_id)})
    return out


def study_lesson(lesson_id: int, lesson_dir: str) -> Dict[str, Any]:
    """La lezione per lo Studio della web app: unità con l'HTML del loro testo (sanificato, come
    il documento) e quante domande ciascuna ha da porre. Titolo e materia sono nell'elenco."""
    from rt.core.idempotency import PhaseStatus, check_phase_status
    from rt.core.markdown_render import markdown_parser
    from rt.services.lesson_service import lesson_audio_file
    ready = check_phase_status(lesson_dir, "rewrite")[0] == PhaseStatus.VALID
    md = markdown_parser()
    units = []
    if ready:
        for unit in study_units(lesson_dir):
            units.append({**{k: unit[k] for k in ("id", "title", "start", "end", "pending")},
                          "html": md.render(unit["content"]), "questions": sum(unit["pending"].values())})
    return {"id": lesson_id, "ready": ready, "has_audio": lesson_audio_file(lesson_dir) is not None, "units": units}
