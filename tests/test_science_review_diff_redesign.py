"""
Test per Task 74 e Task 93: redesign della card di review scientifica (DiffView), bottoni discreti,
rimozione ridondanze e uscita senza attesa INVIO.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from rich.text import Text
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity, Draft, DraftUnit, SegmentsData, Segment
)
from rt.pipeline.issue_review import _build_diff_strings
from rt.tui.issue_review import _build_science_panel, IssueReviewApp
from rt.pipeline.ledger import load_ledger
from textual_diff_view import DiffView


def _sample_draft_unit():
    return DraftUnit(
        unit_id="U1",
        title="Introduzione alla Biochimica",
        content="Gli enzimi abbassano l'energia di attivazione accelerando la reazione.",
        start_segment_id="seg_000001",
        end_segment_id="seg_000001",
        source_segment_ids=["seg_000001"],
        key_concepts=[],
    )


def test_science_critic_diff_strings_building():
    sci_unit = _sample_draft_unit()
    iss = ScienceIssue(
        id="sci_001",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="abbassano l'energia di attivazione",
        reason="L'enzima stabilizza lo stato di transizione.",
        suggested_fix="riducono la barriera di energia libera",
    )

    code_orig, code_mod = _build_diff_strings(sci_unit, iss)
    assert code_orig == sci_unit.content
    assert code_mod == "Gli enzimi riducono la barriera di energia libera accelerando la reazione."


def test_science_critic_diff_strings_fallback_and_no_fix():
    sci_unit = _sample_draft_unit()
    iss_fallback = ScienceIssue(
        id="sci_002",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.MEDIUM,
        unit_id="U1",
        claim="claim inesistente",
        reason="critica",
        suggested_fix="correzione",
    )
    orig_fb, mod_fb = _build_diff_strings(sci_unit, iss_fallback)
    assert "claim inesistente" in orig_fb
    assert "correzione" in mod_fb

    iss_nofix = ScienceIssue(
        id="sci_003",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.LOW,
        unit_id="U1",
        claim="abbassano l'energia di attivazione",
        reason="critica",
        suggested_fix=None,
    )
    orig_nf, mod_nf = _build_diff_strings(sci_unit, iss_nofix)
    assert orig_nf == mod_nf == sci_unit.content


def test_science_critic_panel_no_header_or_legend():
    sci_unit = _sample_draft_unit()
    iss = ScienceIssue(
        id="sci_001",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="abbassano l'energia di attivazione",
        reason="L'enzima stabilizza lo stato di transizione.",
        suggested_fix="riducono la barriera di energia libera",
        diplomatic_question="Come possiamo chiarire questo punto?",
    )

    rendered_text: Text = _build_science_panel(
        idx=0,
        total_count=1,
        iss=iss,
        tc="01:23",
        sci_unit_info="U1 - Introduzione",
        sci_unit=sci_unit,
        decisions_map={},
    )
    plain = rendered_text.plain

    # Nessuna riga header duplicata [1/1] o ID
    assert "[1/1]" not in plain
    assert "SCIENCE CRITIC" not in plain
    # Nessuna legenda
    assert "🔴 = claim attuale" not in plain
    # Presenza di critica e domanda docente
    assert "L'enzima stabilizza lo stato di transizione." in plain
    assert "Come possiamo chiarire questo punto?" in plain


def test_asr_risk_visual_layout():
    sci_unit = _sample_draft_unit()
    iss = ScienceIssue(
        id="asr_001",
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.MEDIUM,
        unit_id="U1",
        claim="enzimi abbassano",
        reason="ASR incerto",
    )

    rendered_text = _build_science_panel(
        idx=0,
        total_count=1,
        iss=iss,
        tc="00:15",
        sci_unit_info="U1 - Introduzione",
        sci_unit=sci_unit,
        decisions_map={},
    )

    plain = rendered_text.plain
    assert "[1/1]" not in plain
    assert "⏱ Timecode (stima): 00:15" in plain
    assert "🎙️ Segmento raw sospetto: \"enzimi abbassano\"" in plain
    assert "ASR incerto" in plain


@pytest.mark.anyio
async def test_keybindings_and_actions_science_critic(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    iss1 = ScienceIssue(
        id="sci_1",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 1",
        reason="reason 1",
        suggested_fix="fix 1",
    )
    iss2 = ScienceIssue(
        id="sci_2",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 2",
        reason="reason 2",
        suggested_fix="fix 2",
    )

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss1, iss2])
    async with app.run_test() as pilot:
        # 1. 'a' accetta la correzione per sci_1
        await pilot.press("a")
        # 2. 'r' rifiuta la correzione per sci_2 (mantiene claim)
        await pilot.press("r")

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 2
    assert ledger.decisions[0].issue_id == "sci_1"
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[0].resolved_text == "fix 1"

    assert ledger.decisions[1].issue_id == "sci_2"
    assert ledger.decisions[1].decision == "rejected"
    assert ledger.decisions[1].resolved_text == "claim 2"


@pytest.mark.anyio
async def test_buttons_click_science_critic(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    iss1 = ScienceIssue(
        id="sci_btn_1",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 1",
        reason="reason 1",
        suggested_fix="fix 1",
    )
    iss2 = ScienceIssue(
        id="sci_btn_2",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.HIGH,
        unit_id="U1",
        claim="claim 2",
        reason="reason 2",
        suggested_fix="fix 2",
    )

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss1, iss2])
    async with app.run_test(size=(100, 35)) as pilot:
        # Verifica che DiffView sia montato
        dv = app.query_one("#diff-view", DiffView)
        assert dv.split is True

        # Click sul bottone Accetta
        await pilot.click("#btn-accept")
        await pilot.pause()
        assert app.idx == 1

        # Click sul bottone Indietro
        await pilot.click("#btn-back")
        await pilot.pause()
        assert app.idx == 0

        # Click sul bottone Salta
        await pilot.click("#btn-skip")
        await pilot.pause()
        assert app.idx == 1

        # Click sul bottone Rifiuta
        await pilot.click("#btn-reject")
        await pilot.pause()

    ledger = load_ledger(lesson_dir)
    assert any(d.issue_id == "sci_btn_2" and d.decision == "rejected" for d in ledger.decisions)


@pytest.mark.anyio
async def test_keybindings_and_actions_asr_risk(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[_sample_draft_unit()],
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    iss_asr = ScienceIssue(
        id="asr_1",
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.MEDIUM,
        unit_id="U1",
        claim="enzimi abbassano",
        reason="ASR incerto",
    )

    app = IssueReviewApp(lesson_dir=lesson_dir, to_review=[iss_asr])
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("a")
        await pilot.pause()

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "asr_1"
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[0].resolved_text == _sample_draft_unit().content


def test_run_cli_review_skips_input_prompt():
    from rt.tui.app import RTApp
    app = RTApp()
    with patch.object(app, "suspend"), \
         patch("builtins.input") as mock_input, \
         patch("subprocess.run") as mock_run, \
         patch("rt.telegram.daemon_status.get_rt_executable_path", return_value="/mock/bin/rt"):
        mock_run.return_value.returncode = 0
        app._run_cli(["review", "some_lesson"])
        mock_input.assert_not_called()

    # Per comandi diversi da review, l'attesa INVIO deve essere chiamata
    with patch.object(app, "suspend"), \
         patch("builtins.input") as mock_input, \
         patch("subprocess.run") as mock_run, \
         patch("rt.telegram.daemon_status.get_rt_executable_path", return_value="/mock/bin/rt"):
        mock_run.return_value.returncode = 0
        app._run_cli(["config"])
        mock_input.assert_called_once()

