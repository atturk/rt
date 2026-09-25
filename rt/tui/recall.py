"""
rt.tui.recall
Active Recall da terminale: sessione interattiva ('rt recall --channel terminal') e
revisione delle domande stale ('rt recall --check', app Textual). La logica di sessione è
in rt.services.recall_service.
"""
import os
import sys
from typing import Any, List, Optional, Tuple

from textual.app import App, ComposeResult
from textual.widgets import Static
from rich.panel import Panel
from rich.text import Text
from rt.core.encoding import fix_mojibake
from rt.core.models import RecallQuestionType
from rt.core.lesson_paths import lesson_path
from rt.services import recall_service


def run_recall_terminal_session(lesson_dir: str, order: str = "alternato", style: Optional[str] = None, force_mock: bool = False) -> None:
    from rt.core.editor_edit import edit_text_in_editor
    from rt.core.config import load_config
    from rt.telegram import recall_preferences
    from rt.pipeline.recall import (
        record_recall_answer, record_recall_vote,
        record_fewshot_vote, evaluate_recall_answer, skip_recall_question,
    )

    cfg = load_config()
    state_dir = cfg.telegram.state_dir
    if style:
        recall_preferences.set_active_style(state_dir, style)
    active_style = recall_preferences.get_active_style(state_dir)
    qtype = RecallQuestionType(active_style)

    if not sys.stdin.isatty():
        print("⚠️  Terminale non interattivo: il recall da terminale richiede un TTY. Usa --channel telegram.")
        return

    recall_service.ensure_initial_batch(lesson_dir, force_mock=force_mock)

    print(f"\n🧠 SESSIONE DI ACTIVE RECALL — stile: {active_style}, ordine: {order}")
    print("=" * 60)

    unit_cursor: Optional[str] = None
    exclude_id: Optional[str] = None
    interrupted = False

    try:
        while not interrupted:
            question = recall_service.next_question(
                lesson_dir, qtype, order, unit_cursor, exclude_id,
                cfg.telegram.recall.refill_batch_size, state_dir, force_mock=force_mock,
            )
            exclude_id = None
            if question is None:
                print(f"\n✨ Nessuna domanda '{active_style}' disponibile al momento. Cambia stile o riprova più tardi.")
                break

            if order == "alternato":
                unit_cursor = question.unit_ids[0]

            print(f"\n[{question.type.value.upper()}] Unità: {', '.join(question.unit_ids)}")
            print(f"  {question.question_text}")
            letters = ["A", "B", "C", "D"]
            if question.type == RecallQuestionType.QUIZ and question.options:
                for i, opt in enumerate(question.options):
                    print(f"  {letters[i]}) {opt}")

            if question.type == RecallQuestionType.QUIZ:
                print("\n  Azione [A/B/C/D=Scegli / 1=👍 / 2=👎 / 3=⚡ / S=Salta / Q=Esci]: ", end="", flush=True)
            else:
                print("\n  Azione [R=Rispondi (editor) / 1=👍 / 2=👎 / 3=⚡ / S=Salta / Q=Esci]: ", end="", flush=True)

            while True:
                try:
                    raw_key = input()
                except (EOFError, KeyboardInterrupt):
                    interrupted = True
                    break
                choice = raw_key.strip().lower()

                if question.type == RecallQuestionType.QUIZ and choice in ("a", "b", "c", "d"):
                    idx_choice = "abcd".index(choice)
                    is_correct = (question.correct_index == idx_choice)
                    record_recall_answer(
                        lesson_dir, question.id, question.options[idx_choice],
                        is_voice=False, evaluation=question.pregenerated_material,
                    )
                    esito = "✔ Corretto!" if is_correct else "❌ Sbagliato."
                    print(f"  {esito}")
                    if question.pregenerated_material:
                        print(f"  {question.pregenerated_material}")
                    break
                elif choice in ("r", "rispondi") and question.type != RecallQuestionType.QUIZ:
                    initial = f"# Scrivi qui la tua risposta. La riga con # viene ignorata.\n# Domanda: {question.question_text}\n\n"
                    edited = edit_text_in_editor(initial)
                    lines = [l for l in edited.splitlines() if not l.strip().startswith("#")]
                    answer_text = "\n".join(lines).strip()
                    if not answer_text:
                        print("  ⚠️ Nessuna risposta inserita.")
                        continue
                    print("  ⏳ Valutazione in corso...")
                    evaluation = evaluate_recall_answer(lesson_dir, question.id, answer_text, force_mock=force_mock)
                    record_recall_answer(lesson_dir, question.id, answer_text, is_voice=False, evaluation=evaluation)
                    print(f"\n{evaluation}\n")
                    break
                elif choice == "1":
                    record_recall_vote(lesson_dir, question.id, "up")
                    record_fewshot_vote(question.type, question.question_text, "up", state_dir=state_dir)
                    continue
                elif choice == "2":
                    record_recall_vote(lesson_dir, question.id, "down")
                    record_fewshot_vote(question.type, question.question_text, "down", state_dir=state_dir)
                    continue
                elif choice == "3":
                    record_recall_vote(lesson_dir, question.id, "lightning")
                    record_fewshot_vote(question.type, question.question_text, "lightning", state_dir=state_dir)
                    continue
                elif choice in ("s", "salta", "skip"):
                    print("  ⏭ Saltato.")
                    skip_recall_question(lesson_dir, question.id)
                    exclude_id = question.id
                    break
                elif choice in ("q", "esci", "quit"):
                    print("  ⏹ Sessione di recall interrotta.")
                    interrupted = True
                    break
                else:
                    continue

            # Rifornimento proattivo se sotto soglia
            recall_service.refill_if_low(
                lesson_dir, qtype, cfg.telegram.recall.refill_threshold,
                cfg.telegram.recall.refill_batch_size, state_dir, force_mock=force_mock,
            )
    except KeyboardInterrupt:
        print("\n  ⏹ Sessione di recall interrotta.")


class StaleRecallApp(App[None]):
    """Textual App per la revisione interattiva delle domande stale di active recall."""

    BINDINGS = [
        ("m", "keep", "Mantieni"),
        ("e", "delete", "Elimina"),
        ("s", "skip", "Salta"),
        ("right", "skip", "Salta"),
        ("b", "back", "Indietro"),
        ("left", "back", "Indietro"),
        ("q", "quit_session", "Esci"),
        ("ctrl+q", "quit_session", "Esci"),
        ("ctrl+c", "quit_session", "Esci"),
    ]

    def __init__(self, lesson_dir: str, stale_questions: List[Any]) -> None:
        super().__init__()
        from rt.core.ui_theme import apply_saved_theme
        apply_saved_theme(self)
        self.lesson_dir = lesson_dir
        self.stale_questions = stale_questions
        self.idx: int = 0
        self.history_stack: List[Tuple[str, Any, Any]] = []
        self.kept_count: int = 0
        self.deleted_count: int = 0
        self.skipped_count: int = 0
        self.last_status: Optional[str] = None
        self.interrupted: bool = False

    def compose(self) -> ComposeResult:
        yield Static(id="stale_view")

    def on_mount(self) -> None:
        self._update_view()

    def _render_panel(self) -> Panel:
        if self.idx >= len(self.stale_questions):
            return Panel(Text("Revisione completata."), title="Stale Recall Check", border_style="green")
        q = self.stale_questions[self.idx]
        from rt.pipeline.recall import load_recall_bank
        bank = load_recall_bank(self.lesson_dir)
        total_count = len(self.stale_questions)

        lines = [
            f"[{self.idx + 1}/{total_count}] STALE RECALL QUESTION ({q.type.value.upper()}) - ID: {q.id}",
            f"  📚 Unità: {', '.join(q.unit_ids)}",
            f"  📌 Stato: {q.status.value}",
            f"  ❓ Domanda: \"{fix_mojibake(q.question_text)}\"",
        ]
        if q.type == RecallQuestionType.QUIZ and q.options:
            lines.append("  📝 Opzioni:")
            for opt in q.options:
                lines.append(f"    - {fix_mojibake(opt)}")
        if q.pregenerated_material:
            lines.append(f"  💡 Spiegazione: {fix_mojibake(q.pregenerated_material)}")
        answers = [a for a in bank.answers if a.question_id == q.id]
        if answers:
            last_ans = answers[-1]
            lines.append(f"  💬 Ultima risposta registrata: \"{fix_mojibake(last_ans.answer_text)}\"")
            if last_ans.evaluation:
                lines.append(f"  ⭐ Ultima valutazione: {fix_mojibake(last_ans.evaluation)}")

        if self.last_status:
            lines.append(f"\n  {self.last_status}")

        lines.append("\n  Azione [M=Mantieni (aggiorna fingerprint) / E=Elimina domanda+risposte / S=Salta / B=Indietro / Q=Esci]: ")
        content = "\n".join(lines)
        return Panel(Text(content), title=f"Stale Recall Check [{self.idx + 1}/{total_count}]", border_style="yellow")

    def _update_view(self) -> None:
        try:
            widget = self.query_one("#stale_view", Static)
            widget.update(self._render_panel())
        except Exception:
            pass

    def action_keep(self) -> None:
        if self.idx >= len(self.stale_questions):
            return
        q = self.stale_questions[self.idx]
        from rt.pipeline.recall import load_recall_bank, save_recall_bank, _compute_units_fingerprint, recall_bank_lock
        old_fp = q.content_fingerprint
        cur_fp = _compute_units_fingerprint(self.lesson_dir, q.unit_ids)
        with recall_bank_lock(self.lesson_dir):
            b = load_recall_bank(self.lesson_dir)
            bq = next((item for item in b.questions if item.id == q.id), None)
            if bq:
                bq.content_fingerprint = cur_fp
                save_recall_bank(b, self.lesson_dir)
        self.history_stack.append(("kept", q.id, old_fp))
        self.kept_count += 1
        self.last_status = f"✔ Mantenuta domanda {q.id} (fingerprint aggiornato)."
        self.idx += 1
        if self.idx >= len(self.stale_questions):
            self.exit()
        else:
            self._update_view()

    def action_delete(self) -> None:
        if self.idx >= len(self.stale_questions):
            return
        q = self.stale_questions[self.idx]
        from rt.pipeline.recall import load_recall_bank, save_recall_bank, recall_bank_lock
        with recall_bank_lock(self.lesson_dir):
            b = load_recall_bank(self.lesson_dir)
            q_to_del = next((item for item in b.questions if item.id == q.id), None)
            a_to_del = [a for a in b.answers if a.question_id == q.id]
            b.questions = [item for item in b.questions if item.id != q.id]
            b.answers = [a for a in b.answers if a.question_id != q.id]
            save_recall_bank(b, self.lesson_dir)
        self.history_stack.append(("deleted", q_to_del or q, a_to_del))
        self.deleted_count += 1
        self.last_status = f"🗑 Eliminata domanda {q.id} e relative risposte."
        self.idx += 1
        if self.idx >= len(self.stale_questions):
            self.exit()
        else:
            self._update_view()

    def action_skip(self) -> None:
        if self.idx >= len(self.stale_questions):
            return
        q = self.stale_questions[self.idx]
        self.history_stack.append(("skipped", q.id, None))
        self.skipped_count += 1
        self.last_status = "⏭ Saltato."
        self.idx += 1
        if self.idx >= len(self.stale_questions):
            self.exit()
        else:
            self._update_view()

    def action_back(self) -> None:
        if self.idx == 0:
            self.last_status = "⚠️  Sei già al primo elemento, impossibile tornare oltre."
            self._update_view()
            return
        from rt.pipeline.recall import load_recall_bank, save_recall_bank, recall_bank_lock
        self.idx -= 1
        action_type, hist_q, hist_extra = self.history_stack.pop()
        with recall_bank_lock(self.lesson_dir):
            b = load_recall_bank(self.lesson_dir)
            if action_type == "kept":
                bq = next((item for item in b.questions if item.id == hist_q), None)
                if bq:
                    bq.content_fingerprint = hist_extra
                    save_recall_bank(b, self.lesson_dir)
                self.kept_count -= 1
            elif action_type == "deleted":
                if not any(item.id == hist_q.id for item in b.questions):
                    b.questions.append(hist_q)
                for a in hist_extra:
                    b.answers.append(a)
                save_recall_bank(b, self.lesson_dir)
                self.deleted_count -= 1
            elif action_type == "skipped":
                self.skipped_count -= 1
        prev_q = self.stale_questions[self.idx]
        self.last_status = f"◀️ Tornato alla domanda precedente ({prev_q.id})."
        self._update_view()


    def action_quit_session(self) -> None:
        self.last_status = "⏹ Revisione interrotta."
        self.interrupted = True
        self.exit()


def run_stale_recall_check(lesson_dir: str, state_dir: Optional[str] = None) -> None:
    """Revisione interattiva da terminale delle domande stale il cui content_fingerprint
    non corrisponde più al contenuto attuale delle unità didattiche."""
    from rt.core.config import load_config
    from rt.telegram import session as tg_session
    if not state_dir:
        state_dir = load_config().telegram.state_dir
    active = tg_session.get_active_session_for_lesson(state_dir, lesson_dir, kind="recall")
    if active is not None:
        print("ℹ️ C'è già una sessione Telegram attiva di recall per questa lezione. Usa /quit su Telegram per chiuderla prima di eseguire --check.")
        return

    stale_questions = recall_service.find_stale_questions(lesson_dir)

    if not stale_questions:
        print("Nessuna domanda da rivedere.")
        return

    if not sys.stdin.isatty():
        print(f"⚠️  [HUMAN REVIEW REQUIRED] Ci sono {len(stale_questions)} domande stale che richiedono revisione umana.")
        return

    print(f"\n🔍 REVISIONE DOMANDE STALE ({len(stale_questions)} da rivedere)")
    print("=" * 60)

    app = StaleRecallApp(lesson_dir=lesson_dir, stale_questions=stale_questions)
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n  ⏹ Sessione interrotta.")

    print(f"\n📊 Riepilogo revisione stale: {app.kept_count} mantenute, {app.deleted_count} eliminate, {app.skipped_count} saltate.")
