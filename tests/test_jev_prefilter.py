"""
tests/test_jev_prefilter.py
Test per il pre-filtro Jev (System One di typesafe.ai) davanti alla critica scientifica LLM
(rt/pipeline/review.py). Tutto mockato su rt.pipeline.review.call_jev: nessuna chiamata HTTP
reale, indipendente dal trasporto usato in produzione.
"""

import os
import json
import pytest
from unittest.mock import patch

from rt.core.config import RTConfig, JevConfig
from rt.core.models import (
    ScienceType,
    ScienceSeverity,
    ScienceIssue,
    Draft,
    DraftUnit,
    ReviewDecision,
    DecisionLedger,
)
from rt.core.timestamp import format_timestamp
from rt.llm.jev_client import JevResponse, JevChoiceAnswer, JevNoulAnswer
from rt.llm.prompts import ScienceIssueList
from rt.pipeline.review import run_review
from rt.pipeline.ledger import apply_decisions_to_draft
from rt.pipeline.issue_review import _build_science_panel, _is_no_diff_issue_type
from rt.cli import main


def setup_mock_lesson(tmp_path, num_units: int = 2):
    lesson_dir = str(tmp_path)

    word_timestamps = []
    raw_segments = []
    for i in range(num_units):
        s_idx, e_idx = i * 5, (i + 1) * 5
        for _ in range(5):
            word_timestamps.append({"confidence": 0.95})
        raw_segments.append({"text": f"Raw seg {i+1}", "wordRange": {"startIndex": s_idx, "endIndexExclusive": e_idx}})

    with open(os.path.join(lesson_dir, "trascritto grezzo.json"), "w", encoding="utf-8") as f:
        json.dump({"wordTimestamps": word_timestamps, "transcriptSegments": raw_segments}, f)

    segments_data = {
        "schema_version": "1.0",
        "segments": [
            {
                "id": f"seg_{i+1:06d}",
                "index": i + 1,
                "start_seconds": float(i * 10),
                "end_seconds": float((i + 1) * 10),
                "start_formatted": format_timestamp(float(i * 10)),
                "end_formatted": format_timestamp(float((i + 1) * 10)),
                "text_raw": f"Raw seg {i+1}",
            }
            for i in range(num_units)
        ],
    }
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(segments_data, f)

    draft_data = {
        "schema_version": "1.0",
        "units": [
            {
                "unit_id": f"1.{i+1}",
                "title": f"Unità {i+1}",
                "start_segment_id": f"seg_{i+1:06d}",
                "end_segment_id": f"seg_{i+1:06d}",
                "source_segment_ids": [f"seg_{i+1:06d}"],
                "content": f"Contenuto unità {i+1}.",
            }
            for i in range(num_units)
        ],
    }
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)
    with open(os.path.join(lesson_dir, "_state", "info.yaml"), "w", encoding="utf-8") as f:
        f.write("current_state: REWRITE_COMPLETED\n")

    return lesson_dir


def _jev_cfg(**overrides) -> RTConfig:
    return RTConfig(jev=JevConfig(enabled=True, **overrides))


def _choice_response(choice: str, confidence: float) -> JevResponse:
    return JevResponse(
        model="typesafe/jev-1.13",
        answers={"correttezza": JevChoiceAnswer(choice=choice, probabilities={choice: confidence}, confidence=confidence)},
        usage={"input_tokens": 100, "output_tokens": 10, "cost": 0.00001},
    )


def _noul_response(probability: float) -> JevResponse:
    return JevResponse(
        model="typesafe/jev-1.13",
        answers={"unsupported_content": JevNoulAnswer(noul=probability)},
        usage={"input_tokens": 200, "output_tokens": 10, "cost": 0.00002},
    )


def _never_called_expensive_llm(*args, **kwargs):
    raise AssertionError("La chiamata LLM costosa (call_structured) non doveva avvenire per questa unità.")


def _empty_expensive_llm(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
    return ScienceIssueList(issues=[])


# ---------------------------------------------------------------------------
# Task A: skip vs escalation
# ---------------------------------------------------------------------------

def test_task_a_confident_corretta_skips_expensive_llm(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85)

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("corretta", 0.95)
        return _noul_response(0.1)

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=_never_called_expensive_llm):
        res = run_review(lesson_dir, force=True, force_mock=True)

    assert res["total_science_issues"] == 0


def test_task_a_confident_imprecisione_skips_expensive_llm(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85)

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("imprecisione", 0.9)
        return _noul_response(0.1)

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=_never_called_expensive_llm):
        res = run_review(lesson_dir, force=True, force_mock=True)

    assert res["total_science_issues"] == 0


def test_task_a_confident_errore_grave_escalates(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85)
    called = {"count": 0}

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("errore_grave", 0.95)
        return _noul_response(0.1)

    def mock_call_structured(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
        called["count"] += 1
        return ScienceIssueList(issues=[])

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        run_review(lesson_dir, force=True, force_mock=False)

    assert called["count"] == 1


def test_task_a_low_confidence_falls_through_conservatively(tmp_path):
    """Il test più importante: bassa confidenza, anche su 'corretta', deve SEMPRE
    ricadere verso l'LLM costoso, mai verso lo skip."""
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85)
    called = {"count": 0}

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("corretta", 0.5)  # sotto soglia
        return _noul_response(0.1)

    def mock_call_structured(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
        called["count"] += 1
        return ScienceIssueList(issues=[])

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        run_review(lesson_dir, force=True, force_mock=False)

    assert called["count"] == 1


def test_task_a_low_confidence_errore_grave_still_escalates(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85)
    called = {"count": 0}

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("errore_grave", 0.3)
        return _noul_response(0.1)

    def mock_call_structured(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
        called["count"] += 1
        return ScienceIssueList(issues=[])

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        run_review(lesson_dir, force=True, force_mock=False)

    assert called["count"] == 1


# ---------------------------------------------------------------------------
# Task B: creazione issue ERR_REWRITE_DRIFT
# ---------------------------------------------------------------------------

def test_task_b_high_confidence_drift_creates_issue(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85, task_b_fabrication_threshold=0.80)

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("errore_grave", 0.99)  # forza comunque l'escalation, non rilevante qui
        return _noul_response(0.95)

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=_empty_expensive_llm):
        res = run_review(lesson_dir, force=True, force_mock=False)

    assert res["rewrite_drift_issues"] == 1
    issues = json.load(open(os.path.join(lesson_dir, "_state", "science_issues.json"), encoding="utf-8"))
    drift = [i for i in issues if i["type"] == "ERR_REWRITE_DRIFT"]
    assert len(drift) == 1
    assert drift[0]["claim"] == "Contenuto unità 1."
    assert drift[0]["suggested_fix"] is None
    assert drift[0]["unit_id"] == "1.1"


def test_task_b_below_threshold_creates_no_issue(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85, task_b_fabrication_threshold=0.80)

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        if job_name == "jev_task_a":
            return _choice_response("corretta", 0.95)
        return _noul_response(0.4)

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=_never_called_expensive_llm):
        res = run_review(lesson_dir, force=True, force_mock=True)

    assert res["rewrite_drift_issues"] == 0


# ---------------------------------------------------------------------------
# Modalità ombra
# ---------------------------------------------------------------------------

def test_shadow_jev_leaves_behavior_unchanged_but_calls_jev(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg(task_a_skip_confidence_threshold=0.85, task_b_fabrication_threshold=0.80)
    jev_calls = []
    expensive_calls = {"count": 0}

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        jev_calls.append(job_name)
        if job_name == "jev_task_a":
            return _choice_response("corretta", 0.99)  # confidentemente skip-abile, se non fosse ombra
        return _noul_response(0.99)  # confidentemente drift, se non fosse ombra

    def mock_call_structured(prompt, system_prompt, response_model, job_name, unit_id, min_elapsed_seconds=5.0, lesson_dir=None):
        expensive_calls["count"] += 1
        return ScienceIssueList(issues=[])

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=mock_call_structured):
        res = run_review(lesson_dir, force=True, force_mock=False, shadow_jev=True)

    # Jev è stato interrogato (loggato)...
    assert "jev_task_a" in jev_calls
    assert "jev_task_b" in jev_calls
    # ...ma il comportamento resta identico a Jev disattivato: LLM chiamato, nessun drift creato.
    assert expensive_calls["count"] == 1
    assert res["rewrite_drift_issues"] == 0


# ---------------------------------------------------------------------------
# jev.enabled=False (default): nessuna regressione per installazioni esistenti
# ---------------------------------------------------------------------------

def test_jev_disabled_makes_zero_jev_calls(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = RTConfig()  # jev.enabled default = False
    assert cfg.jev.enabled is False

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev") as mock_jev, \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=_empty_expensive_llm):
        run_review(lesson_dir, force=True, force_mock=False)

    mock_jev.assert_not_called()


# ---------------------------------------------------------------------------
# I due task ricevono state genuinamente diversi
# ---------------------------------------------------------------------------

def test_task_a_never_sees_raw_transcript(tmp_path):
    lesson_dir = setup_mock_lesson(tmp_path, num_units=1)
    cfg = _jev_cfg()
    states_by_job = {}

    def fake_call_jev(state, questions, *, job_name, **kwargs):
        states_by_job[job_name] = state
        if job_name == "jev_task_a":
            return _choice_response("corretta", 0.99)
        return _noul_response(0.1)

    with patch("rt.pipeline.review.load_config", return_value=cfg), \
         patch("rt.pipeline.review.call_jev", side_effect=fake_call_jev), \
         patch("rt.llm.client.LLMClient.call_structured", side_effect=_never_called_expensive_llm):
        run_review(lesson_dir, force=True, force_mock=True)

    assert states_by_job["jev_task_a"] == "Contenuto unità 1."
    assert "Raw seg 1" not in states_by_job["jev_task_a"]
    assert "Raw seg 1" in states_by_job["jev_task_b"]
    assert "Contenuto unità 1." in states_by_job["jev_task_b"]


# ---------------------------------------------------------------------------
# Rendering della card per ERR_REWRITE_DRIFT
# ---------------------------------------------------------------------------

def test_rewrite_drift_issue_renders_no_diff_branch():
    unit = DraftUnit(
        unit_id="1.1",
        title="Titolo Unità",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        content="Testo rielaborato dell'unità che potrebbe contenere un'invenzione.",
    )
    iss = ScienceIssue(
        id="sci_jevdrift_1.1",
        type=ScienceType.ERR_REWRITE_DRIFT,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        segment_id=None,
        claim=unit.content,
        reason="Il modello di pre-screening Jev ha rilevato con probabilità 0.95 ...",
        suggested_fix=None,
        diplomatic_question=None,
        status="pending",
    )
    assert _is_no_diff_issue_type(iss) is True

    panel = _build_science_panel(
        idx=0, total_count=1, iss=iss, tc="N/D",
        sci_unit_info=f"{unit.unit_id} - {unit.title}", sci_unit=unit,
        decisions_map={}, last_status=None,
    )
    rendered = panel.renderable.plain
    assert "DERIVA RIELABORAZIONE" in rendered
    assert "Il modello di pre-screening Jev" in rendered
    assert "0.95" in rendered
    # Nessun blocco diff rosso/verde: niente prefisso "+ " di correzione, dato che
    # suggested_fix è None per questo tipo di issue.
    assert "\n+ " not in rendered


# ---------------------------------------------------------------------------
# apply_decisions_to_draft per ERR_REWRITE_DRIFT
# ---------------------------------------------------------------------------

def test_apply_decisions_to_draft_err_rewrite_drift():
    draft = Draft(
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Titolo Unità",
                start_segment_id="seg_000001",
                end_segment_id="seg_000001",
                source_segment_ids=["seg_000001"],
                content="Testo rielaborato originale.",
            )
        ]
    )
    issue = ScienceIssue(
        id="sci_000001",
        type=ScienceType.ERR_REWRITE_DRIFT,
        severity=ScienceSeverity.HIGH,
        unit_id="1.1",
        segment_id=None,
        claim="Testo rielaborato originale.",
        reason="Possibile invenzione rilevata da Jev.",
        status="pending",
    )

    # "accettato" (dismiss): nessuna modifica al contenuto
    ledger_accepted = DecisionLedger(decisions=[
        ReviewDecision(issue_id="sci_000001", decision="accepted", resolved_text="Testo rielaborato originale.")
    ])
    res_accepted = apply_decisions_to_draft(draft, ledger_accepted, [issue])
    assert res_accepted.units[0].content == "Testo rielaborato originale."

    # "modificato": sostituzione integrale del contenuto dell'unità
    ledger_edited = DecisionLedger(decisions=[
        ReviewDecision(issue_id="sci_000001", decision="edited", resolved_text="Testo corretto dopo riascolto audio.")
    ])
    res_edited = apply_decisions_to_draft(draft, ledger_edited, [issue])
    assert res_edited.units[0].content == "Testo corretto dopo riascolto audio."


# ---------------------------------------------------------------------------
# CLI: --shadow-jev
# ---------------------------------------------------------------------------

def test_cli_review_shadow_jev_flag():
    with patch("rt.cli.run_review") as mock_run_review, patch("rt.cli.run_interactive_review"), \
         patch("sys.argv", ["rt", "review", "/path/to/lesson", "--shadow-jev", "--mock"]):
        mock_run_review.return_value = {"status": "ok", "skipped": True}
        try:
            main()
        except SystemExit:
            pass
        mock_run_review.assert_called_once()
        _, kwargs = mock_run_review.call_args
        assert kwargs.get("shadow_jev") is True


def test_cli_review_without_shadow_jev_defaults_false():
    with patch("rt.cli.run_review") as mock_run_review, patch("rt.cli.run_interactive_review"), \
         patch("sys.argv", ["rt", "review", "/path/to/lesson", "--mock"]):
        mock_run_review.return_value = {"status": "ok", "skipped": True}
        try:
            main()
        except SystemExit:
            pass
        mock_run_review.assert_called_once()
        _, kwargs = mock_run_review.call_args
        assert kwargs.get("shadow_jev") is False
