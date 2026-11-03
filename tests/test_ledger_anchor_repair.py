import json
import pytest

from rt.core.encoding import sanitize_llm_output
from rt.core.models import Anchor, DecisionLedger, ReviewDecision, Draft
from rt.pipeline.ledger import get_ledger_path, load_ledger, write_ledger_file
from rt.pipeline.rewrite import save_draft
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_ledger_quote_with_latex_and_tab_loads_identical_length(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    quote = "Formula: \\theta + \\frac{1}{2} e un\ttab"
    unit_content = f"Introduzione. {quote} Conclusione."
    lesson_dir = _synthetic_lesson(root, {"1.1": unit_content})

    start = unit_content.index(quote)
    end = start + len(quote)
    anchor = Anchor(quote=quote, start=start, end=end)
    decision = ReviewDecision(
        issue_id="sci_000001",
        unit_id="1.1",
        decision="accepted",
        resolved_text="corretto",
        anchor=anchor,
    )
    ledger = DecisionLedger(schema_version="2.0", decisions=[decision])
    write_ledger_file(ledger, lesson_dir)

    loaded = load_ledger(lesson_dir, strict=True)
    assert len(loaded.decisions) == 1
    loaded_quote = loaded.decisions[0].anchor.quote
    assert loaded_quote == quote
    assert len(loaded_quote) == len(quote)


def test_decision_with_incoherent_anchor_does_not_empty_ledger(tmp_path, monkeypatch, rt_db):
    root = isolated_workspace(tmp_path, monkeypatch)
    lesson_dir = _synthetic_lesson(root, {"1.1": "Testo unità 1"})

    # Scriviamo direttamente sul file JSON del ledger una decisione valida e una non valida
    path = get_ledger_path(lesson_dir)
    data = {
        "schema_version": "2.0",
        "decisions": [
            {
                "issue_id": "sci_000001",
                "unit_id": "1.1",
                "decision": "accepted",
                "resolved_text": "ok",
                "anchor": {
                    "quote": "Testo",
                    "start": 0,
                    "end": 5,
                },
            },
            {
                # Decisione rotta (manca issue_id obbligatorio)
                "unit_id": "1.1",
                "decision": "invalid_decision_type",
            },
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    loaded = load_ledger(lesson_dir, strict=False)
    # La decisione rotta viene scartata, ma quella valida resta
    assert len(loaded.decisions) == 1
    assert loaded.decisions[0].issue_id == "sci_000001"


def test_fake_rewrite_response_with_trm_repaired():
    fake_output = {
        "units": [
            {
                "unit_id": "1.1",
                "title": "Titolo",
                "content": "Valore ($	rm{RTPL}$) e formula $\\theta + \frac{1}{2}$",
            }
        ]
    }
    cleaned = sanitize_llm_output(fake_output)
    unit_content = cleaned["units"][0]["content"]
    assert "$\\mathrm{RTPL}$" in unit_content
    assert "\\frac{1}{2}" in unit_content


def test_broken_anchor_lesson_returns_200_on_study_notes(tmp_path, monkeypatch, rt_db, api_client):
    root = isolated_workspace(tmp_path, monkeypatch)
    text = "Il testo della lezione con formula e citazione."
    lesson_dir = _synthetic_lesson(root, {"1.1": text})

    # Ledger con ancora avente quote e span incoerenti (es. end - start != len(quote))
    path = get_ledger_path(lesson_dir)
    data = {
        "schema_version": "2.0",
        "decisions": [
            {
                "issue_id": "sci_000012",
                "unit_id": "1.1",
                "decision": "accepted",
                "resolved_text": "risolto",
                "anchor": {
                    "quote": "formula",
                    "start": 10,
                    "end": 50,  # 50 - 10 = 40 != len("formula") (7)
                },
            }
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    lid = api_client.get("/api/v1/lessons").json()[0]["id"]
    res = api_client.get(f"/api/v1/lessons/{lid}/study-notes")
    assert res.status_code == 200
