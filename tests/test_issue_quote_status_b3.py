"""Stato del passaggio deciso dal server sul testo risolto dopo un salvataggio."""
import pytest
from rt.core.models import ScienceIssue
from rt.pipeline.anchors import make_anchor
from rt.pipeline.review import save_science_issues
from rt.services.review_service import issue_quote_status
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson, _preview


@pytest.fixture
def lesson(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    directory = _synthetic_lesson(root, {"1.1": "Il pH è 6. Nota prima. Nota dopo."})
    text = "Il pH è 6. Nota prima. Nota dopo."
    issue = ScienceIssue(id="sci_quote", type="ERR_CONCETTUALE", severity="high", unit_id="1.1",
        claim="Il pH è 6.", suggested_fix="Il pH è 7.", reason="Controlla il valore.", anchor=make_anchor(text, 0, 10))
    save_science_issues([issue], directory)
    return directory, issue


@pytest.mark.parametrize("old,new,status", [
    ("Il pH è 6.", "Passaggio riscritto.", "changed"),
    ("Il pH è 6.", "Il pH è 8.", "changed"),
    ("Nota dopo.", "Una nota diversa.", "found"),
])
def test_api_reports_quote_status_after_manual_save(lesson, api_client, old, new, status):
    directory, issue = lesson
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    path = f"/api/v1/lessons/{lid}"
    assert api_client.get(path + "/issues").json()["items"][0]["quote_status"] == "found"
    response = api_client.put(path + "/document/draft", json={"markdown": _preview(directory).replace(old, new)})
    assert response.status_code == 200, response.text
    item, = api_client.get(path + "/issues").json()["items"]
    assert item["issue"]["id"] == issue.id
    assert item["quote_status"] == status


def test_normalized_spacing_and_shifted_anchor_are_found(lesson):
    _, issue = lesson
    assert issue_quote_status(issue, "Aggiunta. Il pH è 6. Nota prima. Nota dopo.") == "found"
    assert issue_quote_status(issue, "Il pH  è 6. Nota prima. Nota dopo.") == "found"


def test_asr_advisory_stays_found_when_unit_text_changes(lesson):
    _, issue = lesson
    issue.type = "ERR_ASR_ST"
    assert issue_quote_status(issue, "Passaggio nuovo.") == "found"


def test_api_reports_changed_for_reconfirmation(lesson, api_client):
    from rt.services.review_service import record_review_decision
    directory, issue = lesson
    record_review_decision(directory, issue.id, "accepted", channel="api", validate=True)
    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    path = f"/api/v1/lessons/{lid}"
    from rt.pipeline.rewrite import load_draft, save_draft
    draft = load_draft(directory)
    draft.units[0].content = "Passaggio diverso dopo una rielaborazione."
    save_draft(draft, directory)
    # Una rielaborazione non ritrova la scelta precedente, che resta registrata.
    item, = api_client.get(path + "/issues?status=all").json()["items"]
    assert item["decision"]["decision"] == "accepted"
    assert item["needs_reconfirmation"]
    assert item["quote_status"] == "changed"
