"""Interfaccia web locale di RT: dashboard, review e configurazione."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import gradio as gr

from rt.pipeline.review_actions import submit_review_decision, undo_web_decision
from rt.tui.data import LessonSummary
from rt.web.data import (
    IssueDetail, configuration_summary, issue_choices, issue_detail, lesson_card,
    lesson_preview, lesson_stats, lessons_root, list_lessons, picker_choices,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSS = (Path(__file__).with_name("style.css")).read_text(encoding="utf-8")


def _selected(lessons: list[LessonSummary], lesson_dir: Optional[str]) -> Optional[LessonSummary]:
    return next((lesson for lesson in lessons if lesson.dir_path == lesson_dir), None)


def _require_lesson(root: str, lesson_dir: Optional[str]) -> LessonSummary:
    lesson = _selected(list_lessons(root), lesson_dir)
    if lesson is None or not Path(lesson.dir_path).resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Seleziona una lezione nella cartella configurata.")
    return lesson


def _review_values(detail: IssueDetail, status: str = ""):
    return (
        detail.heading, detail.claim, detail.proposal, detail.diff,
        f"**Motivo**\n\n{detail.reason}" if detail.reason else "",
        detail.source_quote, detail.unit_text, detail.audio,
        gr.update(interactive=detail.can_accept), gr.update(interactive=detail.can_reject),
        gr.update(interactive=detail.can_edit), gr.update(interactive=detail.can_undo),
        gr.update(value=detail.editor_initial, visible=False),
        gr.update(visible=False), gr.update(visible=False),
        gr.update(value=status, visible=bool(status)),
    )


def _selection_view(root: str, lesson_dir: Optional[str]):
    lesson = _selected(list_lessons(root), lesson_dir)
    choices, issue_id = issue_choices(lesson)
    return (
        lesson_card(lesson), lesson_preview(lesson),
        gr.update(choices=choices, value=issue_id),
        *_review_values(issue_detail(lesson, issue_id)),
    )


def _review_view(root: str, lesson_dir: Optional[str], issue_id: Optional[str]):
    return _review_values(issue_detail(_selected(list_lessons(root), lesson_dir), issue_id))


def _refresh_view(root: str, current: Optional[str]):
    lessons = list_lessons(root)
    choices = picker_choices(lessons)
    available = {path for _, path in choices}
    selected = current if current in available else (choices[0][1] if choices else None)
    return lesson_stats(lessons), gr.update(choices=choices, value=selected), *_selection_view(root, selected)


def _decision_view(root: str, lesson_dir: Optional[str], issue_id: Optional[str], action: str,
                   edited_text: Optional[str] = None):
    try:
        lesson = _require_lesson(root, lesson_dir)
        if not issue_id:
            raise ValueError("Seleziona una questione da valutare.")
        if action == "undo":
            undo_web_decision(lesson.dir_path, issue_id)
            status = f"↶ Decisione {issue_id} riaperta. Operazione registrata nel log della lezione."
        else:
            submit_review_decision(lesson.dir_path, issue_id, action, edited_text)
            labels = {"accepted": "accettata", "rejected": "rifiutata", "edited": "modificata"}
            status = f"✓ Questione {issue_id} {labels[action]}. Decisione salvata nel ledger e nel log."
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc

    lessons = list_lessons(root)
    lesson = _selected(lessons, lesson_dir)
    choices, next_issue = issue_choices(lesson)
    if lesson and lesson.pending_issues == 0:
        next_issue = issue_id
    detail = issue_detail(lesson, next_issue)
    return (
        lesson_stats(lessons), lesson_card(lesson), lesson_preview(lesson),
        gr.update(choices=choices, value=next_issue), *_review_values(detail, status),
    )


def build_app(root: str) -> gr.Blocks:
    """Costruisce una UI che legge e aggiorna le stesse lezioni usate da RT."""
    root = str(Path(root).expanduser().resolve())
    lessons = list_lessons(root)
    selected = next((lesson.dir_path for lesson in lessons if lesson.pending_issues),
                    lessons[0].dir_path if lessons else None)
    initial_lesson = _selected(lessons, selected)
    initial_choices, initial_issue = issue_choices(initial_lesson)
    initial_detail = issue_detail(initial_lesson, initial_issue)

    with gr.Blocks(title="RT · Lezioni", analytics_enabled=False, fill_width=True) as demo:
        gr.HTML('<div id="rt-header"><h1>rt<span style="color:#138a78">.</span></h1>'
                '<p>Le tue lezioni, dall’audio agli appunti pronti per lo studio.</p></div>')
        with gr.Row(equal_height=False):
            with gr.Column(scale=3, min_width=270, elem_id="rt-sidebar"):
                gr.HTML('<h3>Lezioni</h3>')
                picker = gr.Dropdown(
                    choices=picker_choices(lessons), value=selected, label="Scegli o cerca una lezione",
                    filterable=True, elem_id="lesson-picker",
                )
                refresh = gr.Button("Aggiorna elenco", variant="secondary", size="sm")
                gr.HTML('<div class="rt-note">La review salva nel ledger RT. Ogni azione dalla GUI viene registrata anche nel log della lezione.</div>')
            with gr.Column(scale=8, min_width=520, elem_id="rt-main"):
                with gr.Tabs():
                    with gr.Tab("Dashboard"):
                        stats = gr.HTML(lesson_stats(lessons))
                        card = gr.HTML(lesson_card(initial_lesson))
                        gr.HTML('<h3 class="rt-section-title">Anteprima appunti</h3>')
                        preview = gr.Markdown(lesson_preview(initial_lesson), elem_id="rt-preview")
                    with gr.Tab("Review"):
                        issue_picker = gr.Dropdown(
                            choices=initial_choices, value=initial_issue, label="Questione da valutare",
                            filterable=True,
                        )
                        action_status = gr.Markdown(visible=False, elem_id="rt-action-status")
                        issue_header = gr.HTML(initial_detail.heading)
                        with gr.Row():
                            original = gr.Textbox(value=initial_detail.claim, label="Affermazione da valutare",
                                                  lines=5, interactive=False, elem_id="rt-review-source")
                            suggested = gr.Textbox(value=initial_detail.proposal, label="Correzione proposta / testo deciso",
                                                   lines=5, interactive=False, elem_id="rt-review-proposal")
                        diff_view = gr.HTML(initial_detail.diff)
                        explanation = gr.Markdown(f"**Motivo**\n\n{initial_detail.reason}")
                        with gr.Accordion("Contesto: unità completa e trascrizione sorgente", open=False):
                            unit_text = gr.Textbox(value=initial_detail.unit_text, label="Unità completa",
                                                   lines=14, max_lines=18, interactive=False)
                            source_quote = gr.Textbox(value=initial_detail.source_quote,
                                                      label="Citazione della trascrizione originale",
                                                      lines=5, interactive=False)
                        audio_player = gr.Audio(value=initial_detail.audio, label="Ascolta il passaggio",
                                                interactive=False, buttons=[], format="wav")
                        with gr.Row():
                            accept = gr.Button("Accetta", interactive=initial_detail.can_accept, variant="primary")
                            reject = gr.Button("Mantieni originale", interactive=initial_detail.can_reject)
                            modify = gr.Button("Modifica…", interactive=initial_detail.can_edit)
                            undo = gr.Button("Riapri decisione", interactive=initial_detail.can_undo)
                        editor = gr.Textbox(value=initial_detail.editor_initial, label="Testo corretto",
                                            lines=8, visible=False)
                        with gr.Row():
                            save_edit = gr.Button("Salva modifica", variant="primary", visible=False)
                            cancel_edit = gr.Button("Annulla modifica", visible=False)
                    with gr.Tab("Configurazione"):
                        gr.HTML(configuration_summary(root))
                        gr.HTML('<div class="rt-note">Le chiavi API non vengono mostrate. Il salvataggio delle impostazioni arriverà dopo l’estrazione della logica dal wizard CLI.</div>')

        review_outputs = [issue_header, original, suggested, diff_view, explanation, source_quote,
                          unit_text, audio_player, accept, reject, modify, undo, editor,
                          save_edit, cancel_edit, action_status]
        view_outputs = [card, preview, issue_picker, *review_outputs]
        decision_outputs = [stats, card, preview, issue_picker, *review_outputs]

        picker.input(lambda path: _selection_view(root, path), inputs=picker, outputs=view_outputs,
                     show_progress="hidden")
        issue_picker.input(lambda path, issue_id: _review_view(root, path, issue_id),
                           inputs=[picker, issue_picker], outputs=review_outputs,
                           show_progress="hidden")
        refresh.click(lambda path: _refresh_view(root, path), inputs=picker,
                      outputs=[stats, picker, *view_outputs], show_progress="hidden")
        accept.click(lambda path, issue: _decision_view(root, path, issue, "accepted"),
                     inputs=[picker, issue_picker], outputs=decision_outputs)
        reject.click(lambda path, issue: _decision_view(root, path, issue, "rejected"),
                     inputs=[picker, issue_picker], outputs=decision_outputs)
        undo.click(lambda path, issue: _decision_view(root, path, issue, "undo"),
                   inputs=[picker, issue_picker], outputs=decision_outputs)
        modify.click(lambda: (gr.update(visible=True), gr.update(visible=True), gr.update(visible=True)),
                     outputs=[editor, save_edit, cancel_edit], show_progress="hidden")
        cancel_edit.click(lambda: (gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)),
                          outputs=[editor, save_edit, cancel_edit], show_progress="hidden")
        save_edit.click(lambda path, issue, text: _decision_view(root, path, issue, "edited", text),
                        inputs=[picker, issue_picker, editor], outputs=decision_outputs)
    return demo


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Interfaccia web locale di RT")
    parser.add_argument("--lessons-root", default=None, help="Cartella delle lezioni (default: configurazione RT)")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true", help="Non aprire automaticamente il browser")
    args = parser.parse_args(argv)
    root = args.lessons_root or lessons_root()
    if not root or not Path(root).is_dir():
        parser.error("Configura telegram.lessons_root o passa --lessons-root con una cartella esistente.")
    blocked = [str(PROJECT_ROOT / name) for name in (".env", "config", ".rt_telegram", ".agents", ".claude")]
    blocked.append(str(Path(root).resolve()))
    build_app(root).launch(
        server_name="127.0.0.1", server_port=args.port, inbrowser=not args.no_browser,
        share=False, show_error=True, blocked_paths=blocked,
        theme=gr.themes.Soft(primary_hue="teal", neutral_hue="slate"), css=CSS,
    )


if __name__ == "__main__":
    main()
