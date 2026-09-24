"""Interfaccia web locale di RT: dashboard, review e configurazione."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Optional

import gradio as gr

from rt.pipeline.review_actions import submit_review_decision, undo_web_decision
from rt.tui.data import LessonSummary
from rt.web.data import (
    IssueDetail, configuration_summary, issue_choices, issue_detail, lesson_card,
    lesson_audio_path, lesson_preview_html, lesson_stats, lessons_root, list_lessons,
    sidebar_lessons,
)
from rt.web.ingest import ingest_audio

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSS = (Path(__file__).with_name("style.css")).read_text(encoding="utf-8")
CARD_JS = """
element.addEventListener('click', event => {
  if (event.target.closest('[data-open-review]')) trigger('open_review');
});
"""
PREVIEW_JS = """
const wireTimecodes = () => {
  const article = element.querySelector('.rt-document');
  if (!article) return;
  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  const matches = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement.closest('a, button, code, pre')) continue;
    if (/(?:\\d{1,2}:)?\\d{2}:\\d{2}/.test(node.textContent)) matches.push(node);
  }
  for (const node of matches) {
    const text = node.textContent;
    const pattern = /(?:\\d{1,2}:)?\\d{2}:\\d{2}/g;
    const fragment = document.createDocumentFragment();
    let last = 0;
    for (const match of text.matchAll(pattern)) {
      fragment.append(document.createTextNode(text.slice(last, match.index)));
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'rt-timecode';
      button.textContent = match[0];
      button.title = 'Vai a questo punto nell’audio';
      const parts = match[0].split(':').map(Number);
      button.dataset.seconds = String(parts.reduce((sum, part) => sum * 60 + part, 0));
      fragment.append(button);
      last = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(last)));
    node.replaceWith(fragment);
  }
};
wireTimecodes();
watch('value', () => requestAnimationFrame(wireTimecodes));
let seekSequence = 0;
const displayedSeconds = () => {
  const time = document.querySelector('#rt-lesson-audio #time')?.textContent?.trim();
  if (!time) return null;
  return time.split(':').map(Number).reduce((sum, part) => sum * 60 + part, 0);
};
const playAfterSeek = (seconds, sequence) => {
  const deadline = Date.now() + 15000;
  const check = () => {
    if (sequence !== seekSequence) return;
    if (displayedSeconds() === seconds) {
      document.querySelector('#rt-lesson-audio button[aria-label="Play"]')?.click();
    } else if (Date.now() < deadline) {
      requestAnimationFrame(check);
    }
  };
  requestAnimationFrame(check);
};
element.addEventListener('click', event => {
  const button = event.target.closest('button.rt-timecode');
  if (!button) return;
  const seconds = Number(button.dataset.seconds);
  const sequence = ++seekSequence;
  if (displayedSeconds() !== seconds) trigger('seek', { seconds });
  playAfterSeek(seconds, sequence);
});
"""
RESIZE_JS = """
const handle = element.querySelector('.rt-resize-handle');
const sidebar = element.closest('#rt-sidebar');
if (handle && sidebar) {
  const layout = sidebar.closest('.sidebar-parent');
  sidebar.appendChild(handle);
  handle.addEventListener('pointerdown', event => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (!handle.hasPointerCapture(event.pointerId)) return;
    const width = Math.max(220, Math.min(420, event.clientX - sidebar.getBoundingClientRect().left));
    layout?.style.setProperty('--rt-sidebar-width', `${width}px`);
  });
}
"""
SIDEBAR_JS = """
element.addEventListener('click', event => {
  const button = event.target.closest('button[data-lesson-path]');
  if (!button) return;
  for (const lesson of element.querySelectorAll('button[data-lesson-path]')) {
    const active = lesson === button;
    lesson.classList.toggle('active', active);
    lesson.setAttribute('aria-current', active ? 'page' : 'false');
  }
  trigger('lesson_selected', { lesson_dir: button.dataset.lessonPath });
});
"""


def _selected(lessons: list[LessonSummary], lesson_dir: Optional[str]) -> Optional[LessonSummary]:
    return next((lesson for lesson in lessons if lesson.dir_path == lesson_dir), None)


def _seek_audio(evt: gr.EventData):
    seconds = max(0.0, float(evt.seconds))
    return gr.update(playback_position=seconds)


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
        lesson_card(lesson), lesson_preview_html(lesson),
        gr.update(value=lesson_audio_path(lesson), playback_position=0),
        gr.update(choices=choices, value=issue_id),
        *_review_values(issue_detail(lesson, issue_id)),
    )


def _review_view(root: str, lesson_dir: Optional[str], issue_id: Optional[str]):
    return _review_values(issue_detail(_selected(list_lessons(root), lesson_dir), issue_id))


def _refresh_view(root: str, current: Optional[str]):
    lessons = list_lessons(root)
    available = {lesson.dir_path for lesson in lessons}
    selected = current if current in available else (lessons[0].dir_path if lessons else None)
    return lesson_stats(lessons), selected, sidebar_lessons(lessons, selected), *_selection_view(root, selected)


def _select_view(root: str, evt: gr.EventData):
    lesson = _require_lesson(root, evt.lesson_dir)
    return (lesson.dir_path, *_selection_view(root, lesson.dir_path),
            gr.update(selected="dashboard"))


def _decision_view(root: str, lesson_dir: Optional[str], issue_id: Optional[str], action: str,
                   edited_text: Optional[str] = None):
    try:
        lesson = _require_lesson(root, lesson_dir)
        if not issue_id:
            raise ValueError("Seleziona una issue da valutare.")
        if action == "undo":
            undo_web_decision(lesson.dir_path, issue_id)
            status = f"↶ Decisione {issue_id} riaperta. Operazione registrata nel log della lezione."
        else:
            submit_review_decision(lesson.dir_path, issue_id, action, edited_text)
            labels = {"accepted": "accettata", "rejected": "rifiutata", "edited": "modificata"}
            status = f"✓ Issue {issue_id} {labels[action]}. Decisione salvata nel ledger e nel log."
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc

    lessons = list_lessons(root)
    lesson = _selected(lessons, lesson_dir)
    choices, next_issue = issue_choices(lesson)
    if lesson and lesson.pending_issues == 0:
        next_issue = issue_id
    detail = issue_detail(lesson, next_issue)
    return (
        lesson_stats(lessons), lesson_card(lesson), lesson_preview_html(lesson),
        gr.update(choices=choices, value=next_issue), *_review_values(detail, status),
    )


def _ingest_view(root: str, audio_path: Optional[str], recorded: str, subject: str,
                 topics: str, transcribe: bool):
    try:
        lesson_dir = ingest_audio(audio_path, root, recorded, subject, topics, transcribe)
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc
    lessons = list_lessons(root)
    label = "importata e trascritta" if transcribe else "importata; trascrizione da eseguire"
    status = f"Lezione {label}: **{Path(lesson_dir).name}**"
    return (
        status, lesson_dir, sidebar_lessons(lessons, lesson_dir),
        lesson_stats(lessons), *_selection_view(root, lesson_dir),
        gr.update(selected="dashboard"),
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
        with gr.Sidebar(label="Navigazione", width=280, elem_id="rt-sidebar"):
            sidebar_list = gr.HTML(sidebar_lessons(lessons, selected), js_on_load=SIDEBAR_JS,
                                   apply_default_css=False,
                                   elem_id="rt-lesson-list")
            refresh = gr.Button("↻ Aggiorna lezioni", variant="secondary", size="sm")
            gr.HTML('<div class="rt-resize-handle" title="Trascina per regolare la larghezza"></div>',
                    js_on_load=RESIZE_JS)

        picker = gr.Textbox(value=selected or "", visible=False)

        with gr.Row(elem_id="rt-header"):
            gr.HTML('<div class="rt-brand"><h1>rt<span>.</span></h1>'
                    '<p>Le tue lezioni, dall’audio agli appunti pronti per lo studio.</p></div>', scale=1)
            go_upload = gr.Button("＋ Importa audio", variant="primary", size="sm", scale=0,
                                  elem_id="rt-upload-nav")
            go_config = gr.Button("⚙ Configurazione", variant="secondary", size="sm", scale=0,
                                  elem_id="rt-config-nav")

        with gr.Tabs(selected="dashboard", elem_id="rt-pages") as pages:
            with gr.Tab("Dashboard", id="dashboard"):
                stats = gr.HTML(lesson_stats(lessons))
                card = gr.HTML(lesson_card(initial_lesson), js_on_load=CARD_JS,
                               apply_default_css=False, elem_id="rt-lesson-card")
                preview = gr.HTML(lesson_preview_html(initial_lesson), js_on_load=PREVIEW_JS,
                                  elem_id="rt-preview")
                lesson_audio = gr.Audio(value=lesson_audio_path(initial_lesson), label="Audio della lezione",
                                        interactive=False, buttons=[], elem_id="rt-lesson-audio")
            with gr.Tab("Review", id="review"):
                back_review = gr.Button("← Dashboard", size="sm", elem_classes="rt-back")
                issue_picker = gr.Dropdown(
                    choices=initial_choices, value=initial_issue, label="Issue da valutare",
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
            with gr.Tab("Configurazione", id="config"):
                back_config = gr.Button("← Dashboard", size="sm", elem_classes="rt-back")
                gr.HTML(configuration_summary(root))
                gr.HTML('<div class="rt-note">Le chiavi API non vengono mostrate. Le impostazioni si modificano ancora con il wizard CLI.</div>')
            with gr.Tab("Importa audio", id="upload"):
                back_upload = gr.Button("← Dashboard", size="sm", elem_classes="rt-back")
                gr.Markdown("## Nuova lezione\nCarica un file audio: RT creerà la cartella della lezione senza toccare quelle esistenti.")
                upload_file = gr.File(label="File audio", file_types=[".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"])
                with gr.Row():
                    upload_date = gr.Textbox(value=date.today().isoformat(), label="Data della lezione (AAAA-MM-GG)")
                    upload_subject = gr.Textbox(label="Materia")
                upload_topics = gr.Textbox(label="Argomenti (facoltativo)")
                upload_transcribe = gr.Checkbox(value=True, label="Trascrivi subito con macparakeet-cli")
                upload_submit = gr.Button("Crea lezione", variant="primary")
                upload_status = gr.Markdown()

        review_outputs = [issue_header, original, suggested, diff_view, explanation, source_quote,
                          unit_text, audio_player, accept, reject, modify, undo, editor,
                          save_edit, cancel_edit, action_status]
        view_outputs = [card, preview, lesson_audio, issue_picker, *review_outputs]
        decision_outputs = [stats, card, preview, issue_picker, *review_outputs]

        def select_sidebar(evt: gr.EventData):
            return _select_view(root, evt)

        sidebar_list.lesson_selected(select_sidebar,
                                     outputs=[picker, *view_outputs, pages],
                                     show_progress="hidden")
        issue_picker.input(lambda path, issue_id: _review_view(root, path, issue_id),
                           inputs=[picker, issue_picker], outputs=review_outputs,
                           show_progress="hidden")
        refresh.click(lambda path: _refresh_view(root, path), inputs=picker,
                      outputs=[stats, picker, sidebar_list, *view_outputs], show_progress="hidden")
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
        back_review.click(lambda: gr.update(selected="dashboard"), outputs=pages, show_progress="hidden")
        back_config.click(lambda: gr.update(selected="dashboard"), outputs=pages, show_progress="hidden")
        back_upload.click(lambda: gr.update(selected="dashboard"), outputs=pages, show_progress="hidden")
        go_upload.click(lambda: gr.update(selected="upload"), outputs=pages, show_progress="hidden")
        go_config.click(lambda: gr.update(selected="config"), outputs=pages, show_progress="hidden")
        card.open_review(lambda: gr.update(selected="review"), outputs=pages, show_progress="hidden")
        preview.seek(_seek_audio, outputs=lesson_audio, show_progress="hidden")
        upload_submit.click(
            lambda file, recorded, subject, topics, transcribe: _ingest_view(
                root, file, recorded, subject, topics, transcribe,
            ),
            inputs=[upload_file, upload_date, upload_subject, upload_topics, upload_transcribe],
            outputs=[upload_status, picker, sidebar_list, stats, *view_outputs, pages],
        )
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
        theme=gr.themes.Soft(
            primary_hue="teal", neutral_hue="slate",
            font=["Seravek", "Helvetica Neue", "Arial", "sans-serif"],
        ), css=CSS,
    )


if __name__ == "__main__":
    main()
