"""VC1a: test del job study_note (Verifica e Chiedi) in mock, schema vincolato e DB."""
import pytest

from rt.core.models import DecisionLedger
from rt.llm.prompts import (
    STUDY_NOTE_CHIEDI_SYSTEM_PROMPT,
    STUDY_NOTE_VERIFICA_SYSTEM_PROMPT,
    StudyNoteChiediResponse,
    StudyNoteVerificaResponse,
)
from rt.pipeline.anchors import make_anchor
from rt.pipeline.ledger import write_ledger_file
from rt.pipeline.rewrite import load_draft, save_draft
from rt.pipeline.study_notes import run_study_note
from rt.services.jobs import DbJobQueue
from rt.services.study_notes_service import list_study_notes
from rt.services.worker import Worker
from tests.api_support import isolated_workspace
from tests.test_document_edit import _synthetic_lesson


def test_schema_vincolato_verifica():
    # Corretto senza correzione è valido
    v_ok = StudyNoteVerificaResponse(esito="corretto", spiegazione="Tutto giusto.")
    assert v_ok.esito == "corretto"
    assert v_ok.correzione is None

    # Errato senza correzione solleva errore di validazione
    with pytest.raises(ValueError, match="obbligatoria"):
        StudyNoteVerificaResponse(esito="errato", spiegazione="C'è un errore.")

    # Impreciso con correzione è valido
    v_imp = StudyNoteVerificaResponse(esito="impreciso", spiegazione="Manca precisione.", correzione="Versione precisa")
    assert v_imp.correzione == "Versione precisa"

    # Campi extra sono vietati (schema vincolato)
    with pytest.raises(ValueError):
        StudyNoteVerificaResponse.model_validate({
            "esito": "corretto", "spiegazione": "Ok", "extra_field": "vietato"
        })


def test_schema_vincolato_chiedi():
    c_ok = StudyNoteChiediResponse(spiegazione="Spiegazione chiara.")
    assert c_ok.spiegazione == "Spiegazione chiara."

    # Campi extra sono vietati
    with pytest.raises(ValueError):
        StudyNoteChiediResponse.model_validate({
            "spiegazione": "Spiegazione.", "extra": "non ammesso"
        })


def test_study_note_verifica_e_chiedi_mock(tmp_path, monkeypatch, rt_db):
    text = "Il valore normale del pH arterioso è considerato tra 7,36 e 7,45."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    anchor = make_anchor(text, text.index("7,36 e 7,45"), text.index("7,36 e 7,45") + len("7,36 e 7,45")).model_dump()

    # 1. Verifica in mock (esito errato in presenza di parole che chiedono verifica errore)
    res_v = run_study_note(
        lesson_dir=lesson_dir,
        unit_id="1.1",
        kind="verifica",
        anchor=anchor,
        request="Questo valore è errato?",
        force_mock=True,
    )
    assert res_v["note_id"] > 0
    note_v = res_v["note"]
    assert note_v["kind"] == "verifica"
    assert note_v["unit_id"] == "1.1"
    assert note_v["response"]["esito"] == "errato"
    assert "7,36 e 7,45 [corretto]" in note_v["response"]["correzione"]
    assert note_v["applied_decision_id"] is None
    assert len(note_v["unit_fingerprint"]) == 64

    # 2. Chiedi in mock
    res_c = run_study_note(
        lesson_dir=lesson_dir,
        unit_id="1.1",
        kind="chiedi",
        anchor=anchor,
        request="Spiegami il significato fisiologico.",
        force_mock=True,
    )
    assert res_c["note_id"] > 0
    note_c = res_c["note"]
    assert note_c["kind"] == "chiedi"
    assert "spiegazione" in note_c["response"]

    # 3. Controllo nel DB
    notes = list_study_notes(note_v["lesson_id"])
    assert len(notes) == 2
    assert {n["kind"] for n in notes} == {"verifica", "chiedi"}


def test_study_note_prompt_order_and_context(tmp_path, monkeypatch, rt_db):
    text = "Regolazione omeostatica del pH corporeo."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    anchor = make_anchor(text, 0, len(text)).model_dump()

    recorded_calls = []

    def mock_call(self, **kwargs):
        recorded_calls.append(kwargs)
        return StudyNoteVerificaResponse(esito="corretto", spiegazione="Corretto.")

    monkeypatch.setattr("rt.llm.client.LLMClient.call_structured", mock_call)

    run_study_note(
        lesson_dir=lesson_dir,
        unit_id="1.1",
        kind="verifica",
        anchor=anchor,
        request="Richiesta specifica dello studente",
        force_mock=False,
    )

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    # Ordine dei pezzi:
    # 1. system_prompt fisso per strumento
    assert call["system_prompt"] == STUDY_NOTE_VERIFICA_SYSTEM_PROMPT
    # 2. prompt_prefix con contesto della lezione
    assert "CONTESTO DELLA LEZIONE:" in call["prompt_prefix"]
    # 3. prompt con Unità intera, poi Testo selezionato, poi Richiesta per ultima
    prompt = call["prompt"]
    idx_unit = prompt.index("UNITÀ 1.1")
    idx_quote = prompt.index("TESTO SELEZIONATO:")
    idx_req = prompt.index("RICHIESTA DELLO STUDENTE:")
    assert idx_unit < idx_quote < idx_req
    assert "Richiesta specifica dello studente" in prompt
    assert call["response_model"] is StudyNoteVerificaResponse
    assert call["job_name"] == "review"
    assert call["unit_id"] == "1.1"


def test_study_note_selection_changed_raises(tmp_path, monkeypatch, rt_db):
    text = "Testo originale che poi viene modificato."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    anchor = make_anchor(text, 0, len("Testo originale")).model_dump()

    # Modifichiamo la bozza
    draft = load_draft(lesson_dir)
    draft.units[0].content = "Altro testo completamente diverso."
    save_draft(draft, lesson_dir)

    with pytest.raises(ValueError, match="cambiato o non si ritrova"):
        run_study_note(
            lesson_dir=lesson_dir,
            unit_id="1.1",
            kind="verifica",
            anchor=anchor,
            force_mock=True,
        )


def test_study_note_job_worker_execution(tmp_path, monkeypatch, rt_db):
    text = "Equilibrio acido-base e sistemi tampone."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    # Ricava lesson_id dal DB
    from rt.db.models import Lesson
    from rt.db.session import read_scope
    from sqlalchemy import select
    with read_scope(rt_db) as session:
        lesson_row = session.scalar(select(Lesson).where(Lesson.path == lesson_dir))
        lesson_id = lesson_row.id

    anchor = make_anchor(text, 0, len("Equilibrio acido-base")).model_dump()

    queue = DbJobQueue(rt_db)
    job_id = queue.enqueue(
        "study_note",
        lesson_dir,
        payload={
            "lesson_id": lesson_id,
            "unit_id": "1.1",
            "kind": "verifica",
            "anchor": anchor,
            "request": "È corretto?",
            "options": {"mock": True},
        },
        created_by="test",
    )

    Worker(queue, worker_id="study-test").run_once()

    done = queue.get(job_id)
    assert done.state == "succeeded", done.error
    assert done.result["note_id"] > 0
    assert done.result["note"]["kind"] == "verifica"

    notes = list_study_notes(lesson_id)
    assert len(notes) == 1
    assert notes[0]["id"] == done.result["note_id"]
    assert notes[0]["applied_decision_id"] is None


def test_study_note_verifica_with_web_search(tmp_path, monkeypatch, rt_db):
    from unittest.mock import patch
    from rt.core.config import RTConfig
    from rt.core.searxng_client import WebSearchResult

    text = "Il valore normale del pH arterioso è considerato tra 7,36 e 7,45."
    lesson_dir = _synthetic_lesson(isolated_workspace(tmp_path, monkeypatch), {"1.1": text})
    write_ledger_file(DecisionLedger(schema_version="2.0"), lesson_dir)

    anchor = make_anchor(text, 0, len("Il valore")).model_dump()

    fake_cfg = RTConfig(contextual_web_search=True, searxng_base_url="http://fake-searxng:8080")
    fake_results = [
        WebSearchResult(title="Manuale MSD", url="https://msd.it/ph", content="pH arterioso"),
        WebSearchResult(title="Biochimica Clinica", url="https://biochimica.it/ph", content="equilibrio acido-base"),
    ]

    with patch("rt.core.config.load_config", return_value=fake_cfg), \
         patch("rt.core.searxng_client.search_web", return_value=fake_results) as mock_search:
        res = run_study_note(
            lesson_dir=lesson_dir,
            unit_id="1.1",
            kind="verifica",
            anchor=anchor,
            request="Verifica questo passaggio",
            force_mock=True,
        )
        assert mock_search.called
        assert res["note"]["response"]["sources"] == [
            {"title": "Manuale MSD", "url": "https://msd.it/ph"},
            {"title": "Biochimica Clinica", "url": "https://biochimica.it/ph"},
        ]
