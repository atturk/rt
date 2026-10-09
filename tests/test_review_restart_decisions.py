"""4.2.3b3.1: quando la review riparte da zero (testo cambiato dopo la revisione) le issue nuove
riprendevano i numeri da sci_000001 e le decisioni vecchie si attaccavano a issue diverse.
V1 conserva le decise e usa nuovi numeri per le nuove, senza trasferire correzioni ad altri tratti."""
from rt.core.idempotency import check_phase_status
from rt.pipeline.ledger import get_pending_issues, load_ledger, load_resolved_draft, record_decision
from rt.pipeline.review import merge_unit_findings, load_science_issues, run_review
from rt.pipeline.rewrite import load_draft, save_draft
from tests.test_force_review_ledger_purge import _setup_test_lesson


def _decide_all(lesson_dir):
    _, pending = get_pending_issues(lesson_dir)
    assert pending
    for issue in pending:
        record_decision(lesson_dir, issue.id, "edited", resolved_text="TESTO INTERO SOSTITUITO")
    return pending


def test_review_restarted_from_scratch_keeps_old_decisions(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)
    assert run_review(lesson_dir, force=True, force_mock=True)["status"] == "review_completed"
    decided = {i.id for i in _decide_all(lesson_dir)}
    record_decision(lesson_dir, "custom_000001", "accepted", resolved_text="x")

    draft = load_draft(lesson_dir)
    # Tutti i claim sono cambiati: nessuna decisione deve passare a issue diverse.
    draft.units[0].content = "VERSIONE NUOVA: PROTEINE FIBROSE RESISTENTI."
    save_draft(draft, lesson_dir)
    assert check_phase_status(lesson_dir, "review")[0].name in ("STALE", "INVALID")

    result = run_review(lesson_dir, force_mock=True)
    assert result["action"] == "RUN" and result["status"] == "review_completed"
    _, pending = get_pending_issues(lesson_dir)
    assert pending and len(pending) == len(load_science_issues(lesson_dir))
    ids = {d.issue_id for d in load_ledger(lesson_dir).decisions}
    assert ids == decided | {"custom_000001"}
    # nessuna "modificata" vecchia sostituisce il testo di un'unità (caso reale: 2.2 ridotta a una frase)
    resolved = load_resolved_draft(lesson_dir)
    assert [u.content for u in resolved.units] == [u.content for u in load_draft(lesson_dir).units]


def _identity(issue):
    return (issue.unit_id, issue.type, issue.segment_id, " ".join(issue.claim.split()))


def test_new_findings_do_not_reuse_decided_ids(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)
    run_review(lesson_dir, force=True, force_mock=True)
    issues = load_science_issues(lesson_dir)
    _decide_all(lesson_dir)
    before = {i.id:_identity(i) for i in issues}
    # I numeri prodotti dal modello non determinano l'identità delle issue.
    shifted = [i.model_copy(update={"id":f"sci_{n:06d}"}) for n,i in enumerate(issues[1:], start=1)]
    combined, orphaned, _ = merge_unit_findings(lesson_dir, issues, shifted,
                            load_resolved_draft(lesson_dir).units, {i.unit_id for i in issues})
    assert orphaned == []
    assert {i.id for i in shifted}.isdisjoint(before)
    assert {i.id:_identity(i) for i in combined if i.id in before} == before
    assert {d.issue_id for d in load_ledger(lesson_dir).decisions} == set(before)


def test_manual_edit_in_preview_keeps_review_and_decisions(tmp_path):
    """4.2.3b3.2: una correzione a mano nell'anteprima (es. per chiudere un'issue) rendeva la
    review STALE e "Riprendi la pipeline" la rifaceva da zero, perdendo le decisioni."""
    from rt.core.idempotency import check_phase_status
    from rt.services.document_edit_service import save_document_edit
    from rt.services.lesson_service import load_markdown_preview
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)
    run_review(lesson_dir, force=True, force_mock=True)
    decided = {i.id for i in _decide_all(lesson_dir)}
    issues = load_science_issues(lesson_dir)

    unit = load_resolved_draft(lesson_dir).units[0]
    sentence = unit.content.strip().split("\n")[0].strip()
    markdown = load_markdown_preview(lesson_dir)
    assert sentence in markdown
    assert save_document_edit(lesson_dir, markdown.replace(sentence, sentence + " Aggiunta a mano.", 1))["units_changed"] == [unit.unit_id]
    assert check_phase_status(lesson_dir, "review")[0].name == "STALE"

    result = run_review(lesson_dir, force_mock=True)
    assert result["action"] == "SKIP"
    assert check_phase_status(lesson_dir, "review")[0].name == "VALID"
    assert [i.model_dump() for i in load_science_issues(lesson_dir)] == [i.model_dump() for i in issues]
    assert {d.issue_id for d in load_ledger(lesson_dir).decisions} == decided
    # il testo scritto a mano resta, le decisioni non lo sovrascrivono
    assert "Aggiunta a mano." in load_resolved_draft(lesson_dir).units[0].content
