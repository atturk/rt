"""Note dello Studio (Verifica e Chiedi, 4.2.4): gestione DB e logica di business."""
from typing import Any, Optional
from sqlalchemy import delete, select

from rt.core.lesson_lock import lesson_lock
from rt.core.models import Anchor, ScienceIssue, ScienceSeverity, ScienceType
from rt.db.engine import get_database
from rt.db.models import ReviewDecision, StudyNote
from rt.db.session import read_scope, session_scope
from rt.pipeline.anchors import locate, make_anchor
from rt.pipeline.ledger import load_resolved_draft
from rt.pipeline.review import load_science_issues, save_science_issues
from rt.services.errors import Conflict, Invalid, NotFound
from rt.services.review_service import record_review_decision, undo_last_decision


def _row(n: StudyNote) -> dict[str, Any]:
    from rt.services.previous_study import previous_for_lesson
    from rt.core.markdown_render import render_markdown
    response = n.response or {}
    return {
        "precedente": previous_for_lesson(n.lesson_id, n.unit_id, n.created_at),
        "id": n.id,
        "lesson_id": n.lesson_id,
        "unit_id": n.unit_id,
        "kind": n.kind,
        "anchor": n.anchor,
        "unit_fingerprint": n.unit_fingerprint,
        "request": n.request,
        "response": n.response,
        "spiegazione_html": render_markdown(str(response.get('spiegazione') or '')),
        "correzione_html": render_markdown(str(response.get('correzione') or '')),
        "model": n.model,
        "cost": n.cost,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "applied_decision_id": n.applied_decision_id,
    }


def list_study_notes(lesson_id: int, unit_id: Optional[str] = None) -> list[dict[str, Any]]:
    with read_scope(get_database()) as session:
        query = select(StudyNote).where(StudyNote.lesson_id == lesson_id)
        if unit_id is not None:
            query = query.where(StudyNote.unit_id == unit_id)
        return [_row(n) for n in session.scalars(query.order_by(StudyNote.id.desc()))]


def get_study_note(lesson_id: int, note_id: int) -> dict[str, Any]:
    with read_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("study_note_not_found", "Nota dello studio non trovata.")
        return _row(row)


def add_study_note(
    lesson_id: int,
    unit_id: str,
    kind: str,
    anchor: dict[str, Any],
    unit_fingerprint: str = "",
    request: str = "",
    response: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
    cost: Optional[float] = None,
) -> dict[str, Any]:
    with session_scope(get_database()) as session:
        row = StudyNote(
            lesson_id=lesson_id,
            unit_id=unit_id,
            kind=kind,
            anchor=anchor,
            unit_fingerprint=unit_fingerprint,
            request=request,
            response=response or {},
            model=model,
            cost=cost,
        )
        session.add(row)
        session.flush()
        return _row(row)


def delete_study_note(lesson_id: int, note_id: int) -> None:
    with session_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("study_note_not_found", "Nota dello studio non trovata.")
        session.delete(row)


def update_study_note_applied(lesson_id: int, note_id: int, decision_id: Optional[int]) -> dict[str, Any]:
    with session_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is None or row.lesson_id != lesson_id:
            raise NotFound("study_note_not_found", "Nota dello studio non trovata.")
        row.applied_decision_id = decision_id
        session.flush()
        return _row(row)


def update_study_note_unit(lesson_id: int, note_id: int, new_unit_id: str) -> None:
    with session_scope(get_database()) as session:
        row = session.get(StudyNote, note_id)
        if row is not None and row.lesson_id == lesson_id:
            row.unit_id = new_unit_id


def decorate_study_note(note: dict[str, Any], lesson_dir: str, lesson_id: int) -> dict[str, Any]:
    """Ritrova il passaggio nel testo risolto e ne determina lo stato dell'ancora."""
    draft = load_resolved_draft(lesson_dir)
    anchor_obj = Anchor.model_validate(note["anchor"])
    target_unit = next((u for u in draft.units if u.unit_id == note["unit_id"]), None)

    located = locate(anchor_obj, target_unit.content) if target_unit else None
    if located:
        exact = located.exact and target_unit.content[located.start:located.end] == anchor_obj.quote
        state = "trovata" if exact else "cambiata"
        current_quote = target_unit.content[located.start:located.end]
    else:
        # Cerca nelle altre unità della lezione
        for other in draft.units:
            if target_unit and other.unit_id == target_unit.unit_id:
                continue
            other_located = locate(anchor_obj, other.content)
            if other_located:
                if note["unit_id"] != other.unit_id:
                    update_study_note_unit(lesson_id, note["id"], other.unit_id)
                    note["unit_id"] = other.unit_id
                exact = other_located.exact and other.content[other_located.start:other_located.end] == anchor_obj.quote
                state = "trovata" if exact else "cambiata"
                current_quote = other.content[other_located.start:other_located.end]
                break
        else:
            state = "non_ritrovata"
            current_quote = None

    issue_id = None
    if note.get("applied_decision_id"):
        with read_scope(get_database()) as session:
            dec_row = session.get(ReviewDecision, note["applied_decision_id"])
            if dec_row is not None and dec_row.reverted_at is None:
                issue_id = dec_row.issue_id
            else:
                note["applied_decision_id"] = None

    note["anchor_state"] = state
    note["current_quote"] = current_quote
    note["issue_id"] = issue_id
    return note


def apply_study_note(lesson_dir: str, lesson_id: int, note_id: int) -> dict[str, Any]:
    """Applica la correzione di una verifica registrando un'issue e una decisione nel ledger."""
    with lesson_lock(lesson_dir):
        note = get_study_note(lesson_id, note_id)
        if note["kind"] != "verifica":
            raise Invalid("invalid_note_type", "Solo le verifiche possono essere applicate.")

        fix = (note.get("response") or {}).get("correzione")
        if not fix or not fix.strip():
            raise Invalid("no_fix_available", "Nessuna correzione proposta per questa verifica.")

        if note.get("applied_decision_id"):
            with read_scope(get_database()) as session:
                dec_row = session.get(ReviewDecision, note["applied_decision_id"])
                if dec_row is not None and dec_row.reverted_at is None:
                    raise Conflict("already_applied", "Questa correzione è già stata applicata.")

        draft = load_resolved_draft(lesson_dir)
        unit = next((u for u in draft.units if u.unit_id == note["unit_id"]), None)
        if unit is None:
            raise NotFound("unit_not_found", f"Unità {note['unit_id']} non trovata nella bozza.")

        anchor_obj = Anchor.model_validate(note["anchor"])
        located = locate(anchor_obj, unit.content)
        if not located or unit.content[located.start:located.end] != anchor_obj.quote:
            raise Conflict("passage_changed", "Il passaggio è cambiato o non si ritrova uguale: la correzione non si può applicare.")

        exact_anchor = make_anchor(unit.content, located.start, located.end)

        # Crea un'issue con origin 'studio'
        prior_issues = list(load_science_issues(lesson_dir))
        nums = [int(i.id[4:]) for i in prior_issues if i.id.startswith("sci_") and i.id[4:].isdigit()]
        seq = (max(nums) + 1) if nums else 1
        issue_id = f"sci_{seq:06d}"

        issue = ScienceIssue(
            id=issue_id,
            type=ScienceType.ERR_CONCETTUALE,
            severity=ScienceSeverity.MEDIUM,
            unit_id=unit.unit_id,
            claim=exact_anchor.quote,
            reason=(note.get("response") or {}).get("spiegazione") or "Correzione da Verifica nello Studio.",
            suggested_fix=fix,
            anchor=exact_anchor,
            origin="studio",
            status="pending",
        )
        prior_issues.append(issue)
        save_science_issues(prior_issues, lesson_dir)

        # Registra la decisione accettata
        record_review_decision(
            lesson_dir=lesson_dir,
            issue_id=issue_id,
            decision="accepted",
            resolved_text=fix,
            channel="web",
            actor="user",
            notes="Applicata da Verifica nello Studio",
            validate=False,
        )

        with read_scope(get_database()) as session:
            dec_row = session.scalar(
                select(ReviewDecision)
                .where(ReviewDecision.lesson_id == lesson_id, ReviewDecision.issue_id == issue_id)
                .order_by(ReviewDecision.id.desc())
            )
            decision_id = dec_row.id if dec_row else None

        if decision_id:
            update_study_note_applied(lesson_id, note_id, decision_id)
            note["applied_decision_id"] = decision_id

        decorated = decorate_study_note(note, lesson_dir, lesson_id)
        return {
            "ok": True,
            "applied_decision_id": decision_id or 0,
            "issue_id": issue_id,
            "note": decorated,
        }


def undo_study_note(lesson_dir: str, lesson_id: int, note_id: int) -> dict[str, Any]:
    """Annulla la decisione precedentemente applicata dalla nota."""
    with lesson_lock(lesson_dir):
        note = get_study_note(lesson_id, note_id)
        if not note.get("applied_decision_id"):
            raise NotFound("not_applied", "Nessuna decisione applicata per questa nota.")

        with read_scope(get_database()) as session:
            dec_row = session.get(ReviewDecision, note["applied_decision_id"])
            if dec_row is None:
                raise NotFound("decision_not_found", "Decisione non trovata nel ledger.")
            issue_id = dec_row.issue_id

        undo_last_decision(lesson_dir, issue_id)
        update_study_note_applied(lesson_id, note_id, None)
        note["applied_decision_id"] = None
        return decorate_study_note(note, lesson_dir, lesson_id)
