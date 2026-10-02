import { authenticate, request, waitJob, lessonPath } from './api.js';
import { renderDelimitedMath } from '../src/lib/math';

(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} }
  };

  const MATERIE = {};
  const LEZIONI = [];
  // Tipi di domanda dell'API; "mista" li alterna tutti nella stessa sessione.
  const TYPES = ['quiz', 'mirata', 'vasta', 'caso', 'esercizio'];
  const OPEN = ['mirata', 'caso', 'esercizio']; // valutate con correttezza e completezza
  /* ─── stato ──────────────────────────────────────────────────────── */
  const state = {
    theme: store.get('rt-theme') || 'auto',
    materia: 'all', query: '', loaded: false,
    lessonId: null, setupType: store.get('rt-type') || 'quiz', pmode: store.get('rt-pmode') || 'materia',
    scope: { kind: 'lesson', id: null },
    recall: null, read: null, sheet: { mode: 'browse', unitId: null, lesson: null },
    audio: { player: null, url: null }
  };

  const lesson = () => LEZIONI.find(l => l.id === state.lessonId);
  const materieCon = m => LEZIONI.filter(l => l.materia === m);
  const readyLessons = m => materieCon(m).filter(l => l.stato === 'pronto' && l.domande);
  const dayLessons = d => LEZIONI.filter(l => l.iso === d && l.stato === 'pronto' && l.domande);
  const scopeLessons = sc => sc.kind === 'materia' ? readyLessons(sc.id) : sc.kind === 'giorno' ? dayLessons(sc.id) : [LEZIONI.find(l => l.id === sc.id)].filter(Boolean);
  // La sessione per materia dell'API serve anche il ripasso di un giorno ("GIORNO:AAAA-MM-GG").
  const isShared = sc => sc.kind === 'materia' || sc.kind === 'giorno';
  const subjectKey = sc => sc.kind === 'giorno' ? 'GIORNO:' + sc.id : sc.id;
  const curLesson = () => {
    const r = state.recall;
    if (r && r.qs[r.i] && r.qs[r.i]._lesson) return r.qs[r.i]._lesson;
    return lesson();
  };
  const mmss = s => Math.floor(s / 60) + ':' + String(Math.max(0, Math.round(s) % 60)).padStart(2, '0');

  /* ─── tema ───────────────────────────────────────────────────────── */
  function applyTheme() {
    const dark = state.theme === 'dark' || (state.theme === 'auto' && (tg ? tg.colorScheme === 'dark' : matchMedia('(prefers-color-scheme:dark)').matches));
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }
  $('#themeBtn').addEventListener('click', () => {
    state.theme = state.theme === 'auto' ? 'light' : state.theme === 'light' ? 'dark' : 'auto';
    store.set('rt-theme', state.theme);
    applyTheme();
    toast('Tema: ' + (state.theme === 'auto' ? 'automatico' : state.theme === 'dark' ? 'scuro' : 'chiaro'));
  });
  try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (state.theme === 'auto') applyTheme(); }); } catch {}

  /* ─── helper UI ──────────────────────────────────────────────────── */
  const VIEWS = { lessons: 'view-lessons', lesson: 'view-lesson', read: 'view-read', setup: 'view-setup', recall: 'view-recall', summary: 'view-summary' };
  const shell = { view: 'lessons', main: null };

  function show(view) {
    Object.keys(VIEWS).forEach(k => $('#' + VIEWS[k]).classList.toggle('active', k === view));
    shell.view = view;
    if (view === 'lessons') tg?.BackButton?.hide(); else tg?.BackButton?.show();
    if (view === 'recall') tg?.enableClosingConfirmation?.();
    $('#app').scrollTop = 0;
  }

  function setMain(cfg) {
    const b = $('#mainBtn'), bar = $('.tg-bottom');
    if (!cfg) { b.hidden = true; bar.hidden = true; shell.main = null; return; }
    bar.hidden = false;
    b.hidden = false;
    b.disabled = !!cfg.disabled;
    b.textContent = cfg.label;
    shell.main = cfg.action || null;
  }
  $('#mainBtn').addEventListener('click', () => { if (shell.main) shell.main(); });

  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._tm); t._tm = setTimeout(() => t.classList.remove('show'), 1800);
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  const tg = window.Telegram?.WebApp?.initData ? window.Telegram.WebApp : null;
  let operation = false;
  let recording = null;
  let mediaStream = null;
  let sheetFocus = null;
  function errorMessage(error, retry) {
    const box = $('#sheet').classList.contains('open') ? $('#sheetError') : $('#studyError'); box.hidden = false;
    box.innerHTML = '<div>' + esc(error.message || 'Operazione non riuscita.') + '</div>' + (retry ? '<button class="btn btn-secondary">Riprova</button>' : '');
    if (retry) box.querySelector('button').onclick = () => { box.hidden = true; retry(); };
  }
  async function guarded(fn, retry) {
    if (operation) return;
    operation = true; $('#studyError').hidden = true; $('#sheetError').hidden = true;
    try { await fn(); } catch (e) { errorMessage(e, retry); } finally { operation = false; }
  }
  function counts(l, questions) {
    l.domande = Object.fromEntries(TYPES.map(k => [k, { length: questions[k]?.pending || 0 }]));
  }
  async function loadLessons() {
    const rows = await request('/lessons');
    Object.keys(MATERIE).forEach(k => delete MATERIE[k]); LEZIONI.splice(0);
    rows.sort((a, b) => (b.data || '').localeCompare(a.data || '')).forEach((row, i) => {
      const materia = row.materia || 'Varie'; MATERIE[materia] = materia;
      const date = row.data ? new Date(row.data + 'T12:00:00') : null;
      const valid = date && !Number.isNaN(date.getTime());
      const l = { id: String(row.id), materia, num: i + 1, titolo: row.titolo || row.argomenti || 'Lezione', argomento: row.argomenti || '',
        iso: valid ? row.data : null,
        data: valid ? date.toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' }) : row.data || 'Data non disponibile',
        short: valid ? date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' }) : '—',
        durata: '—', durataSec: 0, unita: [], stato: row.ready ? 'pronto' : 'trascrizione', loaded: false };
      counts(l, row.questions || {}); LEZIONI.push(l);
    });
    renderChips(); renderLessons(); renderSubjects(); renderPractice();
  }
  async function loadLesson(l, force) {
    if (!l || (l.loaded && !force)) return;
    const d = await request(lessonPath(l.id));
    l.unita = d.units.map(u => ({ id: u.id, titolo: u.title, testo: u.content, html: u.html, t0: u.start, t1: u.end, audioOff: !d.has_audio, pending: u.pending || {} }));
    l.stato = d.ready ? 'pronto' : 'trascrizione'; counts(l, d.questions); l.loaded = true;
    l.durataSec = Math.max(0, ...l.unita.map(u => u.t1 || 0)); l.durata = d.has_audio ? mmss(l.durataSec) : '—';
  }
  function mapQuestion(q, l) {
    return { id: q.id, tipo: q.type, testo: q.question_text, unitIds: q.unit_ids, _lesson: l,
      opzioni: (q.options || []).map((testo, i) => ({ id: String.fromCharCode(65 + i), testo })),
      corretta: q.correct_index == null ? null : String.fromCharCode(65 + q.correct_index), spiegazione: q.explanation };
  }
  function saveSession() {
    const r = state.recall;
    try {
      if (!r) { sessionStorage.removeItem('rt-mini-session'); return; }
      const q = r.qs[r.i];
      sessionStorage.setItem('rt-mini-session', JSON.stringify({ scope: r.scope, type: r.type, i: r.i, limit: r.limit, lessonId: q?._lesson.id, questionId: q?.id, jobId: r.jobId }));
    } catch { /* Storage can be disabled by the WebView; the current session still works. */ }
  }
  async function fetchQuestion(exclude) {
    stopRecording();
    const r = state.recall;
    let picked;
    if (isShared(r.scope)) picked = await request('/subject/next?' + new URLSearchParams({ materia: subjectKey(r.scope), qtype: r.type, ...(exclude ? { exclude } : {}) }), { method: 'POST' });
    else picked = { lesson_id: r.scope.id, question: await request(lessonPath(r.scope.id, '/next?') + new URLSearchParams({ qtype: r.type, ...(r.scope.unitId ? { unit_id: r.scope.unitId } : {}), ...(exclude ? { exclude_id: exclude } : {}) }), { method: 'POST' }) };
    const l = LEZIONI.find(l => l.id === String(picked.lesson_id));
    r.qs[r.i] = mapQuestion(picked.question, l); r.jobId = null; saveSession(); await loadLesson(l); show('recall'); renderQuestion();
  }
  async function generateScope() {
    const sc = state.scope; setMain({ label: 'Preparazione in corso…', disabled: true });
    for (const l of scopeLessons(sc)) {
      const accepted = await request(lessonPath(l.id, '/generate?qtype=' + state.setupType), { method: 'POST' });
      await waitJob(accepted);
    }
    await loadLessons();
    if (sc.kind === 'lesson') { state.lessonId = sc.id; await loadLesson(lesson(), true); }
    openSetup(sc.kind, sc.id);
  }
  async function resumeSession() {
    let saved; try { saved = JSON.parse(sessionStorage.getItem('rt-mini-session')); } catch { return; }
    if (!saved?.questionId) return;
    try {
      const data = await request(lessonPath(saved.lessonId, '/resume?') + new URLSearchParams({ question_id: saved.questionId, ...(isShared(saved.scope) ? { materia: subjectKey(saved.scope) } : {}) }));
      const l = LEZIONI.find(l => l.id === String(saved.lessonId)); await loadLesson(l); state.lessonId = l.id; state.scope = saved.scope;
      state.recall = { type: saved.type, scope: saved.scope, i: saved.i, limit: saved.limit, qs: [], voted: {}, records: [], phase: 'question' };
      const r = state.recall; r.qs[r.i] = mapQuestion(data.question, l); show('recall'); renderQuestion();
      if (data.answer) restoredAnswer(data);
      else if (data.pending_job) { r.jobId = data.pending_job.job_id; saveSession(); await grade(null, false); }
    } catch (e) { if (e.status === 404) { sessionStorage.removeItem('rt-mini-session'); return; } throw e; }
  }

  function restoredAnswer(data) {
    const r = state.recall, q = r.qs[r.i];
    Object.assign(q, mapQuestion(data.question, q._lesson)); r.text = data.answer.answer_text;
    r.transcript = data.answer.is_voice ? data.answer.answer_text : ''; r.evaluation = data.answer.evaluation;
    const selected = q.tipo === 'quiz' ? q.opzioni.find(o => o.testo === data.answer.answer_text)?.id : null;
    const dontKnow = ['[Non lo so]', '[Non risposto]'].includes(data.answer.answer_text);
    r.jobId = null; r.uncertain = false; renderFeedback(selected, dontKnow, outcome(q, selected, dontKnow, r.evaluation)); saveSession();
  }

  /* ─── elenco lezioni ─────────────────────────────────────────────── */
  function renderChips() {
    const used = Object.keys(MATERIE).filter(m => LEZIONI.some(l => l.materia === m));
    const items = [{ v: 'all', label: 'Tutte' }].concat(used.map(m => ({ v: m, label: MATERIE[m] })));
    $('#chips').innerHTML = items.map(i =>
      '<button class="chip" data-mat="' + esc(i.v) + '" aria-pressed="' + (state.materia === i.v) + '">' + esc(i.label) + '</button>'
    ).join('');
  }

  function filtered() {
    const q = state.query.trim().toLowerCase();
    return LEZIONI.filter(l => (state.materia === 'all' || l.materia === state.materia))
      .filter(l => !q || (l.titolo + ' ' + l.argomento + ' ' + MATERIE[l.materia]).toLowerCase().includes(q));
  }

  function statoTone(l) {
    if (l.stato === 'pronto') return countQ(l) ? 'Appunti disponibili' : 'Domande in preparazione';
    if (l.stato === 'elaborazione') return 'Domande in preparazione';
    return 'Appunti non ancora disponibili';
  }

  function renderLessons() {
    const list = filtered();
    const empty = $('#lessonsEmpty'), box = $('#lessonsList');
    if (!list.length) { box.hidden = true; empty.hidden = false; empty.querySelector('.hint').textContent = LEZIONI.length ? 'Prova con un’altra materia o un altro termine.' : 'Le lezioni compariranno quando saranno disponibili in RT.'; return; }
    empty.hidden = true; box.hidden = false;

    const groups = {};
    list.forEach(l => { (groups[l.materia] = groups[l.materia] || []).push(l); });

    box.innerHTML = Object.keys(groups).map(m => {
      const rows = groups[m].map(l => {
        const sub = l.loaded && l.unita.length
          ? esc(MATERIE[m]) + ' · ' + l.unita.length + ' unità · ' + esc(l.durata)
          : esc(MATERIE[m]) + ' · ' + statoTone(l);
        const day = l.short.split(' ');
        return '<button class="lesson-row" data-id="' + l.id + '">' +
          '<span class="date"><b class="num">' + esc(day[0]) + '</b>' + esc(day[1] || '') + '</span>' +
          '<span><span class="lr-title">' + esc(l.titolo) + '</span><span class="lr-sub">' + sub + '</span></span>' +
          '<svg class="chev" viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>' +
        '</button>';
      }).join('');
      return '<div class="group-label"><span class="gl-name">' + esc(MATERIE[m]) + '</span><span class="meta">' + groups[m].length + '</span></div>' +
        '<div>' + rows + '</div>';
    }).join('');
  }

  $('#chips').addEventListener('click', e => {
    const c = e.target.closest('.chip'); if (!c) return;
    state.materia = c.dataset.mat; renderChips(); renderLessons();
  });
  $('#searchInput').addEventListener('input', e => {
    state.query = e.target.value;
    $('#clearSearch').hidden = !state.query;
    renderLessons();
  });
  $('#clearSearch').addEventListener('click', () => {
    state.query = ''; $('#searchInput').value = ''; $('#clearSearch').hidden = true; renderLessons();
  });
  $('#lessonsList').addEventListener('click', e => {
    const r = e.target.closest('.lesson-row'); if (!r) return;
    openLesson(r.dataset.id);
  });

  /* ─── ripasso per materia ────────────────────────────────────────── */
  // Domande pronte del tipo scelto in alto (mista: tutte).
  const typeCount = (l, t) => !l.domande ? 0 : t === 'mista' ? countQ(l) : (l.domande[t]?.length || 0);
  function renderSubjects() {
    const used = Object.keys(MATERIE).filter(m => LEZIONI.some(l => l.materia === m));
    $('#lessonHead').textContent = LEZIONI.length + (LEZIONI.length === 1 ? ' lezione' : ' lezioni');
    $('#subjectRow').innerHTML = used.map(m => {
      const tot = materieCon(m).length;
      const q = readyLessons(m).reduce((n, l) => n + typeCount(l, state.setupType), 0);
      if (!readyLessons(m).length) {
        return '<button class="subject-card" disabled><span class="sc-name">' + esc(MATERIE[m]) + '</span><span class="sc-meta">Appunti non ancora disponibili</span></button>';
      }
      return '<button class="subject-card" data-subject="' + esc(m) + '">' +
        '<span class="sc-name">' + esc(MATERIE[m]) + '</span>' +
        '<span class="sc-meta">' + tot + (tot === 1 ? ' lezione' : ' lezioni') + ' · ' + q + (q === 1 ? ' domanda pronta' : ' domande pronte') + '</span>' +
        '<span class="sc-bar">Avvia recall →</span></button>';
    }).join('');
  }
  $('#subjectRow').addEventListener('click', e => {
    const c = e.target.closest('.subject-card'); if (!c || c.disabled) return;
    openSetup('materia', c.dataset.subject);
  });

  /* ─── ripasso per giorno ─────────────────────────────────────────── */
  // Una riga per giorno: la sessione pesca da tutte le lezioni di quella data.
  function renderDays() {
    const days = {};
    LEZIONI.filter(l => l.iso).forEach(l => { (days[l.iso] = days[l.iso] || []).push(l); });
    const keys = Object.keys(days).sort((a, b) => b.localeCompare(a));
    $('#dayRow').innerHTML = keys.map(d => {
      const ls = days[d], first = ls[0];
      const q = ls.filter(l => l.stato === 'pronto').reduce((n, l) => n + typeCount(l, state.setupType), 0);
      const ready = ls.some(l => l.stato === 'pronto' && l.domande);
      const materie = [...new Set(ls.map(l => MATERIE[l.materia]))].join(', ');
      const title = ls.length === 1 ? first.titolo : ls.length + ' lezioni · ' + ls.map(l => l.titolo).join(' · ');
      const sub = ready ? q + (q === 1 ? ' domanda pronta' : ' domande pronte') + ' · ' + esc(materie)
        : esc(materie) + ' · ' + statoTone(first);
      const day = first.short.split(' ');
      return '<button class="lesson-row" data-day="' + d + '"' + (ready ? '' : ' disabled style="opacity:.6"') + '>' +
        '<span class="date"><b class="num">' + esc(day[0]) + '</b>' + esc(day[1] || '') + '</span>' +
        '<span><span class="lr-title">' + esc(title) + '</span><span class="lr-sub">' + sub + '</span></span>' +
        '<svg class="chev" viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>' +
      '</button>';
    }).join('') || '<p class="meta">Nessuna lezione con una data.</p>';
  }
  const PRACTICE_TYPES = ['quiz', 'mirata', 'vasta', 'mista'];
  function renderPractice() {
    const isDay = state.pmode === 'giorno';
    $('#subjectRow').hidden = isDay;
    $('#dayRow').hidden = !isDay;
    $('#practiceSeg').querySelectorAll('.seg-btn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.pmode === state.pmode)));
    const typeButtons = [...$('#practiceType').querySelectorAll('.type-btn')];
    $('#practiceType').style.setProperty('--type-index', Math.max(0, typeButtons.findIndex(b => b.dataset.practiceType === state.setupType)));
    typeButtons.forEach(b => {
      const selected = b.dataset.practiceType === state.setupType;
      b.setAttribute('aria-checked', String(selected));
      b.tabIndex = selected || (!PRACTICE_TYPES.includes(state.setupType) && b === typeButtons[0]) ? 0 : -1;
    });
    if (isDay) renderDays(); else renderSubjects();
  }
  $('#practiceSeg').addEventListener('click', e => {
    const b = e.target.closest('.seg-btn'); if (!b) return;
    state.pmode = b.dataset.pmode; store.set('rt-pmode', state.pmode);
    renderPractice();
  });
  $('#practiceType').addEventListener('click', e => {
    const b = e.target.closest('.type-btn'); if (!b) return;
    state.setupType = b.dataset.practiceType; store.set('rt-type', state.setupType);
    renderPractice();
  });
  $('#practiceType').addEventListener('keydown', e => {
    const buttons = [...$('#practiceType').querySelectorAll('.type-btn')];
    const current = buttons.indexOf(e.target.closest('.type-btn'));
    if (current < 0) return;
    let next = current;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (current + 1) % buttons.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (current - 1 + buttons.length) % buttons.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = buttons.length - 1;
    else return;
    e.preventDefault();
    buttons[next].focus();
    buttons[next].click();
  });
  $('#dayRow').addEventListener('click', e => {
    const b = e.target.closest('[data-day]'); if (!b || b.disabled) return;
    openSetup('giorno', b.dataset.day);
  });

  /* ─── dettaglio lezione ──────────────────────────────────────────── */
  async function openLesson(id) {
    try { const l = LEZIONI.find(l => l.id === String(id)); await loadLesson(l); } catch (e) { errorMessage(e, () => openLesson(id)); return; }
    state.lessonId = id; store.set('rt-last', id);
    state.scope = { kind: 'lesson', id: id };
    const l = lesson();
    const v = $('#view-lesson');

    if (!l.unita.length) {
      v.innerHTML =
        '<button class="back" data-back><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> Lezioni</button>' +
        '<div class="vh"><span class="pill">' + esc(MATERIE[l.materia]) + '</span>' +
        '<h1 style="margin-top:10px">' + esc(l.titolo) + '</h1>' +
        '<p class="sub">' + esc(l.data) + '</p></div>' +
        '<div class="notice warn"><svg viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>' +
        '<span>Appunti e unità non sono ancora disponibili. Completa l’elaborazione della lezione in RT.</span></div>';
      wireBack(v);
      show('lesson'); setMain(null);
      return;
    }

    const tone = l.stato === 'pronto' ? '' :
      '<div class="notice warn" style="margin-bottom:12px"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg><span>Le domande di recall sono in preparazione. Le unità sono già consultabili.</span></div>';

    v.innerHTML =
      '<button class="back" data-back><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> Lezioni</button>' +
      '<div class="vh"><span class="pill">' + esc(MATERIE[l.materia]) + '</span>' +
      '<h1 style="margin-top:10px">' + esc(l.titolo) + '</h1>' +
      '<p class="sub">' + esc(l.data) + ' · ' + l.unita.length + ' unità · audio ' + esc(l.durata) + '</p></div>' +
      '<p class="lead">' + esc(l.argomento) + '</p>' +
      '<div class="statrow">' +
        '<div class="stat"><div class="k num">' + l.unita.length + '</div><div class="l">unità didattiche</div></div>' +
        '<div class="stat"><div class="k num">' + countQ(l) + '</div><div class="l">domande di recall</div></div>' +
        '<div class="stat"><div class="k num">' + esc(l.durata) + '</div><div class="l">durata audio</div></div>' +
      '</div>' + tone +
      '<div class="card stack" style="margin-top:4px">' +
        '<div class="row-between"><span class="card-h">Indice delle unità</span><span class="meta">' + l.unita.length + '</span></div>' +
        '<ul class="unit-index">' + l.unita.map((u, i) =>
          '<li><button data-unit="' + esc(u.id) + '"><span class="ui-n num">' + String(i + 1).padStart(2, '0') + '</span>' +
          '<span class="ui-title">' + esc(u.titolo) + '</span>' +
          '<span class="ui-t num">' + (u.t0 == null ? '' : mmss(u.t0)) + '</span></button></li>').join('') + '</ul>' +
      '</div>' +
      '<div style="margin-top:14px"><button class="btn btn-secondary btn-block" data-read>' +
        '<svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg> Leggi e ripeti</button>' +
        '<button class="btn btn-secondary btn-block" data-units style="margin-top:10px">' +
        '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg> Consulta le unità senza recall</button>' +
        (l.stato === 'pronto' ? '<button class="btn btn-secondary btn-block" data-regen style="margin-top:10px">' +
          '<svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/><path d="M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> ' +
          (countQ(l) ? 'Rigenera il pool di domande' : 'Genera il pool di domande') + '</button>' : '') +
      '</div>';

    wireBack(v);
    v.onclick = function (e) {
      const b = e.target.closest('[data-unit]');
      if (b) { openSheet('browse', b.dataset.unit); return; }
      if (e.target.closest('[data-read]')) { openRead(l.id, 0); return; }
      if (e.target.closest('[data-units]')) { openSheet('browse', l.unita[0].id); return; }
      const rg = e.target.closest('[data-regen]');
      if (rg) regenPool(l, rg);
    };
    show('lesson');
    if (l.stato === 'pronto') setMain({ label: 'Avvia recall', action: () => openSetup('lesson', l.id) });
    else setMain({ label: l.stato === 'elaborazione' ? 'Domande in preparazione' : 'In elaborazione', disabled: true, action: null });
  }

  function countQ(l) {
    if (!l.domande) return 0;
    return TYPES.reduce((n, k) => n + (l.domande[k] ? l.domande[k].length : 0), 0);
  }
  function wireBack(v) {
    const b = v.querySelector('[data-back]');
    if (b) b.addEventListener('click', () => { show('lessons'); setMain(null); });
  }

  // Rigenera il pool dell'intera lezione: il recaller aggiunge domande nuove di ogni tipo
  // (casi ed esercizi compresi, dove il classificatore li trova) senza togliere le altre.
  function regenPool(l, btn) {
    guarded(async () => {
      btn.disabled = true; btn.style.opacity = '0.75'; btn.style.cursor = 'wait';
      btn.innerHTML = '<span class="spinner"></span> Rigenerazione del pool…';
      const job = await request(lessonPath(l.id, '/generate?qtype=mista'), { method: 'POST' });
      await waitJob(job, info => { if (info.progress?.message) btn.lastChild.textContent = ' ' + info.progress.message; });
      await loadLesson(l, true); await openLesson(l.id); renderPractice();
      toast('Pool rigenerato · ' + countQ(l) + ' domande');
    }, () => regenPool(l, btn));
  }

  /* ─── leggi e ripeti ─────────────────────────────────────────────── */
  const unitCount = u => Object.values(u.pending || {}).reduce((n, x) => n + x, 0);
  function unitTypes(u) {
    const p = u.pending || {}, names = [];
    if (p.quiz) names.push(p.quiz === 1 ? 'quiz' : 'quiz');
    if (p.mirata) names.push(p.mirata === 1 ? 'mirata' : 'mirate');
    if (p.caso) names.push(p.caso === 1 ? 'caso clinico' : 'casi clinici');
    if (p.esercizio) names.push(p.esercizio === 1 ? 'esercizio' : 'esercizi');
    return names.length > 1 ? names.slice(0, -1).join(', ') + ' e ' + names[names.length - 1] : names[0] || '';
  }
  async function openRead(lessonId, idx) {
    state.lessonId = lessonId;
    try { await loadLesson(lesson()); } catch (e) { errorMessage(e, () => openRead(lessonId, idx)); return; }
    const n = lesson().unita.length;
    state.read = { i: Math.max(0, Math.min(idx || 0, n - 1)) };
    renderRead();
    show('read');
    setMain(null);
  }
  function renderRead() {
    stopAudio(); clearImages();
    const l = lesson(), i = state.read.i, u = l.unita[i];
    const nQ = unitCount(u);
    const v = $('#view-read');
    const times = u.t0 != null && u.t1 != null ? ' · dal minuto ' + mmss(u.t0) + ' al ' + mmss(u.t1) : '';
    v.innerHTML =
      '<button class="back" data-back><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> ' + esc(l.titolo) + '</button>' +
      '<div class="vh"><span class="pill">' + esc(MATERIE[l.materia]) + ' · Unità ' + (i + 1) + ' di ' + l.unita.length + '</span>' +
      '<h1 style="margin-top:10px">' + esc(u.titolo) + '</h1>' +
      '<p class="sub">' + esc(l.data) + times + '</p></div>' +
      (u.t1 && !u.audioOff ? '<div id="readAudio" style="margin-bottom:14px"></div>' : '') +
      '<div class="read-body">' + (u.html || esc(u.testo)) + '</div>' +
      '<div class="read-cta">' +
        (nQ
          ? '<p class="cta-note">' + nQ + (nQ === 1 ? ' domanda' : ' domande') + ' · ' + esc(unitTypes(u)) + ' su questa unità</p>' +
            '<button class="btn btn-primary btn-block" data-repeat><svg viewBox="0 0 24 24"><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg> Ripeti questa unità</button>'
          : '<div class="notice"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg><span>Per questa unità non ci sono ancora domande di recall.</span></div>') +
      '</div>' +
      '<div class="read-pager">' +
        '<button class="btn btn-secondary" data-prev' + (i === 0 ? ' disabled style="opacity:.55;cursor:default"' : '') + '><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> Precedente</button>' +
        '<button class="btn btn-secondary" data-next' + (i === l.unita.length - 1 ? ' disabled style="opacity:.55;cursor:default"' : '') + '>Successiva <svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button>' +
      '</div>';
    const body = v.querySelector('.read-body');
    renderDelimitedMath(body).catch(() => {});
    loadImages(body, l, () => shell.view === 'read');
    const slot = v.querySelector('#readAudio');
    if (slot) audioControls(slot, l, u);
    const back = v.querySelector('[data-back]');
    if (back) back.addEventListener('click', () => { stopAudio(); openLesson(l.id); });
    const rep = v.querySelector('[data-repeat]');
    if (rep) rep.addEventListener('click', () => startUnitRecall(l, i));
    const prev = v.querySelector('[data-prev]');
    if (prev) prev.addEventListener('click', () => { if (i > 0) { state.read.i = i - 1; renderRead(); $('#app').scrollTop = 0; } });
    const next = v.querySelector('[data-next]');
    if (next) next.addEventListener('click', () => { if (i < l.unita.length - 1) { state.read.i = i + 1; renderRead(); $('#app').scrollTop = 0; } });
  }
  function startUnitRecall(l, i) {
    const u = l.unita[i];
    const n = unitCount(u);
    if (!n) return;
    stopAudio();
    guarded(async () => {
      state.scope = { kind: 'unit', id: l.id, unitId: u.id };
      state.recall = { type: 'mista', qs: [], i: 0, limit: n, phase: 'question', sel: null, text: '', transcript: '', voted: {}, records: [], scope: state.scope, returnRead: i };
      setMain({ label: 'Caricamento…', disabled: true }); await fetchQuestion();
    }, () => startUnitRecall(l, i));
  }

  /* ─── preparazione recall ────────────────────────────────────────── */
  const TIPI = [
    { id: 'quiz', t: 'Quiz', d: 'Scelta multipla con esito corretto o sbagliato e spiegazione.' },
    { id: 'mirata', t: 'Mirata', d: 'Domanda aperta su un contenuto circoscritto, a una o due unità.' },
    { id: 'vasta', t: 'Vasta', d: 'Domanda aperta più ampia, che può coinvolgere più unità.' },
    { id: 'mista', t: 'Mista', d: 'Unisce quiz, domande mirate, vaste, casi ed esercizi nella stessa sessione.' },
    { id: 'caso', t: 'Casi clinici', d: 'Un paziente da inquadrare: interpreta i dati e motiva il ragionamento.', special: true },
    { id: 'esercizio', t: 'Esercizi', d: 'Un esercizio da svolgere con il procedimento visto a lezione.', special: true }
  ];

  const tipoLabel = t => ({ quiz: 'Quiz', mirata: 'Mirata', vasta: 'Vasta', caso: 'Caso clinico', esercizio: 'Esercizio' }[t] || 'Mista');

  function openSetup(kind, id) {
    if (kind) state.scope = { kind, id };
    else if (!state.scope.id || state.scope.kind === 'unit') state.scope = { kind: 'lesson', id: state.lessonId };
    if (state.scope.kind === 'lesson') state.lessonId = state.scope.id;

    const sc = state.scope, ls = scopeLessons(sc);
    const title = sc.kind === 'materia' ? MATERIE[sc.id] : sc.kind === 'giorno' ? 'Ripasso del ' + (LEZIONI.find(l => l.iso === sc.id)?.data || sc.id) : lesson().titolo;
    const sub = sc.kind === 'materia'
      ? ls.length + (ls.length === 1 ? ' lezione' : ' lezioni') + ' · domande da tutta la materia'
      : sc.kind === 'giorno'
        ? ls.length + (ls.length === 1 ? ' lezione' : ' lezioni') + ' · domande da tutte le lezioni del giorno'
        : 'Scegli il tipo di domanda per questa sessione';

    const avail = {};
    TIPI.forEach(t => { avail[t.id] = ls.reduce((n, l) => n + typeCount(l, t.id), 0); });
    const ready = ls.length > 0;
    if (!TIPI.some(t => t.id === state.setupType)) state.setupType = 'quiz';
    const shown = TIPI.filter(t => !t.special || avail[t.id] || state.setupType === t.id);

    const v = $('#view-setup');
    v.innerHTML =
      '<button class="back" data-back><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> ' + esc(title) + '</button>' +
      '<div class="vh"><h1>Prepara il recall</h1><p class="sub">' + esc(sub) + '</p></div>' +
      (sc.kind === 'materia' ? '<div class="notice info" style="margin-bottom:14px"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg><span>Sessione su tutta la materia: le domande arrivano da tutte le lezioni disponibili.</span></div>' : '') +
      (sc.kind === 'giorno' ? '<div class="notice info" style="margin-bottom:14px"><svg viewBox="0 0 24 24"><rect x="3.5" y="5.5" width="17" height="15" rx="2"/><path d="M7.5 3.5v4M16.5 3.5v4M3.5 10h17"/></svg><span>Ripasso del giorno: ' + esc(ls.map(l => l.titolo).join(' · ') || 'nessuna lezione pronta') + '.</span></div>' : '') +
      shown.map(t =>
        '<button class="choice" data-type="' + t.id + '" aria-pressed="' + (state.setupType === t.id) + '">' +
          '<span class="radio" aria-hidden="true"></span>' +
          '<span><span class="c-title">' + t.t + '</span><span class="c-desc">' + t.d + '</span>' +
          (avail[t.id] ? '<span class="c-ex">' + avail[t.id] + (avail[t.id] === 1 ? ' domanda' : ' domande') + '</span>' : '<span class="c-ex">in preparazione</span>') +
          '</span>' +
        '</button>').join('') +
      '<div id="prepStatus" style="margin-top:16px"></div>';

    function updateStatus() {
      const s = $('#prepStatus');
      if (!ready) {
        s.innerHTML = '<div class="notice">Non ci sono ancora lezioni con appunti disponibili. Completa l’elaborazione in RT.</div>';
        setMain(null);
        return;
      }
      if (!avail[state.setupType]) {
        s.innerHTML = '<div class="notice"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg><span>Per questo tipo non ci sono ancora domande. Puoi generarne un nuovo gruppo.</span></div>';
        setMain({ label: 'Genera domande', action: () => guarded(generateScope, () => openSetup()) });
        return;
      }
      s.innerHTML = '<div class="notice info"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg><span>' + avail[state.setupType] + ' domande pronte' + (sc.kind === 'materia' ? ' dalle lezioni della materia' : sc.kind === 'giorno' ? ' dalle lezioni del giorno' : '') + ' · puoi terminare la sessione in qualsiasi momento.</span></div>';
      setMain({ label: 'Avvia sessione', action: startRecall });
    }

    v.querySelectorAll('.choice').forEach(c => c.addEventListener('click', () => {
      state.setupType = c.dataset.type;
      if (PRACTICE_TYPES.includes(state.setupType)) store.set('rt-type', state.setupType);
      v.querySelectorAll('.choice').forEach(x => x.setAttribute('aria-pressed', String(x === c)));
      updateStatus();
    }));
    const backBtn = v.querySelector('[data-back]');
    if (backBtn) backBtn.addEventListener('click', () => {
      if (isShared(sc)) { show('lessons'); setMain(null); renderPractice(); }
      else openLesson(state.lessonId);
    });
    show('setup');
    updateStatus();
  }

  /* ─── sessione recall ────────────────────────────────────────────── */
  function startRecall() {
    guarded(async () => {
      const ls = scopeLessons(state.scope);
      const limit = ls.reduce((n, l) => n + typeCount(l, state.setupType), 0);
      state.recall = { type: state.setupType, scope: { ...state.scope }, qs: [], i: 0, limit: Math.max(1, limit), phase: 'question', sel: null, text: '', transcript: '', voted: {}, records: [] };
      setMain({ label: 'Caricamento…', disabled: true }); await fetchQuestion();
    }, () => { state.recall = null; openSetup(); });
  }

  function renderQuestion() {
    const r = state.recall, q = r.qs[r.i];
    r.phase = 'question'; r.sel = null; r.text = ''; r.transcript = ''; r.evaluation = ''; r.voiceBlob = null;
    $('#qProg').textContent = 'Domanda ' + (r.i + 1) + ' di ' + r.limit;
    $('#qBar').style.width = ((r.i) / r.limit * 100) + '%';
    $('#qType').textContent = tipoLabel(q.tipo);
    $('#qText').textContent = q.testo;
    const nU = (q.unitIds || []).length;
    $('#qUnits').textContent = nU > 1 ? 'Domanda su ' + nU + ' unità didattiche' : 'Domanda su una unità didattica';
    $('#qPhase').hidden = false; $('#qGrading').hidden = true; $('#qFeedback').hidden = true;

    const body = $('#qBody');
    if (q.tipo === 'quiz') {
      body.innerHTML = q.opzioni.map(o =>
        '<button class="opt" data-opt="' + o.id + '" aria-pressed="false"><span class="mk num">' + o.id.toUpperCase() + '</span><span>' + esc(o.testo) + '</span></button>').join('');
      body.querySelectorAll('.opt').forEach(b => b.addEventListener('click', () => {
        if (state.recall.phase !== 'question') return;
        state.recall.sel = b.dataset.opt;
        body.querySelectorAll('.opt').forEach(x => { x.setAttribute('aria-pressed', String(x === b)); });
        setMain({ label: 'Invia risposta', action: submitAnswer });
      }));
    } else {
      body.innerHTML =
        '<textarea aria-label="La tua risposta" class="textarea" id="openAnswer" placeholder="' +
          (q.tipo === 'caso' ? 'Inquadra il caso e motiva il ragionamento, oppure rispondi a voce…' : q.tipo === 'esercizio' ? 'Scrivi i passaggi e il risultato, oppure rispondi a voce…' : 'Scrivi la tua risposta, oppure rispondi a voce…') + '"></textarea>' +
        '<div class="answer-tools">' +
          '<button class="mic" id="micBtn"><svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg><span id="micLabel">Rispondi a voce</span></button>' +
          '<span class="meta" id="micState"></span>' +
        '</div>';
      const ta = $('#openAnswer');
      ta.addEventListener('input', () => { state.recall.text = ta.value; setMain({ label: 'Invia risposta', disabled: !ta.value.trim(), action: submitAnswer }); });
      wireMic(q);
    }

    $('#qActions').innerHTML =
      '<button class="btn btn-secondary" id="dontKnow"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.4 2.3c-.9.4-1.4 1-1.4 2"/><path d="M12 17h.01"/></svg> Non lo so</button>' +
      '<button class="btn btn-ghost grow" id="skipQ">Salta</button>' +
      '<span class="hint">«Non lo so» mostra la spiegazione e registra il tentativo · «Salta» passa oltre senza registrare nulla.</span>';
    $('#dontKnow').addEventListener('click', () => grade(null, true));
    $('#skipQ').addEventListener('click', skipQuestion);

    const reference = (q.unitIds || []).find(id => q._lesson.unita.some(u => u.id === id));
    if (reference) {
      const consult = document.createElement('button');
      consult.className = 'btn btn-ghost';
      consult.id = 'consultQuestion';
      consult.textContent = 'Consulta le unità di riferimento';
      consult.onclick = () => openSheet('recall', reference, q._lesson);
      $('#qActions').append(consult);
    }

    setMain({ label: 'Invia risposta', disabled: true, action: submitAnswer });
  }

  function wireMic() {
    $('#micBtn').onclick = async () => {
      const btn = $('#micBtn'), lbl = $('#micLabel');
      if (recording?.state === 'recording') { recording.stop(); return; }
      try {
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Registrazione non disponibile: rispondi a testo.');
        const recallRef = state.recall;
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (state.recall !== recallRef || recallRef.phase !== 'question' || shell.view !== 'recall') { stream.getTracks().forEach(t => t.stop()); return; }
        mediaStream = stream;
        const type = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(t => MediaRecorder.isTypeSupported(t));
        recording = new MediaRecorder(mediaStream, type ? { mimeType: type } : {}); const chunks = [];
        recording.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
        recording.onstop = () => { state.recall.voiceBlob = new Blob(chunks, { type: recording.mimeType }); mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; lbl.textContent = 'Registra di nuovo'; btn.classList.remove('rec'); $('#micState').textContent = 'Vocale pronto per l’invio'; setMain({ label: 'Invia risposta vocale', action: submitAnswer }); };
        recording.start(); btn.classList.add('rec'); lbl.textContent = 'Ferma'; setMain({ label: 'Ferma la registrazione', disabled: true });
      } catch (e) { mediaStream?.getTracks().forEach(t => t.stop()); errorMessage(e); }
    };
  }

  function submitAnswer() { grade(state.recall.sel, false); }

  // "Correttezza: 80%\nCompletezza: 60%\n\ncommento" (mirate, casi, esercizi) → punteggi e commento.
  function parseEvaluation(text) {
    const value = name => { const m = new RegExp(name + ':\\s*(\\d+)\\s*%', 'i').exec(text || ''); return m ? Number(m[1]) : null; };
    const correttezza = value('Correttezza'), completezza = value('Completezza');
    const comment = (text || '').replace(/^\s*(Correttezza|Completezza):\s*\d+\s*%\s*$/gim, '').trim();
    return { scores: correttezza == null || completezza == null ? null : { correttezza, completezza }, comment };
  }
  function outcome(q, selected, dontKnow, evaluation) {
    if (dontKnow) return { kind: 'none', label: 'Non risposto' };
    if (q.tipo === 'quiz') return selected != null && selected === q.corretta ? { kind: 'ok', label: 'Corretto' } : { kind: 'no', label: 'Sbagliato' };
    const s = parseEvaluation(evaluation).scores;
    if (OPEN.includes(q.tipo) && s) {
      return (s.completezza >= 70 && s.correttezza >= 60) ? { kind: 'ok', label: 'Buona risposta' }
        : (s.correttezza >= 40 || s.completezza >= 50) ? { kind: 'warn', label: 'Risposta parziale' }
        : { kind: 'no', label: 'Risposta da rivedere' };
    }
    return { kind: 'none', label: 'Valutazione della risposta' };
  }

  async function grade(selected, dontKnow) {
    if (operation || state.recall.phase !== 'question') return;
    stopRecording();
    await guarded(async () => {
      const r = state.recall, q = r.qs[r.i]; r.phase = 'grading';
      $('#qPhase').hidden = true; $('#qFeedback').hidden = true; $('#qGrading').hidden = false; setMain(null);
      $('#gradingText').textContent = q.tipo === 'quiz' ? 'Verifico la risposta…' : (r.voiceBlob ? 'Trascrizione e valutazione in corso…' : 'Valutazione in corso…');
      const resumeParams = () => new URLSearchParams({ question_id: q.id, ...(isShared(r.scope) ? { materia: subjectKey(r.scope) } : {}) });
      try {
        let result;
        if (r.uncertain || r.jobId) {
          const saved = await request(lessonPath(q._lesson.id, '/resume?') + resumeParams());
          if (saved.answer) { restoredAnswer(saved); return; }
          result = saved.pending_job;
        }
        if (result?.job_id) { r.jobId = result.job_id; }
        else if (r.voiceBlob && !dontKnow) {
          r.uncertain = true;
          const data = new FormData(); data.append('question_id', q.id);
          const type = r.voiceBlob.type; const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm'; data.append('audio', r.voiceBlob, 'answer.' + ext);
          result = await request(lessonPath(q._lesson.id, '/answer-voice'), { method: 'POST', body: data });
        } else {
          r.uncertain = true;
          result = await request(lessonPath(q._lesson.id, '/answer'), { method: 'POST', body: { question_id: q.id, choice: q.tipo !== 'quiz' || selected == null ? null : q.opzioni.findIndex(o => o.id === selected), answer: r.text, dont_know: dontKnow } });
        }
        if (result.job_id) {
          r.jobId = result.job_id; saveSession(); const answer = await waitJob(result); r.evaluation = answer.evaluation; r.transcript = answer.is_voice ? answer.answer : ''; r.jobId = null;
          // Scaletta della vasta e soluzione di casi ed esercizi: visibili solo dopo la risposta.
          if (q.tipo !== 'mirata') {
            try { const saved = await request(lessonPath(q._lesson.id, '/resume?') + resumeParams()); q.spiegazione = saved.question?.explanation || q.spiegazione; }
            catch { /* la valutazione resta visibile anche senza soluzione */ }
          }
        } else { q.corretta = result.question.correct_index == null ? null : String.fromCharCode(65 + result.question.correct_index); q.spiegazione = result.question.explanation; }
        const feedback = outcome(q, selected, dontKnow, r.evaluation);
        r.uncertain = false; r.records.push(feedback.kind); renderFeedback(selected, dontKnow, feedback); saveSession();
      } catch (e) { if (e.code === 'job_failed') { r.jobId = null; r.uncertain = false; } r.phase = 'question'; $('#qPhase').hidden = false; $('#qGrading').hidden = true; softMain(); throw e; }
    }, () => grade(selected, dontKnow));
  }

  const scoreLevel = v => v >= 70 ? 'ok' : v >= 40 ? 'warn' : 'no';
  function scoresHtml(s, tipo) {
    return '<div class="block"><div class="b-label">Punteggi · ' + (tipo === 'mirata' ? 'domanda mirata' : tipo === 'caso' ? 'caso clinico' : 'esercizio') + '</div>' +
      [['Completezza', s.completezza], ['Correttezza', s.correttezza]].map(function (row) {
        const name = row[0], v = row[1], l = scoreLevel(v);
        return '<div class="score"><div class="score-top"><span class="s-name">' + name +
          '</span><span class="s-val lvl-' + l + '">' + v + '%</span></div>' +
          '<div class="meter bg-' + l + '"><span style="width:' + v + '%"></span></div></div>';
      }).join('') +
      '<p class="s-note">Valutazione di RT: <strong>completezza</strong> = quanti punti attesi sono presenti; <strong>correttezza</strong> = quanto ciò che hai detto è giusto.</p></div>';
  }
  // La scaletta della vasta arriva come testo: un punto per riga, oppure "1) … 2) …".
  function scalettaSteps(text) {
    const lines = String(text || '').split(/\n+/).map(s => s.trim()).filter(Boolean);
    const parts = lines.length > 1 ? lines : String(text || '').split(/\s*(?=\b\d+[).]\s)/).map(s => s.trim()).filter(Boolean);
    return parts.map(s => s.replace(/^(\d+[).]|[-•*])\s*/, ''));
  }
  function scalettaHtml(text) {
    const steps = scalettaSteps(text);
    if (!steps.length) return '';
    return '<div class="block scaletta-block"><div class="b-label">Scaletta · impostazione ideale</div>' +
      '<ol class="scaletta">' + steps.map(function (step, i) {
        return '<li><span class="st-n num">' + (i + 1) + '</span><span class="st-t">' + esc(step) + '</span></li>';
      }).join('') + '</ol></div>';
  }

  function renderFeedback(selected, dontKnow, result) {
    const r = state.recall, q = r.qs[r.i];
    r.phase = 'feedback';
    $('#qGrading').hidden = true;
    const fb = $('#qFeedback');
    fb.hidden = false;

    const icon = result.kind === 'ok'
      ? '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>'
      : result.kind === 'no' ? '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>'
      : result.kind === 'warn' ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>'
      : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.4 2.3c-.9.4-1.4 1-1.4 2"/><path d="M12 17h.01"/></svg>';

    const qLesson = curLesson();
    const scope = r.scope || state.scope;
    const evaluation = parseEvaluation(r.evaluation);
    let html = '<div class="fb-head"><span class="badge ' + result.kind + '">' + icon + result.label + '</span>' +
      (isShared(scope) && qLesson ? '<span class="meta">' + esc(qLesson.titolo) + '</span>' : '') +
      (q.tipo === 'vasta' && !dontKnow ? '<span class="meta">valutazione indicativa</span>' : '') + '</div>';

    if (OPEN.includes(q.tipo) && evaluation.scores && !dontKnow) html += scoresHtml(evaluation.scores, q.tipo);
    if (q.tipo === 'vasta') html += scalettaHtml(q.spiegazione);

    if (q.tipo === 'quiz') {
      html += '<div class="block"><div class="b-label">Le tue risposte</div>' + q.opzioni.map(o => {
        let cls = '', mk = o.id.toUpperCase();
        if (o.id === q.corretta) { cls = ' correct'; mk = '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>'; }
        else if (o.id === selected) { cls = ' wrong'; mk = '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>'; }
        return '<button class="opt' + cls + '" disabled><span class="mk num">' + mk + '</span><span>' + esc(o.testo) + '</span></button>';
      }).join('') + '</div>';
    }

    if (r.transcript) {
      html += '<div class="block"><div class="b-label">Trascrizione della risposta vocale</div><p>' + esc(r.transcript) + '</p></div>';
    }

    if (q.tipo === 'quiz' && q.spiegazione) {
      html += '<div class="block"><div class="b-label">Spiegazione</div><p>' + esc(q.spiegazione) + '</p></div>';
    }

    if (q.tipo !== 'quiz') html += '<div class="block"><div class="b-label">Valutazione di RT</div><div style="white-space:pre-wrap">' + esc(evaluation.comment || r.evaluation || 'Valutazione non disponibile.') + '</div></div>';

    if ((q.tipo === 'caso' || q.tipo === 'esercizio') && q.spiegazione) {
      html += '<div class="block"><div class="b-label">' + (q.tipo === 'caso' ? 'Ragionamento atteso' : 'Soluzione attesa') + '</div><div style="white-space:pre-wrap">' + esc(q.spiegazione) + '</div></div>';
    }

    const srcs = (q.unitIds || []).map(id => qLesson.unita.find(u => u.id === id)).filter(Boolean);
    html += '<div class="block"><div class="b-label">Unità di riferimento' + (isShared(scope) ? ' · ' + esc(qLesson.titolo) : '') + '</div>' +
      srcs.map(u => '<button class="src-chip" data-unit="' + esc(u.id) + '" data-lesson="' + qLesson.id + '"><span class="n num">' + String(qLesson.unita.indexOf(u) + 1).padStart(2, '0') + '</span>' + esc(u.titolo) + '</button>').join('') +
      '<div class="meta" style="margin-top:6px">Testo e audio si aprono senza perdere la domanda e il feedback.</div></div>';

    html += '<div class="block"><div class="vote"><span class="v-label">Questa domanda è stata utile?</span>' +
      [['up', '👍'], ['down', '👎'], ['lightning', '⚡']].map(([v, label]) => '<button data-vote="' + v + '" aria-pressed="' + (r.voted[r.i] === v) + '" aria-label="Vota ' + label + '">' + label + '</button>').join('') +
      '</div></div>';

    fb.innerHTML = html;

    fb.querySelectorAll('[data-unit]').forEach(b => b.addEventListener('click', () => {
      const ll = LEZIONI.find(x => x.id === b.dataset.lesson) || curLesson();
      openSheet('recall', b.dataset.unit, ll);
    }));
    fb.querySelectorAll('[data-vote]').forEach(b => b.onclick = () => guarded(async () => {
      await request(lessonPath(q._lesson.id, '/vote'), { method: 'POST', body: { question_id: q.id, vote: b.dataset.vote } });
      r.voted[r.i] = b.dataset.vote; fb.querySelectorAll('[data-vote]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); toast('Voto registrato');
    }));

    const last = r.i === r.limit - 1;
    setMain({ label: last ? 'Termina sessione' : 'Prossima domanda', action: last ? endSession : nextQuestion });
    $('#qBar').style.width = ((r.i + 1) / r.limit * 100) + '%';
  }

  function nextQuestion() {
    guarded(async () => {
      const r = state.recall; r.i++;
      try { await fetchQuestion(); }
      catch (e) { r.i--; if (e.status === 404) { await finishSession(); return; } throw e; }
    }, nextQuestion);
  }

  function skipQuestion() {
    stopRecording();
    guarded(async () => {
      const r = state.recall, q = r.qs[r.i]; await request(lessonPath(q._lesson.id, '/skip'), { method: 'POST', body: { question_id: q.id } });
      if (r.i >= r.limit - 1) { await finishSession(); return; }
      r.i++;
      try { await fetchQuestion(isShared(r.scope) ? q._lesson.id + ':' + q.id : q.id); }
      catch (e) { r.i--; if (e.status === 404) { await finishSession(); return; } throw e; }
    }, skipQuestion);
  }

  async function closeServerSession(r) {
    const result = isShared(r.scope)
      ? await request('/subject/end?' + new URLSearchParams({ materia: subjectKey(r.scope) }), { method: 'POST' })
      : await request(lessonPath(r.scope.id, '/end'), { method: 'POST' });
    sessionStorage.removeItem('rt-mini-session'); tg?.disableClosingConfirmation?.();
    return result;
  }

  function endSession() { guarded(finishSession, endSession); }
  async function finishSession() {
    const r = state.recall; stopRecording();
    const result = await closeServerSession(r);
    const s = result.summary || {};
    const c = { ok: 0, no: 0, warn: 0, none: 0 };
    (r.records || []).forEach(x => { c[x] = (c[x] || 0) + 1; });
    const scope = r.scope;
    const typeLabel = r.type === 'quiz' ? 'Quiz' : r.type === 'mirata' ? 'Domande mirate' : r.type === 'vasta' ? 'Domande vaste'
      : r.type === 'caso' ? 'Casi clinici' : r.type === 'esercizio' ? 'Esercizi' : 'Sessione mista';
    let scopeLabel = '';
    const lg = LEZIONI.find(l => l.id === scope.id);
    if (scope.kind === 'materia') scopeLabel = MATERIE[scope.id] + ' · tutta la materia';
    else if (scope.kind === 'giorno') scopeLabel = 'Ripasso del ' + (LEZIONI.find(l => l.iso === scope.id)?.data || scope.id);
    else {
      const ug = (scope.kind === 'unit' && lg) ? lg.unita.find(u => u.id === scope.unitId) : null;
      scopeLabel = (lg ? lg.titolo : '') + (ug ? ' · ' + ug.titolo : '');
    }
    const l0 = isShared(scope) ? (scopeLessons(scope)[0] || null) : lg;
    const v = $('#view-summary');
    v.innerHTML =
      '<div class="summary">' +
        '<div class="ring"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg></div>' +
        '<h1>Sessione completata</h1>' +
        '<p class="lead" style="margin-top:6px">' + esc(scopeLabel) + ' · ' + typeLabel + '</p>' +
        '<div class="sgrid">' +
          '<div class="cell"><div class="k num" style="color:var(--success)">' + c.ok + '</div><div class="l">corrette / buone</div></div>' +
          '<div class="cell"><div class="k num" style="color:var(--attention)">' + c.warn + '</div><div class="l">da rivedere</div></div>' +
          '<div class="cell"><div class="k num" style="color:var(--danger)">' + c.no + '</div><div class="l">sbagliate</div></div>' +
          '<div class="cell"><div class="k num">' + c.none + '</div><div class="l">non risposte</div></div>' +
        '</div>' +
        '<p class="meta" style="text-align:center">' + (s.questions || 0) + ' domande poste · ' + (s.answered || 0) + ' risposte registrate</p>' +
        (l0 && l0.unita.length ? '<div class="stack"><button class="btn btn-secondary btn-block" id="reviewUnits"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg> Rivedi le unità</button></div>' : '') +
      '</div>';
    const rv = v.querySelector('#reviewUnits');
    if (rv) rv.addEventListener('click', () => openSheet('browse', l0.unita[0].id, l0));
    show('summary');
    const reload = () => loadLessons().catch(e => errorMessage(e));
    if (scope.kind === 'unit' && lg) {
      const next = Math.min((r.returnRead || 0) + 1, lg.unita.length - 1);
      setMain({ label: next > (r.returnRead || 0) ? 'Continua a leggere' : 'Torna alla lettura', action: async () => { state.recall = null; await loadLesson(lg, true); openRead(lg.id, next); reload(); } });
    } else setMain({ label: 'Torna alle lezioni', action: () => { state.recall = null; show('lessons'); setMain(null); reload(); } });
  }
  function stopRecording() {
    if (recording?.state === 'recording') { recording.onstop = null; recording.stop(); }
    mediaStream?.getTracks().forEach(t => t.stop()); mediaStream = null;
  }

  // Esci: chiude la sessione e torna da dove si era partiti (lettura, lezione o elenco).
  function exitRecall() {
    stopRecording();
    guarded(async () => {
      const r = state.recall; if (!r) return;
      await closeServerSession(r);
      state.recall = null;
      const sc = r.scope;
      if (sc.kind === 'unit') { const l = LEZIONI.find(x => x.id === sc.id); await loadLesson(l, true); openRead(sc.id, r.returnRead || 0); }
      else if (sc.kind === 'lesson') { await loadLesson(LEZIONI.find(x => x.id === sc.id), true); openLesson(sc.id); }
      else { show('lessons'); setMain(null); }
      loadLessons().catch(e => errorMessage(e));
    }, exitRecall);
  }
  $('#exitRecall').addEventListener('click', exitRecall);

  /* ─── drawer unità ───────────────────────────────────────────────── */
  function openSheet(mode, unitId, lessonRef) {
    $('#sheetError').hidden = true;
    const l = lessonRef || (mode === 'recall' ? curLesson() : lesson());
    state.sheet = { mode: mode, unitId: unitId || (l.unita[0] && l.unita[0].id), lesson: l };
    $('#sheetCtx').textContent = mode === 'recall' ? 'Unità di riferimento · ' + MATERIE[l.materia] : MATERIE[l.materia];
    $('#sheetTitle').textContent = l.titolo;
    $('#sheetFoot').hidden = mode !== 'recall';
    $('#backToFeedback').lastChild.textContent = state.recall?.phase === 'feedback' ? ' Torna al feedback' : ' Torna alla domanda';
    renderUnitList();
    renderUnit(state.sheet.unitId);
    sheetFocus = document.activeElement; $('#sheet').classList.add('open'); $('#sheetClose').focus(); $('#app').inert = true; tg?.BackButton?.show();
    setMain(null);
  }
  function closeSheet() {
    stopAudio(); clearImages();
    $('#sheet').classList.remove('open'); $('#app').inert = false; sheetFocus?.focus();
    softMain();
  }
  function renderUnitList() {
    const l = state.sheet.lesson;
    $('#sheetUnits').innerHTML = l.unita.map((u, i) =>
      '<button class="u-pill" data-unit="' + esc(u.id) + '" aria-pressed="' + (u.id === state.sheet.unitId) + '"><span class="n num">' + String(i + 1).padStart(2, '0') + '</span>' + esc(u.titolo) + '</button>').join('');
  }
  function renderUnit(id) {
    clearImages();
    const l = state.sheet.lesson, u = l.unita.find(x => x.id === id) || l.unita[0];
    if (!u) { $('#unitRead').innerHTML = '<div class="empty-unit">Nessuna unità disponibile per questa lezione.</div>'; return; }
    state.sheet.unitId = u.id;
    $('#sheetUnits').querySelectorAll('.u-pill').forEach(p => p.setAttribute('aria-pressed', String(p.dataset.unit === u.id)));
    const idx = l.unita.indexOf(u) + 1;
    const playable = u.t1 && !u.audioOff;
    $('#unitRead').innerHTML =
      '<div class="row-between"><span class="u-time num">' + (u.t0 == null || u.t1 == null ? 'Tempi non disponibili' : mmss(u.t0) + ' – ' + mmss(u.t1)) + '</span>' +
      '<span class="tag">Unità ' + idx + ' di ' + l.unita.length + '</span></div>' +
      (playable ? '<div id="audioSlot"></div>' : '') +
      '<h3>' + esc(u.titolo) + '</h3>' +
      '<div class="body-txt">' + (u.html || esc(u.testo)) + '</div>' +
      (playable ? '' : '<div id="audioSlot"></div>');
    renderAudio(u); renderDelimitedMath($('.body-txt')).catch(() => {});
    loadImages($('.body-txt'), l, () => $('#sheet').classList.contains('open'));
  }
  const imageUrls = [];
  function clearImages() { imageUrls.splice(0).forEach(url => URL.revokeObjectURL(url)); }
  function loadImages(root, l, stillOpen) {
    root.querySelectorAll('img[data-rt-image]').forEach(async img => {
      try {
        const blob = await request(lessonPath(l.id, '/images/' + encodeURIComponent(img.dataset.rtImage)), { blob: true });
        if (!img.isConnected || !stillOpen()) return;
        const url = URL.createObjectURL(blob); imageUrls.push(url); img.src = url;
      } catch { img.replaceWith(document.createTextNode(img.alt || 'Immagine non disponibile')); }
    });
  }
  // Ascolta l'audio dell'unità (clip scaricato su richiesta) o lo invia nel topic Telegram.
  function audioControls(slot, l, u) {
    slot.innerHTML = '<div class="player"><button class="btn btn-secondary" data-load-audio>Ascolta audio</button></div><button class="btn btn-ghost" data-send-audio>Invia audio su Telegram</button>';
    slot.querySelector('[data-load-audio]').onclick = async () => {
      const btn = slot.querySelector('[data-load-audio]'); btn.disabled = true;
      try {
        const blob = await request(lessonPath(l.id, '/units/' + encodeURIComponent(u.id) + '/audio'), { blob: true });
        if (!slot.isConnected) return;
        stopAudio();
        const url = URL.createObjectURL(blob); state.audio.url = url;
        slot.querySelector('.player').innerHTML = '<audio controls aria-label="Audio dell’unità"></audio>';
        const player = slot.querySelector('audio'); player.src = url; state.audio.player = player; await player.play().catch(() => {});
      } catch (e) { btn.disabled = false; errorMessage(e); }
    };
    slot.querySelector('[data-send-audio]').onclick = () => guarded(async () => { await request(lessonPath(l.id, '/units/' + encodeURIComponent(u.id) + '/send-audio'), { method: 'POST' }); toast('Audio inviato su Telegram'); });
  }
  function renderAudio(u) {
    stopAudio(); const slot = $('#audioSlot');
    if (!u.t1 || u.audioOff) { slot.innerHTML = '<div class="notice">Audio non disponibile per questa unità.</div>'; return; }
    audioControls(slot, state.sheet.lesson, u);
    slot.querySelector('[data-load-audio]').id = 'loadAudio';
    slot.querySelector('[data-send-audio]').id = 'sendAudio';
  }
  function stopAudio() {
    state.audio.player?.pause(); state.audio.player = null;
    if (state.audio.url) { URL.revokeObjectURL(state.audio.url); state.audio.url = null; }
  }

  $('#sheetUnits').addEventListener('click', e => { const b = e.target.closest('[data-unit]'); if (b) renderUnit(b.dataset.unit); });
  $('#sheetClose').addEventListener('click', closeSheet);
  $('#sheetBd').addEventListener('click', closeSheet);
  $('#backToFeedback').addEventListener('click', closeSheet);

  function softMain() {
    if (shell.view === 'recall' && state.recall) {
      if (state.recall.phase === 'feedback') {
        const last = state.recall.i === state.recall.limit - 1;
        setMain({ label: last ? 'Termina sessione' : 'Prossima domanda', action: last ? endSession : nextQuestion });
      } else if (state.recall.phase === 'question') {
        const q = state.recall.qs[state.recall.i];
        const has = q?.tipo === 'quiz' ? !!state.recall.sel : !!(state.recall.text || '').trim();
        setMain({ label: 'Invia risposta', disabled: !(has || state.recall.voiceBlob), action: submitAnswer });
      }
    } else if (shell.view === 'read') {
      setMain(null);
    } else if (shell.view === 'lesson') {
      const l = lesson();
      if (l && l.stato === 'pronto') setMain({ label: 'Avvia recall', action: () => openSetup('lesson', l.id) });
      else if (l) setMain({ label: 'In elaborazione', disabled: true, action: null });
    } else if (shell.view === 'setup') {
      openSetup();
    } else if (shell.view === 'summary') {
      setMain({ label: 'Torna alle lezioni', action: () => { state.recall = null; show('lessons'); setMain(null); } });
    } else setMain(null);
  }

  document.addEventListener('keydown', e => {
    if (!$('#sheet').classList.contains('open')) return;
    if (e.key === 'Escape') closeSheet();
    if (e.key === 'Tab') {
      const items = Array.from($('#sheet').querySelectorAll('button:not([disabled]),audio')); const first = items[0], last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  function goBack() {
    if ($('#sheet').classList.contains('open')) closeSheet();
    else if (shell.view === 'recall') exitRecall();
    else if (shell.view === 'read') { stopAudio(); openLesson(state.lessonId); }
    else if (shell.view === 'setup' && state.scope.kind === 'lesson') openLesson(state.lessonId);
    else if (shell.view === 'lesson' || shell.view === 'setup' || shell.view === 'summary') { state.recall = null; show('lessons'); setMain(null); tg?.BackButton?.hide(); }
    else { show('lessons'); setMain(null); tg?.BackButton?.hide(); }
  }
  tg?.BackButton?.onClick(goBack); tg?.onEvent('themeChanged', applyTheme);
  $('.tg-close').onclick = () => { if (tg) tg.close(); else goBack(); };
  if (tg) { document.querySelector('.tg-top').hidden = true; tg.ready(); tg.expand(); }
  // Telegram 8.0+: collegamento alla Mini App sulla schermata Home, offerto solo finché manca.
  if (tg?.isVersionAtLeast?.('8.0') && tg.checkHomeScreenStatus) {
    const homeBtn = $('#homeScreenBtn');
    tg.checkHomeScreenStatus(status => { homeBtn.hidden = status !== 'missing'; });
    homeBtn.onclick = () => tg.addToHomeScreen();
    tg.onEvent('homeScreenAdded', () => { homeBtn.hidden = true; toast('Aggiunta alla schermata Home'); });
  }
  window.addEventListener('pagehide', () => { stopAudio(); stopRecording(); });
  window.addEventListener('unhandledrejection', event => { event.preventDefault(); errorMessage(event.reason); });
  async function boot() {
    $('#lessonsLoading').hidden = false; $('#lessonsList').hidden = true;
    try { await authenticate(); await loadLessons(); await resumeSession(); }
    catch (e) { errorMessage(e, boot); }
    finally { $('#lessonsLoading').hidden = true; }
  }
  applyTheme(); renderPractice(); setMain(null); boot();
})();
