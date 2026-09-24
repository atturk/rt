"""Prototipo Gradio locale di RT: dashboard, review e configurazione in sola lettura."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import gradio as gr

from rt.tui.data import LessonSummary
from rt.web.data import (
    configuration_summary, issue_choices, issue_detail, lesson_card, lesson_preview,
    lesson_stats, lessons_root, list_lessons, picker_choices,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSS = (Path(__file__).with_name("style.css")).read_text(encoding="utf-8")


def _selected(lessons: list[LessonSummary], lesson_dir: Optional[str]) -> Optional[LessonSummary]:
    return next((lesson for lesson in lessons if lesson.dir_path == lesson_dir), None)


def _selection_view(root: str, lesson_dir: Optional[str]):
    lesson = _selected(list_lessons(root), lesson_dir)
    choices, issue_id = issue_choices(lesson)
    heading, source, proposal, reason, audio = issue_detail(lesson, issue_id)
    return (
        lesson_card(lesson), lesson_preview(lesson),
        gr.update(choices=choices, value=issue_id), heading, source, proposal,
        f"**Motivo**\n\n{reason}", audio,
    )


def build_app(root: str) -> gr.Blocks:
    """Costruisce una UI con le stesse lezioni lette dalla dashboard di RT."""
    root = str(Path(root).expanduser().resolve())
    lessons = list_lessons(root)
    selected = next((lesson.dir_path for lesson in lessons if lesson.pending_issues),
                    lessons[0].dir_path if lessons else None)
    initial_card, initial_preview, _, heading, source, proposal, reason, audio = _selection_view(root, selected)
    initial_choices, initial_issue = issue_choices(_selected(lessons, selected))

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
                gr.HTML('<div class="rt-note">Prototipo locale: i dati delle lezioni sono letti direttamente da RT. Nessuna decisione viene salvata.</div>')
            with gr.Column(scale=8, min_width=520, elem_id="rt-main"):
                with gr.Tabs():
                    with gr.Tab("Dashboard"):
                        stats = gr.HTML(lesson_stats(lessons))
                        card = gr.HTML(initial_card)
                        gr.HTML('<h3 class="rt-section-title">Anteprima appunti</h3>')
                        preview = gr.Markdown(initial_preview, elem_id="rt-preview")
                    with gr.Tab("Review"):
                        issue_picker = gr.Dropdown(
                            choices=initial_choices, value=initial_issue, label="Questione da valutare",
                            filterable=True,
                        )
                        issue_header = gr.HTML(heading)
                        with gr.Row():
                            original = gr.Textbox(value=source, label="Fonte / passaggio da verificare",
                                                  lines=7, interactive=False, elem_id="rt-review-source")
                            suggested = gr.Textbox(value=proposal, label="Proposta RT / testo convalidato",
                                                   lines=7, interactive=False, elem_id="rt-review-proposal")
                        explanation = gr.Markdown(reason)
                        audio_player = gr.Audio(value=audio, label="Ascolta il passaggio", interactive=False,
                                                buttons=[], format="wav")
                        with gr.Row():
                            gr.Button("Accetta", interactive=False, variant="primary")
                            gr.Button("Rifiuta", interactive=False)
                            gr.Button("Modifica", interactive=False)
                        gr.HTML('<div class="rt-note">Le decisioni saranno abilitate quando questa schermata userà il ledger condiviso con CLI e Telegram.</div>')
                    with gr.Tab("Configurazione"):
                        gr.HTML(configuration_summary(root))
                        gr.HTML('<div class="rt-note">Le chiavi API non vengono mostrate. Il salvataggio delle impostazioni arriverà dopo l’estrazione della logica dal wizard CLI.</div>')

        view_outputs = [card, preview, issue_picker, issue_header, original, suggested, explanation, audio_player]
        picker.input(lambda path: _selection_view(root, path), inputs=picker, outputs=view_outputs,
                     show_progress="hidden")
        issue_picker.input(
            lambda path, issue_id: _review_view(root, path, issue_id),
            inputs=[picker, issue_picker],
            outputs=[issue_header, original, suggested, explanation, audio_player],
            show_progress="hidden",
        )
        refresh.click(lambda path: _refresh_view(root, path),
                      inputs=picker, outputs=[stats, picker, *view_outputs], show_progress="hidden")
    return demo


def _review_view(root: str, lesson_dir: Optional[str], issue_id: Optional[str]):
    heading, source, proposal, reason, audio = issue_detail(_selected(list_lessons(root), lesson_dir), issue_id)
    return heading, source, proposal, f"**Motivo**\n\n{reason}", audio


def _refresh_view(root: str, current: Optional[str]):
    lessons = list_lessons(root)
    choices = picker_choices(lessons)
    available = {path for _, path in choices}
    selected = current if current in available else (choices[0][1] if choices else None)
    return lesson_stats(lessons), gr.update(choices=choices, value=selected), *_selection_view(root, selected)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Prototipo web locale di RT")
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
