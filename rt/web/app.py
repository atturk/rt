"""Interfaccia web locale di RT: dashboard, review e configurazione."""
from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Optional

import gradio as gr
from starlette.middleware import Middleware

from rt.pipeline.review_actions import submit_review_decision, undo_web_decision
from rt.tui.data import LessonSummary
from rt.web.data import (
    configuration_summary, issue_action_state, issue_choices, issue_sidebar, lesson_card,
    lesson_audio_html, lesson_preview_html, lesson_stats, lessons_root, list_lessons,
    sidebar_lessons, web_audio_directory,
)
from rt.web.diagnostics import LOG, RequestLogMiddleware, configure_logging, default_log_file, log_action
from rt.web.ingest import ingest_audio
from rt.web.settings import (credential_names, general_config_path, route_round_robin_keys, route_settings,
                             save_credential, save_lessons_root, save_route, save_telegram,
                             save_transcription)
from rt.core.config import KNOWN_PROVIDER_DEFAULT_BASE_URLS, load_config, load_env_file
from rt.telegram.daemon_status import is_daemon_running

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
const focusIssue = () => {
  const anchor = element.querySelector('#rt-issue-anchor');
  if (anchor) anchor.scrollIntoView({ block: 'center', behavior: 'smooth' });
};
element.addEventListener('click', event => {
  const button = event.target.closest('[data-review-action]');
  if (!button) return;
  const text = element.querySelector('#rt-comment-edit')?.value || '';
  trigger('review_action', { action: button.dataset.reviewAction, text });
});
watch('value', () => requestAnimationFrame(() => { wireTimecodes(); focusIssue(); }));
"""
PLAYER_JS = (Path(__file__).with_name("player.js")).read_text(encoding="utf-8")
RESIZE_JS = """
const handle = element.querySelector('.rt-resize-handle');
const sidebar = element.closest('#rt-sidebar');
if (handle && sidebar) {
  const layout = sidebar.closest('.sidebar-parent');
  const backdrop = document.createElement('div');
  backdrop.id = 'rt-sidebar-backdrop';
  backdrop.setAttribute('aria-hidden', 'true');
  document.body.appendChild(backdrop);
  const syncBackdrop = () => backdrop.classList.toggle('visible', sidebar.classList.contains('open'));
  new MutationObserver(syncBackdrop).observe(sidebar, { attributes: true, attributeFilter: ['class'] });
  backdrop.addEventListener('click', () => {
    const toggle = sidebar.querySelector('button.toggle-button');
    if (toggle && !toggle.disabled) toggle.click();
  });
  syncBackdrop();
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
const sidebar = element.closest('#rt-sidebar');
const toggle = sidebar?.querySelector('button.toggle-button');
let pendingSelection = null;
let loadingTimeout = null;
const setLoading = loading => {
  sidebar?.classList.toggle('rt-sidebar-loading', loading);
  if (toggle) toggle.disabled = loading;
  for (const lesson of element.querySelectorAll('button[data-lesson-path]')) lesson.disabled = loading;
};
window.addEventListener('rt-selection-done', event => {
  if (event.detail.token !== pendingSelection) return;
  pendingSelection = null;
  clearTimeout(loadingTimeout);
  setLoading(false);
});
element.addEventListener('click', event => {
  const button = event.target.closest('button[data-lesson-path]');
  if (!button || pendingSelection) return;
  const token = crypto.randomUUID();
  pendingSelection = token;
  setLoading(true);
  for (const lesson of element.querySelectorAll('button[data-lesson-path]')) {
    const active = lesson === button;
    lesson.classList.toggle('active', active);
    lesson.setAttribute('aria-current', active ? 'page' : 'false');
  }
  trigger('lesson_selected', { lesson_dir: button.dataset.lessonPath, token });
  loadingTimeout = setTimeout(() => {
    if (pendingSelection !== token) return;
    pendingSelection = null;
    setLoading(false);
    trigger('client_log', { kind: 'lesson.timeout', message: 'La selezione della lezione ha superato 60 secondi' });
  }, 60000);
});
"""
ISSUE_SIDEBAR_JS = """
element.addEventListener('click', event => {
  const issue = event.target.closest('button[data-issue-id]');
  if (issue) trigger('issue_selected', { issue_id: issue.dataset.issueId });
  if (event.target.closest('button[data-open-issues-file]')) trigger('open_issues_file');
});
"""
SELECTION_DONE_JS = """
watch('value', () => window.dispatchEvent(new CustomEvent('rt-selection-done', {
  detail: { token: props.value }
})));
"""
BOT_JS = """
const setTitle = () => {
  const button = document.querySelector('#rt-bot-nav');
  if (button) {
    button.title = button.disabled ? 'Bot Telegram rilevato e in esecuzione' : 'Avvia il bot Telegram in background';
    button.setAttribute('aria-label', button.title);
  }
};
const watchBot = () => {
  const header = document.querySelector('#rt-header');
  if (!header) { requestAnimationFrame(watchBot); return; }
  setTitle();
  new MutationObserver(setTitle).observe(header, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['disabled'],
  });
};
watchBot();
"""


def _client_log(evt: gr.EventData) -> None:
    LOG.warning("Browser %s: %s", str(evt.kind)[:60], str(evt.message)[:1200])


def _bot_button():
    running = is_daemon_running()
    return gr.update(value="🤖", interactive=not running)


@log_action("telegram.avvia")
def _start_bot():
    if is_daemon_running():
        return _bot_button()
    load_env_file(override=True)
    if not os.environ.get("RT_TELEGRAM_BOT_TOKEN") or not os.environ.get("RT_TELEGRAM_CHAT_ID"):
        raise gr.Error("Salva prima token e Chat ID nella sezione Telegram.")
    logfile = default_log_file().with_name("telegram.log")
    logfile.parent.mkdir(parents=True, exist_ok=True)
    logfile.touch(mode=0o600, exist_ok=True)
    os.chmod(logfile, 0o600)
    with logfile.open("a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "rt.cli", "telegram-daemon"],
            cwd=general_config_path(PROJECT_ROOT).parent.parent,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    time.sleep(0.25)
    if process.poll() is not None:
        raise gr.Error(f"Il bot non si è avviato. Controlla {logfile}.")
    LOG.info("Bot Telegram avviato in background (PID %d); log: %s", process.pid, logfile)
    return _bot_button()


@log_action("telegram.ascolta_topic")
def _listen_topics(token_input: str, existing_rows: list[list[str]]):
    if is_daemon_running():
        raise gr.Error("Il bot è già in ascolto. Ferma il demone prima di cercare nuovi topic.")
    load_env_file()
    token = token_input.strip() or os.environ.get("RT_TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise gr.Error("Inserisci e salva prima il token del bot.")
    import requests
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                params={"timeout": 20, "limit": 50}, timeout=25)
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise gr.Error("Impossibile contattare Telegram per il rilevamento dei topic.") from None
    if response.status_code == 409:
        raise gr.Error("Un altro processo sta già ascoltando questo bot.")
    if not payload.get("ok"):
        raise gr.Error("Telegram non ha accettato la richiesta. Verifica token e permessi del bot.")
    messages = [item.get("message") or item.get("channel_post") for item in payload.get("result", [])]
    messages = [message for message in messages if isinstance(message, dict)]
    chats = {message.get("chat", {}).get("id") for message in messages}
    chats.discard(None)
    threads = {message.get("message_thread_id") for message in messages}
    threads.discard(None)
    rows = [list(row) for row in existing_rows or []
            if row and len(row) > 1 and (str(row[0]).strip() or str(row[1]).strip())]
    known = {str(row[1]) for row in rows}
    rows.extend([["", str(thread)] for thread in sorted(threads) if str(thread) not in known])
    status = (f"Rilevati {len(threads)} topic. Assegna una materia a ciascuno e salva."
              if threads else "Nessun topic rilevato. Invia un messaggio in un topic e riprova.")
    return status, str(next(iter(chats))) if len(chats) == 1 else "", rows or [["", ""]]


def _topic_from_link(link: str, existing_rows: list[list[str]], chat_input: str):
    from rt.pipeline.configure import parse_telegram_topic_link
    parsed = parse_telegram_topic_link(link)
    if parsed is None:
        raise gr.Error("Incolla un link a un messaggio del topic, per esempio https://t.me/c/1234567890/12/34.")
    chat_id, topic_id = parsed
    if chat_input.strip() and chat_input.strip() != str(chat_id):
        raise gr.Error("Questo topic appartiene a un gruppo diverso dal Chat ID configurato.")
    rows = [list(row) for row in existing_rows or []
            if row and len(row) > 1 and (str(row[0]).strip() or str(row[1]).strip())]
    if str(topic_id) not in {str(row[1]) for row in rows}:
        rows.append(["", str(topic_id)])
    return f"Topic {topic_id} rilevato. Assegna una materia e salva.", str(chat_id), rows, ""


def _selected(lessons: list[LessonSummary], lesson_dir: Optional[str]) -> Optional[LessonSummary]:
    return next((lesson for lesson in lessons if lesson.dir_path == lesson_dir), None)


def _require_lesson(root: str, lesson_dir: Optional[str]) -> LessonSummary:
    lesson = _selected(list_lessons(root), lesson_dir)
    if lesson is None or not Path(lesson.dir_path).resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Seleziona una lezione nella cartella configurata.")
    return lesson


def _selection_view(root: str, lesson_dir: Optional[str]):
    lesson = _selected(list_lessons(root), lesson_dir)
    choices, issue_id = issue_choices(lesson)
    return (
        lesson_card(lesson), lesson_preview_html(lesson),
        lesson_audio_html(lesson),
        gr.update(choices=choices, value=issue_id),
        issue_sidebar(lesson, issue_id),
    )


@log_action("review.issue")
def _select_issue(root: str, lesson_dir: Optional[str], grouping: str, evt: gr.EventData):
    lesson = _require_lesson(root, lesson_dir)
    choices, _ = issue_choices(lesson)
    if evt.issue_id not in {value for _, value in choices}:
        raise gr.Error("Issue non disponibile: aggiorna l'elenco.")
    return (gr.update(value=evt.issue_id), lesson_preview_html(lesson, evt.issue_id),
            issue_sidebar(lesson, evt.issue_id, grouping))


def _open_issues_file(root: str, lesson_dir: Optional[str]) -> None:
    lesson = _require_lesson(root, lesson_dir)
    from rt.pipeline.review import get_science_issues_path
    path = Path(get_science_issues_path(lesson.dir_path))
    if not path.is_file():
        raise gr.Error("File delle issue non trovato.")
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise gr.Error(f"Impossibile aprire il file: {exc}") from exc
    gr.Info("File delle issue aperto nell'app predefinita di questo computer.")


@log_action("review.apri")
def _open_review(root: str, lesson_dir: Optional[str], issue_id: Optional[str], grouping: str):
    lesson = _require_lesson(root, lesson_dir)
    return (gr.update(visible=True), lesson_preview_html(lesson, issue_id),
            issue_sidebar(lesson, issue_id, grouping))


@log_action("lezioni.aggiorna")
def _refresh_view(root: str, current: Optional[str]):
    lessons = list_lessons(root)
    available = {lesson.dir_path for lesson in lessons}
    selected = current if current in available else (lessons[0].dir_path if lessons else None)
    return (lesson_stats(lessons), selected, sidebar_lessons(lessons, selected),
            *_selection_view(root, selected), gr.update(visible=False))


@log_action("lezione.seleziona")
def _select_view(root: str, evt: gr.EventData):
    lesson = _require_lesson(root, evt.lesson_dir)
    return (lesson.dir_path, *_selection_view(root, lesson.dir_path),
            gr.update(visible=False), gr.update(selected="dashboard"), evt.token)


@log_action("review.decisione")
def _decision_view(root: str, lesson_dir: Optional[str], issue_id: Optional[str], action: str,
                   edited_text: Optional[str] = None, grouping: str = "unit"):
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
    return (
        lesson_stats(lessons), lesson_card(lesson), lesson_preview_html(lesson, next_issue),
        gr.update(choices=choices, value=next_issue), issue_sidebar(lesson, next_issue, grouping),
        gr.update(value=status, visible=True),
    )


def _review_action(root: str, lesson_dir: Optional[str], issue_id: Optional[str],
                   grouping: str, evt: gr.EventData):
    action = str(evt.action)
    if action not in {"accept", "reject", "undo"}:
        raise gr.Error("Azione di review non riconosciuta.")
    detail = issue_action_state(_require_lesson(root, lesson_dir), issue_id)
    if action == "accept":
        proposed = detail.editor_initial
        submitted = str(getattr(evt, "text", "") or "").strip()
        if not detail.can_accept:
            raise gr.Error("Questa issue non può essere accettata.")
        if not submitted:
            raise gr.Error("Inserisci il testo da applicare prima di accettare la issue.")
        if submitted != proposed.strip():
            action, proposed = "edited", submitted
        else:
            action, proposed = "accepted", None
    elif action == "reject":
        if not detail.can_reject:
            raise gr.Error("Questa issue non può essere rifiutata.")
        action, proposed = "rejected", None
    else:
        if not detail.can_undo:
            raise gr.Error("Questa decisione non può essere riaperta.")
        proposed = None
    return _decision_view(root, lesson_dir, issue_id, action, proposed, grouping)


@log_action("lezione.importa")
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
        gr.update(visible=False), gr.update(selected="dashboard"),
    )


def build_app(root: str, blocked_paths: Optional[list[str]] = None,
              root_override: bool = False) -> gr.Blocks:
    """Costruisce una UI che legge e aggiorna le stesse lezioni usate da RT."""
    root = str(Path(root).expanduser().resolve()) if root else ""
    blocked_paths = blocked_paths if blocked_paths is not None else []
    lessons = list_lessons(root)
    selected = next((lesson.dir_path for lesson in lessons if lesson.pending_issues),
                    lessons[0].dir_path if lessons else None)
    initial_lesson = _selected(lessons, selected)
    initial_choices, initial_issue = issue_choices(initial_lesson)
    cfg = load_config()
    load_env_file()
    jobs = sorted(cfg.llm)
    first_job = jobs[0] if jobs else ""
    first_route = route_settings(PROJECT_ROOT, first_job, "primary") if first_job else ("openrouter", "", "", "", False)
    topic_rows = [[subject, topic] for subject, topic in cfg.telegram.topics.items()]

    with gr.Blocks(title="RT · Lezioni", analytics_enabled=False, fill_width=True) as demo:
        with gr.Sidebar(label="Navigazione", width=280, open=False, elem_id="rt-sidebar"):
            sidebar_list = gr.HTML(sidebar_lessons(lessons, selected), js_on_load=SIDEBAR_JS,
                                   apply_default_css=False,
                                   elem_id="rt-lesson-list")
            refresh = gr.Button("↻ Aggiorna lezioni", variant="secondary", size="sm")
            gr.HTML('<div class="rt-resize-handle" title="Trascina per regolare la larghezza"></div>',
                    js_on_load=RESIZE_JS)

        picker = gr.Textbox(value=selected or "", visible=False)
        selection_done = gr.HTML("", js_on_load=SELECTION_DONE_JS, elem_id="rt-selection-done")

        with gr.Row(elem_id="rt-header"):
            gr.HTML('<div class="rt-brand"><h1>rt<span>.</span></h1>'
                    '<p>Le tue lezioni, dall’audio agli appunti pronti per lo studio.</p></div>', scale=1)
            go_upload = gr.Button("＋ Importa audio", variant="primary", size="sm", scale=0,
                                  elem_id="rt-upload-nav")
            bot_button = gr.Button("🤖",
                                   interactive=not is_daemon_running(), size="sm", scale=0,
                                   elem_id="rt-bot-nav")
            go_config = gr.Button("⚙" if root and Path(root).is_dir() else "←",
                                  variant="secondary", size="sm", scale=0,
                                  elem_id="rt-config-nav")
            gr.HTML('<span aria-hidden="true" style="display:none"></span>', js_on_load=BOT_JS)
        config_open = gr.State(not bool(root and Path(root).is_dir()))

        with gr.Tabs(selected="dashboard" if root and Path(root).is_dir() else "config",
                     elem_id="rt-pages") as pages:
            with gr.Tab("Dashboard", id="dashboard"):
                stats = gr.HTML(lesson_stats(lessons))
                card = gr.HTML(lesson_card(initial_lesson), js_on_load=CARD_JS,
                               apply_default_css=False, elem_id="rt-lesson-card")
                issue_picker = gr.Dropdown(choices=initial_choices, value=initial_issue,
                                           label="Issue selezionata", visible=False)
                with gr.Row(elem_id="rt-reading-layout"):
                    with gr.Column(scale=3, min_width=350):
                        preview = gr.HTML(lesson_preview_html(initial_lesson), js_on_load=PREVIEW_JS,
                                          elem_id="rt-preview")
                    with gr.Column(scale=1, min_width=270, visible=False,
                                   elem_id="rt-review-panel") as review_panel:
                        with gr.Row(elem_id="rt-review-panel-head"):
                            gr.Markdown("### Issue della lezione")
                            close_review = gr.Button("×", size="sm", scale=0,
                                                      elem_id="rt-review-close")
                        grouping = gr.Radio(choices=[("Per unità", "unit"), ("Per tipo", "type")],
                                            value="unit", label="Raggruppa", container=False)
                        action_status = gr.Markdown(visible=False, elem_id="rt-action-status")
                        issue_list = gr.HTML(issue_sidebar(initial_lesson, initial_issue),
                                             js_on_load=ISSUE_SIDEBAR_JS, elem_id="rt-issue-list")
                lesson_audio = gr.HTML(lesson_audio_html(initial_lesson), js_on_load=PLAYER_JS,
                                       elem_id="rt-lesson-audio")
            with gr.Tab("Configurazione", id="config"):
                with gr.Accordion("Lezioni", open=True):
                    gr.Markdown("Scegli una cartella esistente oppure indica dove crearne una nuova.")
                    root_input = gr.Textbox(value=root or str(Path.home() / "RT Lezioni"),
                                            label="Cartella delle lezioni", placeholder="~/RT Lezioni")
                    save_root = gr.Button("Usa questa cartella", variant="primary")
                    root_status = gr.Markdown(
                        "Configura la cartella per iniziare." if not root or not Path(root).is_dir() else "")
                with gr.Accordion("Modelli e provider", open=False):
                    gr.Markdown("Aggiungi una chiave. Rimane nel file `.env` locale e non viene mostrata dopo il salvataggio.")
                    with gr.Row():
                        key_provider = gr.Dropdown(choices=[("OpenRouter", "openrouter"),
                                                            ("Google AI Studio", "google"),
                                                            ("DeepSeek", "deepseek"),
                                                            ("OpenAI-compatible", "openai_compatible")],
                                                   value="openrouter", label="Provider")
                        key_name = gr.Textbox(label="Nome della chiave", placeholder="es. google_3")
                        key_value = gr.Textbox(label="Chiave API", type="password")
                    add_key = gr.Button("Salva chiave")
                    key_status = gr.Markdown()
                    gr.Markdown("Scegli il job e il ruolo del modello. Per il primario puoi selezionare più chiavi da alternare.")
                    with gr.Row():
                        model_job = gr.Dropdown(choices=jobs, value=first_job, label="Fase / job")
                        model_role = gr.Dropdown(
                            choices=[("Primario", "primary"), ("Secondario", "secondary"),
                                     ("Fallback: timeout", "timeout"),
                                     ("Fallback: limiti API", "rate_limit"),
                                     ("Fallback: sicurezza", "safety"),
                                     ("Fallback: autenticazione", "auth"),
                                     ("Fallback: altro", "generic")], value="primary", label="Ruolo")
                    with gr.Row():
                        model_provider = gr.Dropdown(
                            choices=[("OpenRouter", "openrouter"), ("Google AI Studio", "google"),
                                     ("DeepSeek", "deepseek"),
                                     ("OpenAI-compatible", "openai_compatible")],
                            value=first_route[0], label="Provider")
                        model_credential = gr.Dropdown(choices=credential_names(PROJECT_ROOT, first_route[0]),
                                                       value=first_route[1] or None, label="Chiave")
                    model_name = gr.Textbox(value=first_route[2], label="Nome / ID del modello")
                    model_base = gr.Textbox(value=first_route[3], label="Base URL",
                                             placeholder="Precompilato per i provider comuni")
                    model_rr = gr.Checkbox(value=first_route[4],
                                            label="Alterna più chiavi per il modello primario")
                    model_rr_keys = gr.Dropdown(
                        choices=credential_names(PROJECT_ROOT, first_route[0]),
                        value=route_round_robin_keys(PROJECT_ROOT, first_job) if first_job else [],
                        multiselect=True, visible=first_route[4],
                        label="Chiavi da alternare")
                    save_model = gr.Button("Salva modello", variant="primary")
                    model_status = gr.Markdown()
                with gr.Accordion("Telegram", open=False):
                    gr.Markdown("Aggiungi il bot al gruppo e imposta i topic per materia. "
                                "Per rilevarli, premi **Ascolta topic**, poi invia un messaggio nei topic "
                                "dal telefono. Il token resta salvato localmente.")
                    with gr.Row():
                        telegram_token = gr.Textbox(label="Token del bot", type="password",
                                                     placeholder="Lascia vuoto per mantenere quello salvato")
                        telegram_chat = gr.Textbox(value=os.environ.get("RT_TELEGRAM_CHAT_ID", ""),
                                                    label="Chat ID del gruppo")
                    telegram_topics = gr.Dataframe(value=topic_rows or [["", ""]],
                                                     headers=["Materia", "Topic ID"], type="array",
                                                     interactive=True, label="Topic per materia")
                    telegram_misc = gr.Textbox(value=str(cfg.telegram.misc_topic_id or ""),
                                                label="Topic generale (facoltativo)")
                    with gr.Row():
                        telegram_save = gr.Button("Salva Telegram", variant="primary")
                        telegram_listen = gr.Button("Ascolta topic per 20 secondi")
                    with gr.Row():
                        telegram_link = gr.Textbox(label="Link a un messaggio del topic (facoltativo)",
                                                    placeholder="https://t.me/c/1234567890/12/34")
                        telegram_add_link = gr.Button("Aggiungi dal link", size="sm")
                    telegram_status = gr.Markdown()
                with gr.Accordion("Trascrizione", open=False):
                    stt_engine = gr.Radio(choices=[("macparakeet (su questo Mac)", "macparakeet"),
                                                   ("Server OpenAI-compatible", "custom")],
                                          value=cfg.transcription.engine, label="Motore predefinito")
                    stt_base = gr.Textbox(value=cfg.transcription.base_url or "",
                                           label="Base URL del server STT",
                                           placeholder="http://localhost:8000/v1")
                    stt_model = gr.Textbox(value=cfg.transcription.model or "",
                                            label="ID modello STT")
                    stt_key = gr.Textbox(type="password", label="Chiave API (facoltativa)",
                                         placeholder="Lascia vuoto per mantenere quella salvata")
                    stt_save = gr.Button("Salva trascrizione", variant="primary")
                    stt_status = gr.Markdown()
                config_summary = gr.HTML(configuration_summary(root))
            with gr.Tab("Importa audio", id="upload"):
                back_upload = gr.Button("← Dashboard", size="sm", elem_classes="rt-back")
                gr.Markdown("## Nuova lezione\nCarica un file audio: RT creerà la cartella della lezione senza toccare quelle esistenti.")
                upload_file = gr.File(label="File audio", file_types=[".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"])
                with gr.Row():
                    upload_date = gr.Textbox(value=date.today().isoformat(), label="Data della lezione (AAAA-MM-GG)")
                    upload_subject = gr.Textbox(label="Materia")
                upload_topics = gr.Textbox(label="Argomenti (facoltativo)")
                upload_transcribe = gr.Checkbox(value=True, label="Trascrivi subito")
                upload_submit = gr.Button("Crea lezione", variant="primary")
                upload_status = gr.Markdown()

        view_outputs = [card, preview, lesson_audio, issue_picker, issue_list]
        decision_outputs = [stats, card, preview, issue_picker, issue_list, action_status]

        def select_sidebar(evt: gr.EventData):
            return _select_view(root, evt)

        def select_issue_from_sidebar(path: str, group: str, evt: gr.EventData):
            return _select_issue(root, path, group, evt)

        def act_on_review(path: str, issue: str, group: str, evt: gr.EventData):
            return _review_action(root, path, issue, group, evt)

        sidebar_list.lesson_selected(select_sidebar,
                                     outputs=[picker, *view_outputs, review_panel, pages, selection_done],
                                     show_progress="hidden")
        sidebar_list.client_log(_client_log, show_progress="hidden")
        lesson_audio.client_log(_client_log, show_progress="hidden")
        issue_list.issue_selected(select_issue_from_sidebar,
                                  inputs=[picker, grouping], outputs=[issue_picker, preview, issue_list],
                                  show_progress="hidden")
        issue_list.open_issues_file(lambda path: _open_issues_file(root, path),
                                    inputs=picker, show_progress="hidden")
        grouping.change(
            lambda path, issue, group: issue_sidebar(_selected(list_lessons(root), path), issue, group),
            inputs=[picker, issue_picker, grouping], outputs=issue_list, show_progress="hidden")
        preview.review_action(
            act_on_review,
            inputs=[picker, issue_picker, grouping], outputs=decision_outputs)
        refresh.click(lambda path: _refresh_view(root, path), inputs=picker,
                      outputs=[stats, picker, sidebar_list, *view_outputs, review_panel],
                      show_progress="hidden")
        close_review.click(
            lambda path: (gr.update(visible=False), lesson_preview_html(_selected(list_lessons(root), path))),
            inputs=picker, outputs=[review_panel, preview], show_progress="hidden")
        def toggle_config(open_now: bool):
            return (gr.update(selected="dashboard" if open_now else "config"),
                    gr.update(value="⚙" if open_now else "←"), not open_now)

        go_config.click(toggle_config, inputs=config_open,
                        outputs=[pages, go_config, config_open], show_progress="hidden")
        back_upload.click(lambda: (gr.update(selected="dashboard"), gr.update(value="⚙"), False),
                          outputs=[pages, go_config, config_open], show_progress="hidden")
        go_upload.click(lambda: (gr.update(selected="upload"), gr.update(value="⚙"), False),
                        outputs=[pages, go_config, config_open], show_progress="hidden")
        bot_button.click(_start_bot, outputs=bot_button)
        card.open_review(lambda path, issue, group: _open_review(root, path, issue, group),
                         inputs=[picker, issue_picker, grouping],
                         outputs=[review_panel, preview, issue_list],
                         show_progress="hidden")
        upload_submit.click(
            lambda file, recorded, subject, topics, transcribe: _ingest_view(
                root, file, recorded, subject, topics, transcribe,
            ),
            inputs=[upload_file, upload_date, upload_subject, upload_topics, upload_transcribe],
            outputs=[upload_status, picker, sidebar_list, stats, *view_outputs,
                     review_panel, pages],
        )

        def load_model_form(job: str, role: str):
            provider, credential, model, base_url, rr = route_settings(PROJECT_ROOT, job, role)
            return (provider, gr.update(choices=credential_names(PROJECT_ROOT, provider),
                                        value=credential or None), model, base_url, rr,
                    gr.update(choices=credential_names(PROJECT_ROOT, provider),
                              value=route_round_robin_keys(PROJECT_ROOT, job) if rr else [],
                              visible=rr))

        for control in (model_job, model_role):
            control.change(load_model_form, inputs=[model_job, model_role],
                           outputs=[model_provider, model_credential, model_name, model_base,
                                    model_rr, model_rr_keys],
                           show_progress="hidden")
        model_provider.change(
            lambda provider: (gr.update(choices=credential_names(PROJECT_ROOT, provider), value=None),
                              KNOWN_PROVIDER_DEFAULT_BASE_URLS.get(provider, ""),
                              gr.update(choices=credential_names(PROJECT_ROOT, provider), value=[])),
            inputs=model_provider, outputs=[model_credential, model_base, model_rr_keys],
            show_progress="hidden")
        model_rr.change(lambda enabled, role: gr.update(visible=enabled and role == "primary"),
                        inputs=[model_rr, model_role], outputs=model_rr_keys,
                        show_progress="hidden")
        key_provider.change(
            lambda provider: f"{provider}_{len(credential_names(PROJECT_ROOT, provider)) + 1}",
            inputs=key_provider, outputs=key_name, show_progress="hidden")

        @log_action("configurazione.chiave")
        def save_key_ui(provider: str, name: str, secret: str, current_provider: str,
                        current_rr_keys: list[str]):
            try:
                saved = save_credential(PROJECT_ROOT, provider, name, secret)
            except (OSError, ValueError) as exc:
                raise gr.Error(str(exc)) from None
            choices = credential_names(PROJECT_ROOT, current_provider)
            return ("", f"Chiave **{saved}** salvata localmente.",
                    gr.update(choices=choices,
                              value=saved if provider == current_provider else None),
                    gr.update(choices=choices,
                              value=[key for key in current_rr_keys or [] if key in choices]))

        add_key.click(save_key_ui, inputs=[key_provider, key_name, key_value,
                                           model_provider, model_rr_keys],
                      outputs=[key_value, key_status, model_credential, model_rr_keys])

        @log_action("configurazione.modello")
        def save_model_ui(job: str, role: str, provider: str, credential: str,
                          model: str, base_url: str, rr: bool, rr_keys: list[str]):
            try:
                status = save_route(PROJECT_ROOT, job, role, provider, credential,
                                    model, base_url, rr, rr_keys)
            except (OSError, ValueError, KeyError) as exc:
                raise gr.Error(str(exc)) from None
            return status, configuration_summary(root)

        save_model.click(save_model_ui,
                         inputs=[model_job, model_role, model_provider, model_credential,
                                 model_name, model_base, model_rr, model_rr_keys],
                         outputs=[model_status, config_summary])

        @log_action("configurazione.telegram")
        def save_telegram_ui(token: str, chat: str, topics: list[list[str]], misc: str):
            try:
                status = save_telegram(PROJECT_ROOT, token, chat, topics, misc)
            except (OSError, ValueError, TypeError) as exc:
                raise gr.Error(str(exc)) from None
            return "", status, _bot_button()

        telegram_save.click(save_telegram_ui,
                            inputs=[telegram_token, telegram_chat, telegram_topics, telegram_misc],
                            outputs=[telegram_token, telegram_status, bot_button])
        telegram_listen.click(_listen_topics, inputs=[telegram_token, telegram_topics],
                              outputs=[telegram_status, telegram_chat, telegram_topics])
        telegram_add_link.click(_topic_from_link,
                                inputs=[telegram_link, telegram_topics, telegram_chat],
                                outputs=[telegram_status, telegram_chat, telegram_topics,
                                         telegram_link])

        @log_action("configurazione.trascrizione")
        def save_stt_ui(engine: str, base: str, model: str, key: str):
            try:
                status = save_transcription(PROJECT_ROOT, engine, base, model, key)
            except (OSError, ValueError, TypeError) as exc:
                raise gr.Error(str(exc)) from None
            return "", status

        stt_save.click(save_stt_ui, inputs=[stt_engine, stt_base, stt_model, stt_key],
                       outputs=[stt_key, stt_status])

        @log_action("configurazione.cartella_lezioni")
        def configure_root(path: str):
            nonlocal root
            try:
                new_root = save_lessons_root(path, PROJECT_ROOT)
            except (OSError, ValueError) as exc:
                raise gr.Error(str(exc)) from exc
            root = new_root
            if new_root not in blocked_paths:
                blocked_paths.append(new_root)
            refreshed = _refresh_view(root, None)
            return (
                configuration_summary(root), f"Cartella pronta: **{root}**",
                *refreshed, gr.update(selected="dashboard"), gr.update(value="⚙"), False,
            )

        save_root.click(configure_root, inputs=root_input,
                        outputs=[config_summary, root_status, stats, picker, sidebar_list,
                                 *view_outputs, review_panel, pages, go_config, config_open])

        @log_action("pagina.carica")
        def reload_page():
            nonlocal root
            # Gradio riutilizza i valori iniziali dei componenti anche dopo un refresh
            # del browser: rileggere il file evita di tornare alla cartella precedente.
            if not root_override:
                saved = lessons_root() or ""
                root = (str(Path(saved).expanduser().resolve())
                        if saved and Path(saved).expanduser().is_dir() else "")
            lessons_now = list_lessons(root)
            chosen = next((item.dir_path for item in lessons_now if item.pending_issues),
                          lessons_now[0].dir_path if lessons_now else None)
            return (
                root or str(Path.home() / "RT Lezioni"),
                configuration_summary(root),
                lesson_stats(lessons_now), chosen,
                sidebar_lessons(lessons_now, chosen),
                *_selection_view(root, chosen),
                gr.update(visible=False),
                gr.update(selected="dashboard" if root and Path(root).is_dir() else "config"),
                gr.update(value="⚙" if root and Path(root).is_dir() else "←"),
                not bool(root and Path(root).is_dir()),
                _bot_button(),
            )

        demo.load(reload_page, outputs=[root_input, config_summary, stats, picker,
                                        sidebar_list, *view_outputs, review_panel, pages,
                                        go_config, config_open, bot_button],
                  show_progress="hidden")
    return demo


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Interfaccia web locale di RT")
    parser.add_argument("--lessons-root", default=None, help="Cartella delle lezioni (default: configurazione RT)")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true", help="Non aprire automaticamente il browser")
    parser.add_argument("--log-file", help="Percorso del log diagnostico (default: log utente)")
    args = parser.parse_args(argv)
    root = args.lessons_root or lessons_root() or ""
    if args.lessons_root and not Path(root).expanduser().is_dir():
        parser.error("La cartella passata con --lessons-root non esiste.")
    log_file = configure_logging(args.log_file)
    if root and Path(root).expanduser().is_dir():
        LOG.info("Avvio RT web: lezioni in %s", root)
    else:
        LOG.info("Avvio RT web: cartella lezioni da configurare nell'interfaccia")
    blocked = [str(PROJECT_ROOT / name) for name in (".env", "config", ".rt_telegram", ".agents", ".claude")]
    if root:
        blocked.append(str(Path(root).expanduser().resolve()))
    try:
        build_app(root, blocked_paths=blocked, root_override=bool(args.lessons_root)).launch(
            server_name="127.0.0.1", server_port=args.port, inbrowser=not args.no_browser,
            share=False, show_error=True, blocked_paths=blocked,
            allowed_paths=[web_audio_directory()],
            app_kwargs={"middleware": [Middleware(RequestLogMiddleware, audio_dir=web_audio_directory())]},
            theme=gr.themes.Soft(
                primary_hue="teal", neutral_hue="slate",
                font=["Seravek", "Helvetica Neue", "Arial", "sans-serif"],
            ), css=CSS,
        )
    except Exception:
        LOG.exception("Avvio o esecuzione del server web falliti")
        raise
    LOG.info("RT web terminato. Log: %s", log_file)


if __name__ == "__main__":
    main()
