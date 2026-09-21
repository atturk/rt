"""
Test per Task 74: redesign della card di review scientifica (diff-style) e ridenominazione tasti A/R/M/I.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from rich.text import Text
from rt.core.models import (
    ScienceIssue, ScienceType, ScienceSeverity, Draft, DraftUnit, SegmentsData, Segment
)
from rt.pipeline.issue_review import _build_science_panel, IssueReviewApp
from rt.pipeline.ledger import load_ledger


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


def test_science_critic_diff_rendering_with_spans():
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

    panel = _build_science_panel(
        idx=0,
        total_count=1,
        iss=iss,
        tc="01:23",
        sci_unit_info="U1 - Introduzione",
        sci_unit=sci_unit,
        decisions_map={},
    )

    rendered_text: Text = panel.renderable
    plain = rendered_text.plain

    # 1. Nessuna riga Timecode
    assert "Timecode" not in plain

    # 2. Presenza dei marcatori diff
    assert "- abbassano l'energia di attivazione" in plain
    assert "+ riducono la barriera di energia libera" in plain

    # 3. Verifica spans di stile (rosso per claim rimosso, verde per aggiunta)
    styles = [(span.style, plain[span.start:span.end]) for span in rendered_text.spans]
    has_red_prefix = any("red" in str(st) and "- " in txt for st, txt in styles)
    has_red_claim = any("red" in str(st) and "abbassano l'energia di attivazione" in txt for st, txt in styles)
    has_green_prefix = any("green" in str(st) and "+ " in txt for st, txt in styles)
    has_green_fix = any("green" in str(st) and "riducono la barriera di energia libera" in txt for st, txt in styles)

    assert has_red_prefix or has_red_claim
    assert has_green_prefix or has_green_fix

    # 4. Legenda con solo emoji
    assert "🔴 = claim attuale · 🟢 = correzione suggerita" in plain
    assert "rosso" not in plain
    assert "verde" not in plain


def test_science_critic_no_suggested_fix_omits_green_and_legend():
    sci_unit = _sample_draft_unit()
    iss = ScienceIssue(
        id="sci_002",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.LOW,
        unit_id="U1",
        claim="abbassano l'energia di attivazione",
        reason="Verificare se il concetto è chiaro.",
        suggested_fix=None,
    )

    panel = _build_science_panel(
        idx=0,
        total_count=1,
        iss=iss,
        tc="01:23",
        sci_unit_info="U1 - Introduzione",
        sci_unit=sci_unit,
        decisions_map={},
    )

    plain = panel.renderable.plain
    assert "+ " not in plain
    assert "🔴 = claim attuale" not in plain


def test_science_critic_fallback_when_claim_not_verbatim():
    sci_unit = _sample_draft_unit()
    iss = ScienceIssue(
        id="sci_003",
        type=ScienceType.ERR_CONCETTUALE,
        severity=ScienceSeverity.MEDIUM,
        unit_id="U1",
        claim="un claim che non esiste nel testo",
        reason="Spiegazione alternativa",
        suggested_fix="correzione alternativa",
    )

    panel = _build_science_panel(
        idx=0,
        total_count=1,
        iss=iss,
        tc="01:23",
        sci_unit_info="U1 - Introduzione",
        sci_unit=sci_unit,
        decisions_map={},
    )

    plain = panel.renderable.plain
    assert "⚠️ Affermazione: \"un claim che non esiste nel testo\"" in plain
    assert "💡 Correzione:   \"correzione alternativa\"" in plain


def test_asr_risk_visual_layout_unchanged():
    sci_unit = _sample_draft_unit()
    iss = ScienceIssue(
        id="asr_001",
        type=ScienceType.ERR_ASR_ST,
        severity=ScienceSeverity.MEDIUM,
        unit_id="U1",
        claim="enzimi abbassano",
        reason="ASR incerto",
    )

    panel = _build_science_panel(
        idx=0,
        total_count=1,
        iss=iss,
        tc="00:15",
        sci_unit_info="U1 - Introduzione",
        sci_unit=sci_unit,
        decisions_map={},
    )

    plain = panel.renderable.plain
    assert "🎙️ RISCHIO ASR (statistico)" in plain
    assert "⏱ Timecode (stima): 00:15" in plain
    assert "🎙️ Segmento raw sospetto: \"enzimi abbassano\"" in plain
    assert "Azione [A=Accetta / M=Modifica" in plain
    assert "🔴 = claim attuale" not in plain


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
async def test_keybindings_and_actions_asr_risk(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    os.makedirs(os.path.join(lesson_dir, "_state"), exist_ok=True)

    # Scrivi draft.json
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
    async with app.run_test() as pilot:
        # 'a' per ASR accetta il testo dell'unità
        await pilot.press("a")

    ledger = load_ledger(lesson_dir)
    assert len(ledger.decisions) == 1
    assert ledger.decisions[0].issue_id == "asr_1"
    assert ledger.decisions[0].decision == "accepted"
    assert ledger.decisions[0].resolved_text == _sample_draft_unit().content
