"""
tests/test_recall_session.py
Test di accettazione per la Fase D2 (sessione interattiva di Active Recall)
e per il comando CLI `rt recall`.
"""
import os
import json
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from rt.core.models import (
    RecallQuestion, RecallQuestionType, RecallQuestionStatus,
    SegmentsData, Segment, Draft, DraftUnit,
)
from rt.core.manifest import init_or_update_manifest
from rt.pipeline.recall import save_recall_bank, load_recall_bank, get_reserve_count
from rt.core.models import RecallBank
from rt.pipeline.recall_session import (
    load_recall_session_state, save_recall_session_state,
    start_recall_via_telegram, send_current_recall_question,
    run_recall_terminal_session, handle_recall_answer,
)
from rt.telegram import registry, recall_preferences
from rt.telegram.config import TelegramConfig
from rt.telegram.daemon import (
    handle_callback, handle_text, handle_voice, handle_stile,
    handle_recall_command, handle_poll_answer, handle_message_reaction,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _setup_lesson(lesson_dir: str, num_units: int = 4):
    os.makedirs(lesson_dir, exist_ok=True)
    segs = [
        Segment(id=f"seg_{i:06d}", index=i, start_seconds=float(i * 10), end_seconds=float(i * 10 + 8),
                start_formatted=f"00:{i*10:02d}", end_formatted=f"00:{i*10+8:02d}", text_raw=f"testo {i}")
        for i in range(1, num_units + 1)
    ]
    seg_data = SegmentsData(schema_version="1.0", audio_file="audio.mp3", audio_duration_seconds=120.0, segments=segs)
    with open(os.path.join(lesson_dir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_data.model_dump(mode="json"), f)

    units = [
        DraftUnit(unit_id=f"{i}.1", title=f"Unita {i}", content=f"Contenuto unita {i}.",
                  start_segment_id=f"seg_{i:06d}", end_segment_id=f"seg_{i:06d}", source_segment_ids=[f"seg_{i:06d}"])
        for i in range(1, num_units + 1)
    ]
    draft = Draft(schema_version="1.0", lesson_id="L1", units=units)
    with open(os.path.join(lesson_dir, "draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft.model_dump(mode="json"), f)

    init_or_update_manifest(lesson_dir=lesson_dir, lesson_id="L1", date="2026-09-09", subject="TEST",
                             current_state="DRAFT_VALIDATED")
    with open(os.path.join(lesson_dir, "info.yaml"), "w", encoding="utf-8") as f:
        f.write("status: DRAFT_VALIDATED\nfase_corrente: rewrite_completato\nmateria: TEST\n")


def _make_quiz_question(qid="recall_000001", unit_id="1.1") -> RecallQuestion:
    return RecallQuestion(
        id=qid, type=RecallQuestionType.QUIZ, unit_ids=[unit_id],
        question_text="Qual e' il substrato?", options=["A", "B", "C", "D"], correct_index=1,
        pregenerated_material="B e' corretta perche'...",
    )


def _make_mirata_question(qid="recall_000002", unit_id="1.1") -> RecallQuestion:
    return RecallQuestion(id=qid, type=RecallQuestionType.MIRATA, unit_ids=[unit_id], question_text="Descrivi X.")


def _make_mock_callback_update(data: str, chat_id: int = 12345):
    update = MagicMock()
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update.callback_query = query
    update.effective_chat.id = chat_id
    update.effective_message.message_thread_id = None
    return update


def _make_mock_context(state_dir: str):
    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}
    context.bot.send_message = AsyncMock()
    context.args = []
    return context


# ---------------------------------------------------------------------------
# 1. Stato di sessione (ordine/cursore/domanda corrente)
# ---------------------------------------------------------------------------

class TestSessionState:
    def test_default_state_when_missing(self, tmp_path):
        state = load_recall_session_state(str(tmp_path))
        assert state["order"] == "sequenziale"
        assert state["unit_cursor"] is None
        assert state["current_question_id"] is None

    def test_round_trip(self, tmp_path):
        save_recall_session_state(str(tmp_path), {"order": "alternato", "unit_cursor": "2.1", "current_question_id": "recall_000005", "force_mock": True})
        state = load_recall_session_state(str(tmp_path))
        assert state == {"order": "alternato", "unit_cursor": "2.1", "current_question_id": "recall_000005", "force_mock": True}

    def test_force_mock_persists_for_daemon_refills(self, tmp_path):
        """Il flag --mock della sessione CLI deve sopravvivere alle chiamate del daemon
        (processo separato) che non lo ripassano esplicitamente."""
        save_recall_session_state(str(tmp_path), {"order": "sequenziale", "unit_cursor": None, "current_question_id": None, "force_mock": True})
        state = load_recall_session_state(str(tmp_path))
        assert state["force_mock"] is True


# ---------------------------------------------------------------------------
# 2. start_recall_via_telegram: batch iniziale + guardia doppia sessione
# ---------------------------------------------------------------------------

class TestStartRecallViaTelegram:
    def test_first_call_generates_all_types_and_sends_first_question(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)

        cfg = TelegramConfig(bot_token="TOK", chat_id=999)
        sent = []

        def fake_send(cfg_, text, reply_markup=None, message_thread_id=None, reply_to_message_id=None):
            mid = 100 + len(sent)
            sent.append({"text": text, "reply_markup": reply_markup})
            return {"ok": True, "message_id": mid}

        def fake_send_poll(cfg_, question, options, correct_option_id, message_thread_id=None, is_anonymous=False):
            return {"message_id": 400, "poll": {"id": "POLLY"}}

        with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
             patch("rt.telegram.client.send_message", side_effect=fake_send), \
             patch("rt.telegram.client.send_poll", side_effect=fake_send_poll), \
             patch("rt.core.config.load_config") as mock_cfg:
            cfg_obj = MagicMock()
            cfg_obj.telegram.state_dir = state_dir
            cfg_obj.telegram.topics = {}
            cfg_obj.telegram.recall.reserve_targets = {"mirata": 2, "quiz": 2, "vasta": 1}
            cfg_obj.telegram.recall.refill_threshold = 3
            cfg_obj.telegram.recall.refill_batch_size = 2
            mock_cfg.return_value = cfg_obj

            start_recall_via_telegram(lesson_dir, order="sequenziale", style="quiz", force_mock=True)

        bank = load_recall_bank(lesson_dir)
        types_present = {q.type for q in bank.questions}
        assert types_present == {RecallQuestionType.QUIZ, RecallQuestionType.MIRATA, RecallQuestionType.VASTA}
        # Il poll nativo per la domanda + il messaggio con i bottoni "Non lo so"/"Skip"
        assert len(sent) == 1
        assert sent[0]["reply_markup"] is not None
        assert recall_preferences.get_active_style(state_dir) == "quiz"

    def test_double_session_guard(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)

        cfg = TelegramConfig(bot_token="TOK", chat_id=999)
        sent = []

        def fake_send(cfg_, text, reply_markup=None, message_thread_id=None, reply_to_message_id=None):
            mid = 100 + len(sent)
            sent.append({"text": text, "reply_markup": reply_markup})
            return {"ok": True, "message_id": mid}

        with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
             patch("rt.telegram.client.send_message", side_effect=fake_send), \
             patch("rt.telegram.client.send_poll", return_value={"message_id": 500, "poll": {"id": "POLLZ"}}), \
             patch("rt.core.config.load_config") as mock_cfg:
            cfg_obj = MagicMock()
            cfg_obj.telegram.state_dir = state_dir
            cfg_obj.telegram.topics = {}
            cfg_obj.telegram.recall.reserve_targets = {"mirata": 1, "quiz": 1, "vasta": 1}
            cfg_obj.telegram.recall.refill_threshold = 0
            cfg_obj.telegram.recall.refill_batch_size = 1
            mock_cfg.return_value = cfg_obj

            start_recall_via_telegram(lesson_dir, force_mock=True)
            first_count = len(sent)
            start_recall_via_telegram(lesson_dir, force_mock=True)

        # La seconda chiamata non deve rimandare bottoni (solo un promemoria senza tastiera)
        assert len(sent) == first_count + 1
        assert sent[-1]["reply_markup"] is None

    def test_daemon_refill_respects_mock_without_explicit_arg(self, tmp_path):
        """Bug reale trovato in verifica: una sessione avviata da CLI con --mock deve restare
        mockata anche per i rifornimenti innescati dal daemon in un secondo momento, che non
        ripassano force_mock esplicitamente — deve risolversi da telegram_recall_session.json,
        non dal default della funzione."""
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)

        cfg = TelegramConfig(bot_token="TOK", chat_id=999)

        with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
             patch("rt.telegram.client.send_message", return_value={"ok": True, "message_id": 1}), \
             patch("rt.telegram.client.send_poll", return_value={"message_id": 1, "poll": {"id": "POLLX"}}), \
             patch("rt.core.config.load_config") as mock_cfg:
            cfg_obj = MagicMock()
            cfg_obj.telegram.state_dir = state_dir
            cfg_obj.telegram.topics = {}
            cfg_obj.telegram.recall.reserve_targets = {"mirata": 1, "quiz": 1, "vasta": 1}
            cfg_obj.telegram.recall.refill_threshold = 5  # forza sempre il rifornimento
            cfg_obj.telegram.recall.refill_batch_size = 1
            mock_cfg.return_value = cfg_obj

            start_recall_via_telegram(lesson_dir, style="quiz", force_mock=True)

            # Chiamata "come farebbe il daemon": nessun force_mock esplicito.
            with patch("rt.llm.client.LLMClient.call_structured") as mock_llm_call:
                send_current_recall_question(lesson_dir)
                assert not mock_llm_call.called, "il rifornimento ha chiamato l'LLM reale invece di restare mockato"


# ---------------------------------------------------------------------------
# 3. send_current_recall_question: contenuto + rifornimento
# ---------------------------------------------------------------------------

class TestSendCurrentRecallQuestion:
    def test_sends_quiz_as_native_poll_and_refills_below_threshold(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)

        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)
        save_recall_session_state(lesson_dir, {"order": "sequenziale", "unit_cursor": None, "current_question_id": None})
        recall_preferences.set_active_style(state_dir, "quiz")

        cfg = TelegramConfig(bot_token="TOK", chat_id=999)
        polls = []
        messages = []

        def fake_send_poll(cfg_, question, options, correct_option_id, message_thread_id=None, is_anonymous=False):
            polls.append({"question": question, "options": options, "correct_option_id": correct_option_id})
            return {"message_id": 300, "poll": {"id": "POLL123"}}

        def fake_send_message(cfg_, text, reply_markup=None, message_thread_id=None, reply_to_message_id=None):
            messages.append({"text": text, "reply_markup": reply_markup})
            return {"ok": True, "message_id": 301}

        with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
             patch("rt.telegram.client.send_poll", side_effect=fake_send_poll), \
             patch("rt.telegram.client.send_message", side_effect=fake_send_message), \
             patch("rt.core.config.load_config") as mock_cfg:
            cfg_obj = MagicMock()
            cfg_obj.telegram.state_dir = state_dir
            cfg_obj.telegram.topics = {}
            cfg_obj.telegram.recall.refill_threshold = 5  # forza il rifornimento (1 < 5)
            cfg_obj.telegram.recall.refill_batch_size = 2
            mock_cfg.return_value = cfg_obj

            send_current_recall_question(lesson_dir, force_mock=True)

        assert len(polls) == 1
        assert polls[0]["options"] == ["A", "B", "C", "D"] and polls[0]["correct_option_id"] == 1
        assert len(messages) == 1  # bottoni "Non lo so"/"Skip" in un messaggio a parte
        assert messages[0]["reply_markup"] is not None

        # Il poll_id e il message_id devono essere risolvibili dal registry per le risposte successive
        entry_poll = registry.resolve_pending("POLL123", state_dir)
        assert entry_poll is not None and entry_poll["kind"] == "recall_quiz_poll"
        entry_msg = registry.resolve_pending("300", state_dir)
        assert entry_msg is not None and entry_msg["kind"] == "recall_question_message"

        # Il rifornimento deve aver aggiunto nuove domande quiz (partiva da 1, sotto soglia 5)
        assert get_reserve_count(lesson_dir, RecallQuestionType.QUIZ) >= 2

        state = load_recall_session_state(lesson_dir)
        assert state["current_question_id"] == "recall_000001"


# ---------------------------------------------------------------------------
# 4. handle_recall_answer (D3, salvataggio + valutazione)
# ---------------------------------------------------------------------------

class TestHandleRecallAnswer:
    def test_mirata_answer_is_evaluated_and_saved(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        evaluation = handle_recall_answer(lesson_dir, "recall_000002", "La mia risposta.", is_voice=False, force_mock=True)
        assert evaluation is not None
        assert "Correttezza" in evaluation and "Completezza" in evaluation
        assert "Unità 1.1" in evaluation  # riferimento all'unità didattica allegato alla risposta

        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000002")
        assert ans.answer_text == "La mia risposta."
        assert ans.is_voice is False
        # Il ledger conserva la valutazione "pura" (senza il riferimento all'unità, allegato
        # solo al messaggio di risposta mostrato all'utente)
        assert ans.evaluation in evaluation
        assert ans.evaluation != evaluation

    def test_quiz_returns_none(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)

        result = handle_recall_answer(lesson_dir, "recall_000001", "B", is_voice=False, force_mock=True)
        assert result is None


# ---------------------------------------------------------------------------
# 5. Voto per reazione, risposta a poll nativo, azioni "Non lo so"/"Skip"
# ---------------------------------------------------------------------------

def _make_mock_reaction_update(message_id: int, emoji: str, chat_id: int = 12345):
    update = MagicMock()
    reaction = MagicMock()
    reaction.message_id = message_id
    reaction.new_reaction = [MagicMock(emoji=emoji)]
    update.message_reaction = reaction
    update.effective_chat.id = chat_id
    return update


def _make_mock_poll_answer_update(poll_id: str, option_ids: list):
    update = MagicMock()
    answer = MagicMock()
    answer.poll_id = poll_id
    answer.option_ids = option_ids
    update.poll_answer = answer
    return update


class TestRecallReactionVote:
    def test_reaction_updates_ledger_and_fewshot(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        registry.register_with_key(
            "555", lesson_dir, kind="recall_question_message", state_dir=state_dir,
            extra={"question_id": "recall_000002"},
        )
        update = _make_mock_reaction_update(555, "⚡")
        context = _make_mock_context(state_dir)

        asyncio.run(handle_message_reaction(update, context))

        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000002")
        assert ans.vote == "lightning"
        assert ans.answer_text == ""  # nessuna risposta ancora data

        examples = json.load(open(os.path.join(state_dir, "recall_fewshot.json")))
        assert len(examples["mirata"]) == 1
        assert examples["mirata"][0]["vote"] == "lightning"

    def test_unmapped_emoji_is_ignored(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        registry.register_with_key(
            "556", lesson_dir, kind="recall_question_message", state_dir=state_dir,
            extra={"question_id": "recall_000002"},
        )
        update = _make_mock_reaction_update(556, "😀")
        context = _make_mock_context(state_dir)

        asyncio.run(handle_message_reaction(update, context))

        bank2 = load_recall_bank(lesson_dir)
        assert not any(a.question_id == "recall_000002" for a in bank2.answers)


class TestRecallPollAnswer:
    def test_poll_answer_records_answer_stops_poll_and_advances(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)

        registry.register_with_key(
            "POLL42", lesson_dir, kind="recall_quiz_poll", state_dir=state_dir,
            extra={"question_id": "recall_000001", "message_id": 700},
        )
        update = _make_mock_poll_answer_update("POLL42", [1])  # opzione B, indice 1 = corretta
        context = _make_mock_context(state_dir)

        cfg = TelegramConfig(bot_token="TOK", chat_id=999)
        with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
             patch("rt.telegram.client.stop_poll") as mock_stop, \
             patch("rt.pipeline.recall_session.send_current_recall_question") as mock_next:
            asyncio.run(handle_poll_answer(update, context))
            assert mock_stop.called
            assert mock_next.called

        assert context.bot.send_message.called
        sent_text = context.bot.send_message.call_args.kwargs["text"]
        assert "Corretto" in sent_text

        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000001")
        assert ans.answer_text == "B"
        assert ans.evaluation == "B e' corretta perche'..."

    def test_empty_option_ids_is_ignored(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)

        registry.register_with_key(
            "POLL43", lesson_dir, kind="recall_quiz_poll", state_dir=state_dir,
            extra={"question_id": "recall_000001", "message_id": 701},
        )
        update = _make_mock_poll_answer_update("POLL43", [])
        context = _make_mock_context(state_dir)

        asyncio.run(handle_poll_answer(update, context))
        assert not context.bot.send_message.called


class TestRecallActionCallbacks:
    def test_skip_strips_markup_and_advances_without_recording(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        short_id = registry.register_pending(
            lesson_dir, round_=0, kind="recall_question", state_dir=state_dir,
            extra={"question_id": "recall_000002", "qtype": "mirata"}
        )
        update = _make_mock_callback_update(f"rsk:{short_id}")
        context = _make_mock_context(state_dir)

        with patch("rt.pipeline.recall_session.send_current_recall_question") as mock_next:
            asyncio.run(handle_callback(update, context))
            assert mock_next.called

        assert update.callback_query.edit_message_reply_markup.called
        bank2 = load_recall_bank(lesson_dir)
        assert not any(a.question_id == "recall_000002" for a in bank2.answers)

    def test_non_lo_so_on_mirata_evaluates_and_includes_unit_reference(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        short_id = registry.register_pending(
            lesson_dir, round_=0, kind="recall_question", state_dir=state_dir,
            extra={"question_id": "recall_000002", "qtype": "mirata"}
        )
        update = _make_mock_callback_update(f"rns:{short_id}")
        context = _make_mock_context(state_dir)

        with patch("rt.pipeline.recall_session.send_current_recall_question") as mock_next:
            asyncio.run(handle_callback(update, context))
            assert mock_next.called

        assert context.bot.send_message.called
        sent_text = context.bot.send_message.call_args.kwargs["text"]
        assert "Unità 1.1" in sent_text  # riferimento all'unità didattica

    def test_non_lo_so_on_quiz_stops_poll_and_includes_unit_reference(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)

        short_id = registry.register_pending(
            lesson_dir, round_=0, kind="recall_question", state_dir=state_dir,
            extra={"question_id": "recall_000001", "qtype": "quiz", "poll_message_id": 900}
        )
        update = _make_mock_callback_update(f"rns:{short_id}")
        context = _make_mock_context(state_dir)

        cfg = TelegramConfig(bot_token="TOK", chat_id=999)
        with patch("rt.telegram.config.load_telegram_config", return_value=cfg), \
             patch("rt.telegram.client.stop_poll") as mock_stop, \
             patch("rt.pipeline.recall_session.send_current_recall_question") as mock_next:
            asyncio.run(handle_callback(update, context))
            assert mock_stop.called
            assert mock_next.called

        assert context.bot.send_message.called
        sent_text = context.bot.send_message.call_args.kwargs["text"]
        assert "Unità: 1.1" in sent_text  # riferimento all'unità didattica (quiz: solo id/titolo)


# ---------------------------------------------------------------------------
# 6. handle_text / handle_voice (dispatch verso il recall attivo)
# ---------------------------------------------------------------------------

class TestTextAndVoiceDispatch:
    def test_handle_text_routes_to_recall_answer_when_session_active(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)
        save_recall_session_state(lesson_dir, {"order": "sequenziale", "unit_cursor": None, "current_question_id": "recall_000002"})

        from rt.telegram import session as tg_session
        tg_session.start_session(state_dir, 12345, None, "recall", lesson_dir)

        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_message.message_thread_id = None
        update.message.text = "Risposta a voce di testo."
        update.message.reply_text = AsyncMock()
        context = _make_mock_context(state_dir)

        with patch("rt.pipeline.recall_session.send_current_recall_question") as mock_next, \
             patch("rt.pipeline.recall.evaluate_recall_answer", return_value="Correttezza: 80%\nCompletezza: 60%\n\nOk."):
            asyncio.run(handle_text(update, context))
            assert mock_next.called

        assert update.message.reply_text.called
        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000002")
        assert ans.answer_text == "Risposta a voce di testo."

    def test_handle_voice_rejects_when_current_question_is_quiz(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)
        save_recall_session_state(lesson_dir, {"order": "sequenziale", "unit_cursor": None, "current_question_id": "recall_000001"})

        from rt.telegram import session as tg_session
        tg_session.start_session(state_dir, 12345, None, "recall", lesson_dir)

        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_message.message_thread_id = None
        update.message.voice.file_id = "VOICE123"
        update.message.reply_text = AsyncMock()
        context = _make_mock_context(state_dir)

        asyncio.run(handle_voice(update, context))
        update.message.reply_text.assert_called_once()
        assert "bottoni" in update.message.reply_text.call_args[0][0]


# ---------------------------------------------------------------------------
# 7. /stile: propone i 3 stili con 3 bottoni, nessun argomento testuale
# ---------------------------------------------------------------------------

class TestStileCommand:
    def test_shows_current_style_with_three_buttons(self, tmp_path):
        state_dir = str(tmp_path / "state")
        update = MagicMock()
        update.effective_message.message_thread_id = None
        update.effective_message.reply_text = AsyncMock()
        context = _make_mock_context(state_dir)

        asyncio.run(handle_stile(update, context))
        update.effective_message.reply_text.assert_called_once()
        _, kwargs = update.effective_message.reply_text.call_args
        assert "quiz" in update.effective_message.reply_text.call_args[0][0]
        keyboard = kwargs["reply_markup"]
        row = keyboard["inline_keyboard"][0]
        assert len(row) == 3
        assert {btn["callback_data"] for btn in row} == {"stile:quiz", "stile:mirata", "stile:vasta"}

    def test_button_callback_sets_style(self, tmp_path):
        state_dir = str(tmp_path / "state")
        update = _make_mock_callback_update("stile:vasta")
        update.callback_query.edit_message_text = AsyncMock()
        context = _make_mock_context(state_dir)

        asyncio.run(handle_callback(update, context))
        assert recall_preferences.get_active_style(state_dir) == "vasta"
        assert update.callback_query.answer.called
        assert update.callback_query.edit_message_text.called

    def test_button_callback_rejects_invalid_style(self, tmp_path):
        state_dir = str(tmp_path / "state")
        update = _make_mock_callback_update("stile:boh")
        context = _make_mock_context(state_dir)

        asyncio.run(handle_callback(update, context))
        assert recall_preferences.get_active_style(state_dir) == "quiz"  # default, non cambiato
        update.callback_query.answer.assert_called_once_with("Stile non valido.", show_alert=True)


# ---------------------------------------------------------------------------
# 7b. /recall lanciato da Telegram: usa l'ultima lezione tracciata per il topic
# ---------------------------------------------------------------------------

class TestRecallCommand:
    def test_no_last_lesson_replies_with_guidance(self, tmp_path):
        state_dir = str(tmp_path / "state")
        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_message.message_thread_id = None
        update.effective_message.reply_text = AsyncMock()
        context = _make_mock_context(state_dir)

        asyncio.run(handle_recall_command(update, context))
        update.effective_message.reply_text.assert_called_once()
        assert "rt recall" in update.effective_message.reply_text.call_args[0][0]

    def test_launches_session_for_last_lesson(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)

        from rt.telegram.last_lesson import record_last_lesson
        record_last_lesson(state_dir, 12345, None, lesson_dir)

        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_message.message_thread_id = None
        context = _make_mock_context(state_dir)

        with patch("rt.pipeline.recall_session.start_recall_via_telegram") as mock_start:
            asyncio.run(handle_recall_command(update, context))
            mock_start.assert_called_once_with(lesson_dir, "sequenziale", None, False)


# ---------------------------------------------------------------------------
# 8. Sessione interattiva da terminale
# ---------------------------------------------------------------------------

class TestRecallTerminalSession:
    def test_quiz_flow_records_answer(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_quiz_question()])
        save_recall_bank(bank, lesson_dir)

        keys = iter(["b", "q"])  # sceglie l'opzione B (corretta), poi esce
        with patch("rt.core.keyboard.read_single_key", lambda already_raw=False: next(keys)), \
             patch("sys.stdin") as mock_stdin, \
             patch("rt.core.config.load_config") as mock_cfg:
            mock_stdin.isatty.return_value = True
            cfg_obj = MagicMock()
            cfg_obj.telegram.state_dir = state_dir
            cfg_obj.telegram.recall.refill_threshold = 0
            cfg_obj.telegram.recall.refill_batch_size = 1
            cfg_obj.telegram.recall.reserve_targets = {"mirata": 1, "quiz": 1, "vasta": 1}
            mock_cfg.return_value = cfg_obj

            run_recall_terminal_session(lesson_dir, order="sequenziale", style="quiz", force_mock=True)

        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000001")
        assert ans.answer_text == "B"

    def test_mirata_respond_via_editor_is_evaluated(self, tmp_path):
        lesson_dir = str(tmp_path / "lesson")
        state_dir = str(tmp_path / "state")
        _setup_lesson(lesson_dir)
        bank = RecallBank(questions=[_make_mirata_question()])
        save_recall_bank(bank, lesson_dir)

        keys = iter(["r", "q"])
        with patch("rt.core.keyboard.read_single_key", lambda already_raw=False: next(keys)), \
             patch("rt.core.editor_edit.edit_text_in_editor", return_value="# commento\nLa mia risposta scritta nell'editor."), \
             patch("sys.stdin") as mock_stdin, \
             patch("rt.core.config.load_config") as mock_cfg:
            mock_stdin.isatty.return_value = True
            cfg_obj = MagicMock()
            cfg_obj.telegram.state_dir = state_dir
            cfg_obj.telegram.recall.refill_threshold = 0
            cfg_obj.telegram.recall.refill_batch_size = 1
            cfg_obj.telegram.recall.reserve_targets = {"mirata": 1, "quiz": 1, "vasta": 1}
            mock_cfg.return_value = cfg_obj

            run_recall_terminal_session(lesson_dir, order="sequenziale", style="mirata", force_mock=True)

        bank2 = load_recall_bank(lesson_dir)
        ans = next(a for a in bank2.answers if a.question_id == "recall_000002")
        assert ans.answer_text == "La mia risposta scritta nell'editor."
        assert ans.evaluation is not None and "Correttezza" in ans.evaluation


# ---------------------------------------------------------------------------
# 9. Comando CLI `rt recall`: guardia sul draft
# ---------------------------------------------------------------------------

class TestCmdRecallGuard:
    def test_aborts_without_valid_draft(self, tmp_path, capsys):
        from rt.cli import cmd_recall
        lesson_dir = str(tmp_path / "empty_lesson")
        os.makedirs(lesson_dir, exist_ok=True)

        args = MagicMock()
        args.lesson_dir = lesson_dir
        args.mock = True
        args.order = "sequenziale"
        args.style = None
        args.channel = "terminal"

        with pytest.raises(SystemExit) as exc:
            cmd_recall(args)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "draft" in captured.err.lower()

    def test_aborts_without_configured_job(self, tmp_path, monkeypatch, capsys):
        """Senza --mock, con draft valido ma nessun job LLM configurato per lo stile
        richiesto, deve fallire con un messaggio chiaro invece di un crash profondo."""
        from rt.cli import cmd_recall
        lesson_dir = str(tmp_path / "lesson")
        _setup_lesson(lesson_dir)
        monkeypatch.chdir(tmp_path)
        os.makedirs(tmp_path / "config", exist_ok=True)

        args = MagicMock()
        args.lesson_dir = lesson_dir
        args.mock = False
        args.order = "sequenziale"
        args.style = "quiz"
        args.channel = "terminal"

        from rt.core.idempotency import PhaseStatus
        with patch("rt.core.idempotency.check_phase_status", return_value=(PhaseStatus.VALID, "ok")):
            with pytest.raises(SystemExit) as exc:
                cmd_recall(args)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "recall_quiz" in captured.err
