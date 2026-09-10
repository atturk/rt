import os
import json
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from rt.core.models import ASRLevel, ScienceType, SegmentsData, Segment, Draft, DraftUnit, ASRIssue, ScienceIssue
from rt.telegram import registry, issue_queue as tg_queue
from rt.telegram.daemon import handle_callback
from rt.telegram.formatting import build_issue_keyboard
from rt.telegram.notify import notify_issues_ready, notify_build_completed
from rt.pipeline.review_asr import run_review_asr
from rt.pipeline.review_science import run_review_science
from rt.llm.prompts import SCIENCE_REVIEW_SYSTEM_PROMPT, build_science_review_user_prompt
from rt.cli import main, cmd_review_asr, cmd_review_science, cmd_build


def _setup_test_lesson(lesson_dir: str):
    os.makedirs(lesson_dir, exist_ok=True)
    seg_data = SegmentsData(
        schema_version="1.0",
        audio_file="test.wav",
        total_duration=120.0,
        segment_count=3,
        segments=[
            Segment(id="seg_000001", index=1, start_seconds=0.0, end_seconds=10.0, start_formatted="00:00", end_formatted="00:10", text_raw="La biochimica cellulare e la glicolisi."),
            Segment(id="seg_000002", index=2, start_seconds=10.0, end_seconds=20.0, start_formatted="00:10", end_formatted="00:20", text_raw="Il cofattore magnesio e l'esochinasi."),
            Segment(id="seg_000003", index=3, start_seconds=20.0, end_seconds=30.0, start_formatted="00:20", end_formatted="00:30", text_raw="La fosforilazione del glucosio.")
        ]
    )
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    draft = Draft(
        schema_version="1.0",
        lesson_id="test_lesson",
        units=[
            DraftUnit(
                unit_id="1.1",
                title="Introduzione alla glicolisi",
                content="La biochimica cellulare analizza le reazioni enzimatiche.",
                start_segment_id="seg_000001",
                end_segment_id="seg_000003",
                source_segment_ids=["seg_000001", "seg_000002", "seg_000003"],
                key_concepts=["biochimica", "glicolisi"]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    from rt.core.models import Outline, OutlineMacro, OutlineUnit
    outline = Outline(
        schema_version="1.0",
        lesson_title="Lezione di Biochimica",
        macro_sections=[
            OutlineMacro(
                id="1",
                title="Introduzione",
                units=[
                    OutlineUnit(
                        id="1.1",
                        title="Introduzione alla glicolisi",
                        start_segment_id="seg_000001",
                        end_segment_id="seg_000003",
                        key_concepts=["biochimica", "glicolisi"]
                    )
                ]
            )
        ]
    )
    with open(os.path.join(lesson_dir, "outline.json"), "w", encoding="utf-8") as f:
        json.dump(outline.model_dump(mode="json"), f)

    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("fase_corrente: draft_validato\nmateria: BIOCHIMICA\ndata: 2026-09-08\n")


def test_issue_keyboard_includes_quit_button():
    kb_asr = build_issue_keyboard("test_id", "asr")
    all_buttons = [b for row in kb_asr["inline_keyboard"] for b in row]
    assert len(all_buttons) == 6
    assert any(b["text"] == "🛑 Esci" and b["callback_data"] == "iq:test_id" for b in all_buttons)

    kb_sci = build_issue_keyboard("test_id", "science")
    all_buttons_sci = [b for row in kb_sci["inline_keyboard"] for b in row]
    assert len(all_buttons_sci) == 6
    assert any(b["text"] == "🛑 Esci" and b["callback_data"] == "iq:test_id" for b in all_buttons_sci)



def test_telegram_review_quit_callback(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    tg_queue.create_queue(lesson_dir, ["asr_000001", "asr_000002"], {"asr_000001": "asr", "asr_000002": "asr"})
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "asr_000001", "issue_type": "asr"}
    )

    update = MagicMock()
    query = MagicMock()
    query.data = f"iq:{short_id}"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update.callback_query = query
    update.effective_chat.id = 12345
    update.effective_message.message_thread_id = None

    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}
    context.bot.send_message = AsyncMock()

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send_next, \
         patch("rt.pipeline.issue_review.start_review_via_telegram") as mock_start:
        asyncio.run(handle_callback(update, context))
        assert not mock_send_next.called
        assert not mock_start.called

    query.answer.assert_awaited_once_with("Revisione interrotta.")
    query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    context.bot.send_message.assert_awaited_once()
    assert "interrotta" in context.bot.send_message.call_args[1]["text"]

    queue = tg_queue.load_queue(lesson_dir)
    assert queue.current_index == 0


def test_telegram_review_back_callback_dispatched(tmp_path):
    """Regressione: il callback 'ib:<short_id>' (bottone Indietro) deve raggiungere
    _handle_issue_callback tramite il dispatcher reale handle_callback(), non essere
    silenziosamente ignorato (mancava da ISSUE_ACTIONS, quindi cadeva nel ramo 'else'
    senza alcun effetto visibile, come riscontrato in uso reale)."""
    lesson_dir = str(tmp_path / "lesson")
    state_dir = str(tmp_path / "state")
    _setup_test_lesson(lesson_dir)

    tg_queue.create_queue(lesson_dir, ["asr_000001", "asr_000002"], {"asr_000001": "asr", "asr_000002": "asr"})
    tg_queue.advance(lesson_dir)  # current_index = 1, così "Indietro" ha senso (non è già alla prima)
    short_id = registry.register_pending(
        lesson_dir, round_=0, kind="issue_review", state_dir=state_dir,
        extra={"issue_id": "asr_000002", "issue_type": "asr"}
    )

    update = MagicMock()
    query = MagicMock()
    query.data = f"ib:{short_id}"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update.callback_query = query
    update.effective_chat.id = 12345
    update.effective_message.message_thread_id = None

    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}

    with patch("rt.pipeline.issue_review.send_current_issue") as mock_send_next:
        asyncio.run(handle_callback(update, context))
        assert mock_send_next.called, "'ib:' deve raggiungere _handle_issue_callback tramite il dispatcher, non essere ignorato"

    queue = tg_queue.load_queue(lesson_dir)
    assert queue.current_index == 0


def test_notify_issues_ready_zero_count(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    with patch("rt.telegram.client.send_message") as mock_send, \
         patch("rt.telegram.config.load_telegram_config", return_value=MagicMock()), \
         patch("rt.core.config.load_config") as mock_cfg:
        mock_cfg.return_value.telegram.topics = []
        mock_cfg.return_value.telegram.state_dir = str(tmp_path / "state")

        notify_issues_ready(lesson_dir, "asr", count=0)
        assert mock_send.called
        _, kwargs = mock_send.call_args
        assert "Nessuna issue ASR trovata" in kwargs["text"]
        assert "reply_markup" not in kwargs or kwargs.get("reply_markup") is None


def test_notify_issues_ready_positive_count(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    with patch("rt.telegram.client.send_message") as mock_send, \
         patch("rt.telegram.config.load_telegram_config", return_value=MagicMock()), \
         patch("rt.core.config.load_config") as mock_cfg:
        mock_cfg.return_value.telegram.topics = []
        mock_cfg.return_value.telegram.state_dir = str(tmp_path / "state")

        notify_issues_ready(lesson_dir, "science", count=5)
        assert mock_send.called
        _, kwargs = mock_send.call_args
        assert "5 issue scientifiche pronte" in kwargs["text"]
        assert kwargs.get("reply_markup") is not None


def test_science_review_prompt_has_no_raw_transcript_access_and_ignores_asr_artifacts():
    """Il critic scientifico non riceve più la trascrizione grezza (causa di confusione
    reale riscontrata: citava frammenti ASR grezzi come se fossero affermazioni del
    docente). Il prompt deve dirglielo esplicitamente e istruirlo a ignorare anomalie
    isolate che potrebbero essere artefatti ASR non ancora corretti."""
    assert "Non hai accesso alla trascrizione grezza originale né all'audio" in SCIENCE_REVIEW_SYSTEM_PROMPT
    assert "review ASR" in SCIENCE_REVIEW_SYSTEM_PROMPT
    assert "source_quote" not in SCIENCE_REVIEW_SYSTEM_PROMPT

    import inspect
    sig = inspect.signature(build_science_review_user_prompt)
    assert "source_segments_text" not in sig.parameters


def test_mock_generation_rich_asr_and_science(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_test_lesson(lesson_dir)

    res_asr = run_review_asr(lesson_dir, force=True, force_mock=True)
    assert res_asr["total_issues"] == 10
    assert res_asr["green_auto_applied"] > 0
    assert res_asr["yellow_review_queue"] > 0
    assert res_asr["red_human_required"] > 0

    res_sci = run_review_science(lesson_dir, force=True, force_mock=True)
    assert res_sci["total_science_issues"] == 10
    assert res_sci["docente_issues"] > 0
    assert res_sci["reconstruction_issues"] > 0
    assert res_sci["science_checks"] > 0


def test_mock_generation_bounded_across_many_units(tmp_path):
    """Regressione trovata in test manuale: run_review_science() chiama l'LLM una
    volta per unità didattica (run_review_asr una volta per batch di segmenti). Senza
    un contatore per-istanza in LLMClient, il mock iniettava lo stesso set di ~10 issue
    ad OGNI chiamata, moltiplicandosi per il numero di unità (24 unità -> 240 issue
    scientifiche mock su una lezione reale, invece di ~10 totali come da richiesta)."""
    lesson_dir = str(tmp_path / "lesson")
    _setup_test_lesson(lesson_dir)

    draft_path = os.path.join(lesson_dir, "draft.json")
    with open(draft_path, "r", encoding="utf-8") as f:
        draft_data = json.load(f)
    template_unit = draft_data["units"][0]
    draft_data["units"] = []
    for i in range(1, 13):
        unit = dict(template_unit)
        unit["unit_id"] = f"{i}.1"
        draft_data["units"].append(unit)
    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(draft_data, f)

    res_sci = run_review_science(lesson_dir, force=True, force_mock=True)
    assert res_sci["total_science_issues"] == 10, (
        f"Atteso ~10 issue scientifiche totali indipendentemente dal numero di unità "
        f"(12 in questo test), trovate {res_sci['total_science_issues']}"
    )


def test_cli_channel_dispatch(tmp_path):
    lesson_dir = str(tmp_path / "lesson")
    _setup_test_lesson(lesson_dir)

    # 1. review-asr con channel terminale -> nessuna notifica telegram
    args_rasr_term = MagicMock(lesson_dir=lesson_dir, force=True, mock=True, channel="terminal")
    with patch("rt.telegram.notify.notify_issues_ready") as mock_notify:
        cmd_review_asr(args_rasr_term)
        assert not mock_notify.called

    # 2. review-asr con channel telegram -> invia notifica telegram
    args_rasr_tg = MagicMock(lesson_dir=lesson_dir, force=True, mock=True, channel="telegram")
    with patch("rt.telegram.notify.notify_issues_ready") as mock_notify:
        cmd_review_asr(args_rasr_tg)
        assert mock_notify.called
        assert mock_notify.call_args[0][1] == "asr"
        assert mock_notify.call_args[0][2] == 10

    # 3. review-science con channel telegram -> invia notifica telegram
    args_rsci_tg = MagicMock(lesson_dir=lesson_dir, force=True, mock=True, channel="telegram")
    with patch("rt.telegram.notify.notify_issues_ready") as mock_notify:
        cmd_review_science(args_rsci_tg)
        assert mock_notify.called
        assert mock_notify.call_args[0][1] == "science"
        assert mock_notify.call_args[0][2] == 10

    # 4. build standalone con channel telegram -> invia notify_build_completed
    args_bld_tg = MagicMock(lesson_dir=lesson_dir, force=True, rename=False, channel="telegram")
    with patch("rt.cli.run_build", return_value={"status": "completed", "lesson_dir": lesson_dir, "rielaborato": "rielaborato.md"}), \
         patch("rt.telegram.notify.notify_build_completed") as mock_notify_bld:
        cmd_build(args_bld_tg)
        assert mock_notify_bld.called
