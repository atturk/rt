"""Una decisione cambia il testo risolto ma non la bozza: l'unità resta verificata e una nuova
verifica non richiama il modello (regressione di V1e, golden audio_full)."""
from rt.pipeline.ledger import get_pending_issues, record_decision
from rt.pipeline.review import run_review
from rt.services.review_service import review_units
from tests.test_force_review_ledger_purge import _setup_test_lesson


def test_accepted_decisions_do_not_make_units_changed(tmp_path):
    lesson_dir = str(tmp_path)
    _setup_test_lesson(lesson_dir)
    run_review(lesson_dir, force=True, force_mock=True)
    _, pending = get_pending_issues(lesson_dir)
    assert pending
    for issue in pending:
        record_decision(lesson_dir, issue.id, "accepted", resolved_text="Testo corretto.")
    again = run_review(lesson_dir, force_mock=True)
    assert again["action"] == "SKIP", again
    assert get_pending_issues(lesson_dir)[1] == []
    assert all(row["state"] != "changed" for row in review_units(lesson_dir)), review_units(lesson_dir)
