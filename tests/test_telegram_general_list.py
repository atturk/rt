"""/list nel topic Generale: tutte le lezioni per materia, numerate, e recall avviata nel topic
della materia rispondendo con il numero."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rt.core.lesson_index import LessonEntry
from rt.telegram import registry
from rt.telegram.daemon import handle_list_command, handle_recall_command, handle_text
from rt.telegram.formatting import order_lessons_by_materia, render_grouped_lesson_list

TOPICS = {"BIOCHIMICA": 42, "ANATOMIA": 99}


def _entry(path, materia, data, titolo):
    return LessonEntry(lesson_dir=path, folder_name=path.rsplit("/", 1)[-1], data=data,
                       materia=materia, titolo=titolo, argomenti="")


ENTRIES = [
    _entry("/l/bio2", "BIOCHIMICA", "2026-09-02", "Krebs"),
    _entry("/l/fis1", "FISIOLOGIA", "2026-09-05", "Cuore"),
    _entry("/l/ana1", "ANATOMIA", "2026-09-03", "Femore"),
    _entry("/l/bio1", "BIOCHIMICA", "2026-09-01", "Glicolisi"),
    _entry("/l/x", "", "2026-09-04", "Seminario"),
]


def _cfg(misc=7):
    cfg = MagicMock()
    cfg.telegram.topics = dict(TOPICS)
    cfg.telegram.misc_topic_id = misc
    return cfg


def _update(thread_id=None, is_topic=False, text=None, reply_to=None, chat_id=-1004490473926):
    update = MagicMock()
    update.effective_chat.id = chat_id
    msg = update.effective_message
    msg.message_thread_id = thread_id
    msg.is_topic_message = is_topic
    msg.text = text
    msg.reply_to_message = reply_to
    sent = [MagicMock(message_id=500 + i) for i in range(10)]
    msg.reply_text = AsyncMock(side_effect=sent)
    update.message = msg
    return update


def _context(state_dir, args=None):
    context = MagicMock()
    context.bot_data = {"state_dir": state_dir}
    context.args = args or []
    return context


def test_grouped_list_numbers_across_materie_in_order():
    ordered = order_lessons_by_materia(ENTRIES)
    assert [e.lesson_dir for e in ordered] == ["/l/ana1", "/l/bio1", "/l/bio2", "/l/fis1", "/l/x"]
    [text] = render_grouped_lesson_list(ordered)
    assert "<b>ANATOMIA</b> (1)\n1. [2026-09-03] Femore" in text
    assert "<b>BIOCHIMICA</b> (2)\n2. [2026-09-01] Glicolisi\n3. [2026-09-02] Krebs" in text
    assert "<b>Senza materia</b> (1)\n5. [2026-09-04] Seminario" in text
    assert text.rstrip().endswith("topic della sua materia.")


def test_grouped_list_splits_long_lists_keeping_numbering():
    many = [_entry(f"/l/{i:03d}", "BIOCHIMICA", "2026-09-01", "Lezione molto lunga " * 5) for i in range(120)]
    chunks = render_grouped_lesson_list(order_lessons_by_materia(many), max_chars=1500)
    assert len(chunks) > 1 and all(len(c) <= 1500 for c in chunks)
    joined = "\n".join(chunks)
    assert "1. [2026-09-01]" in joined and "\n120. [2026-09-01]" in joined
    assert chunks[1].split("\n")[0][0].isdigit()  # la numerazione prosegue, niente intestazione nuova


def test_list_in_general_shows_every_lesson_and_registers_it(tmp_path):
    state_dir = str(tmp_path)
    update = _update(thread_id=None)
    with patch("rt.core.config.load_config", return_value=_cfg()), \
         patch("rt.core.lesson_index.database_lessons", return_value=list(ENTRIES)):
        asyncio.run(handle_list_command(update, _context(state_dir)))
    text = update.effective_message.reply_text.call_args[0][0]
    assert "Tutte le lezioni (5)" in text and "<b>FISIOLOGIA</b>" in text
    assert "message_thread_id" not in update.effective_message.reply_text.call_args.kwargs
    assert registry.resolve_list_message(500, state_dir) == [
        "/l/ana1", "/l/bio1", "/l/bio2", "/l/fis1", "/l/x"]


def test_list_in_misc_topic_keeps_only_unmapped_lessons(tmp_path):
    update = _update(thread_id=7, is_topic=True)
    with patch("rt.core.config.load_config", return_value=_cfg(misc=7)), \
         patch("rt.core.lesson_index.database_lessons", return_value=list(ENTRIES)):
        asyncio.run(handle_list_command(update, _context(str(tmp_path))))
    text = update.effective_message.reply_text.call_args[0][0]
    assert "Tutte le lezioni" not in text
    assert "Cuore" in text and "Seminario" in text and "Krebs" not in text


def test_list_in_materia_topic_unchanged(tmp_path):
    update = _update(thread_id=42, is_topic=True)
    with patch("rt.core.config.load_config", return_value=_cfg()), \
         patch("rt.core.lesson_index.database_lessons", return_value=list(ENTRIES)):
        asyncio.run(handle_list_command(update, _context(str(tmp_path))))
    text = update.effective_message.reply_text.call_args[0][0]
    assert "Glicolisi" in text and "Krebs" in text and "Femore" not in text


def _reply_to(message_id):
    reply = MagicMock()
    reply.message_id = message_id
    return reply


def test_plain_number_reply_in_general_starts_recall_in_materia_topic(tmp_path):
    state_dir = str(tmp_path)
    registry.register_list_message(321, ["/l/ana1", "/l/bio1"], state_dir)
    # nel Generale una risposta porta il thread della catena di risposte, non un topic
    update = _update(thread_id=321, is_topic=False, text=" 2 ", reply_to=_reply_to(321))
    with patch("rt.core.config.load_config", return_value=_cfg()), \
         patch("rt.telegram.recall_channel.start_recall_via_telegram", return_value=None) as start, \
         patch("rt.telegram.config.resolve_topic_id", return_value=42):
        asyncio.run(handle_text(update, _context(state_dir)))
    start.assert_called_once_with("/l/bio1", "alternato", None, False)
    text = update.effective_message.reply_text.call_args[0][0]
    assert text == "▶️ Recall avviata nel topic BIOCHIMICA.\nhttps://t.me/c/4490473926/42"


def test_number_reply_to_unmapped_lesson_goes_to_varie(tmp_path):
    state_dir = str(tmp_path)
    registry.register_list_message(321, ["/l/x"], state_dir)
    update = _update(thread_id=None, text="1", reply_to=_reply_to(321))
    with patch("rt.core.config.load_config", return_value=_cfg()), \
         patch("rt.telegram.recall_channel.start_recall_via_telegram", return_value=None), \
         patch("rt.telegram.config.resolve_topic_id", return_value=7):
        asyncio.run(handle_text(update, _context(state_dir)))
    assert update.effective_message.reply_text.call_args[0][0].startswith("▶️ Recall avviata nel topic varie.")


def test_number_reply_reports_why_recall_did_not_start(tmp_path):
    state_dir = str(tmp_path)
    registry.register_list_message(321, ["/l/bio1"], state_dir)
    update = _update(thread_id=None, text="1", reply_to=_reply_to(321))
    with patch("rt.core.config.load_config", return_value=_cfg()), \
         patch("rt.telegram.recall_channel.start_recall_via_telegram", return_value="Il bot Telegram non è configurato."), \
         patch("rt.telegram.config.resolve_topic_id", return_value=42):
        asyncio.run(handle_text(update, _context(state_dir)))
    assert update.effective_message.reply_text.call_args[0][0] == "⚠️ Recall non avviata: Il bot Telegram non è configurato."


def test_number_reply_out_of_range(tmp_path):
    state_dir = str(tmp_path)
    registry.register_list_message(321, ["/l/bio1"], state_dir)
    update = _update(thread_id=None, text="9", reply_to=_reply_to(321))
    with patch("rt.telegram.recall_channel.start_recall_via_telegram") as start:
        asyncio.run(handle_text(update, _context(state_dir)))
    start.assert_not_called()
    assert "Posizione 9 non valida" in update.effective_message.reply_text.call_args[0][0]


def test_number_reply_in_same_topic_adds_no_confirmation(tmp_path):
    state_dir = str(tmp_path)
    registry.register_list_message(321, ["/l/bio1"], state_dir)
    update = _update(thread_id=42, is_topic=True, reply_to=_reply_to(321))
    with patch("rt.core.config.load_config", return_value=_cfg()), \
         patch("rt.telegram.recall_channel.start_recall_via_telegram", return_value=None) as start, \
         patch("rt.telegram.config.resolve_topic_id", return_value=42):
        asyncio.run(handle_recall_command(update, _context(state_dir, args=["1"])))
    start.assert_called_once()
    update.effective_message.reply_text.assert_not_called()


def test_text_not_replying_to_a_list_is_not_a_pick(tmp_path):
    state_dir = str(tmp_path)
    update = _update(thread_id=None, text="1", reply_to=None)
    with patch("rt.telegram.recall_channel.start_recall_via_telegram") as start:
        asyncio.run(handle_text(update, _context(state_dir)))
    start.assert_not_called()
