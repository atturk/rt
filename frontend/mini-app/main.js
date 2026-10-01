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
  /* ─── stato ──────────────────────────────────────────────────────── */
  const state = {
    theme: store.get('rt-theme') || 'auto',
    materia: 'all', query: '', loaded: false,
    lessonId: null, setupType: 'quiz',
    scope: { kind: 'lesson', id: null },
    recall: null, sheet: { mode: 'browse', unitId: null, lesson: null },
    audio: { player: null, url: null }
  };

  const lesson = () => LEZIONI.find(l => l.id === state.lessonId);
  const materieCon = m => LEZIONI.filter(l => l.materia === m);
  const readyLessons = m => materieCon(m).filter(l => l.stato === 'pronto' && l.domande);
  const curLesson = () => {
    const r = state.recall;
    if (r && r.qs[r.i] && r.qs[r.i]._lesson) return r.qs[r.i]._lesson;
    return lesson();
  };
  const mmss = s => Math.floor(s / 60) + ':' + String(Math.max(0, Math.round(s) % 60)).padStart(2, '0');

  /* ─── tema ───────────────────────────────────────────────────────── */
function applyTheme() {
    const dark=state.theme==='dark'||(state.theme==='auto'&&(tg?tg.colorScheme==='dark':matchMedia('(prefers-color-scheme:dark)').matches));
    document.documentElement.dataset.theme=dark?'dark':'light';
  }
  $('#themeBtn').addEventListener('click', () => {
    state.theme = state.theme === 'auto' ? 'light' : state.theme === 'light' ? 'dark' : 'auto';
    store.set('rt-theme', state.theme);
    applyTheme();
    toast('Tema: ' + (state.theme === 'auto' ? 'automatico' : state.theme === 'dark' ? 'scuro' : 'chiaro'));
  });
  try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (state.theme === 'auto') applyTheme(); }); } catch {}

  /* ─── helper UI ──────────────────────────────────────────────────── */
  const VIEWS = { lessons: 'view-lessons', lesson: 'view-lesson', setup: 'view-setup', recall: 'view-recall', summary: 'view-summary' };
  const shell = { view: 'lessons', main: null };

  function show(view) {
    Object.keys(VIEWS).forEach(k => $('#' + VIEWS[k]).classList.toggle('active', k === view));
    shell.view = view;if(view==='lessons')tg?.BackButton?.hide();else tg?.BackButton?.show();if(view==='recall')tg?.enableClosingConfirmation?.();
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
    l.domande = Object.fromEntries(['quiz','mirata','vasta'].map(k => [k,{length:questions[k]?.pending || 0}]));
  }
  async function loadLessons() {
    const rows = await request('/lessons');
    Object.keys(MATERIE).forEach(k=>delete MATERIE[k]); LEZIONI.splice(0);
    rows.sort((a,b)=>(b.data||'').localeCompare(a.data||'')).forEach((row,i)=>{
      const materia = row.materia || 'Varie'; MATERIE[materia] = materia;
      const date = row.data ? new Date(row.data + 'T12:00:00') : null;
      const valid = date && !Number.isNaN(date.getTime());
      const l = {id:String(row.id),materia,num:i+1,titolo:row.titolo||row.argomenti||'Lezione',argomento:row.argomenti||'',
        data:valid?date.toLocaleDateString('it-IT',{day:'numeric',month:'long',year:'numeric'}):row.data||'Data non disponibile',
        short:valid?date.toLocaleDateString('it-IT',{day:'numeric',month:'short'}):'—',
        durata:'—',durataSec:0,unita:[],stato:row.ready?'pronto':'trascrizione',loaded:false};
      counts(l,row.questions||{});LEZIONI.push(l);
    });
    renderChips();renderLessons();renderSubjects();
  }
  async function loadLesson(l) {
    if (!l || l.loaded) return;
    const d = await request(lessonPath(l.id));
    l.unita=d.units.map(u=>({id:u.id,titolo:u.title,testo:u.content,html:u.html,t0:u.start,t1:u.end,audioOff:!d.has_audio}));
    l.stato=d.ready?'pronto':'trascrizione';counts(l,d.questions);l.loaded=true;
    l.durataSec=Math.max(0,...l.unita.map(u=>u.t1||0));l.durata=d.has_audio?mmss(l.durataSec):'—';
  }
  function mapQuestion(q,l) {
    return {id:q.id,testo:q.question_text,unitIds:q.unit_ids,_lesson:l,
      opzioni:(q.options||[]).map((testo,i)=>({id:String.fromCharCode(65+i),testo})),
      corretta:q.correct_index==null?null:String.fromCharCode(65+q.correct_index),spiegazione:q.explanation};
  }
  function saveSession() {
    const r=state.recall;
    try {
      if (!r) {sessionStorage.removeItem('rt-mini-session');return;}
      const q=r.qs[r.i];
      sessionStorage.setItem('rt-mini-session',JSON.stringify({scope:r.scope,type:r.type,i:r.i,limit:r.limit,lessonId:q?._lesson.id,questionId:q?.id,jobId:r.jobId}));
    } catch { /* Storage can be disabled by the WebView; the current session still works. */ }
  }
  async function fetchQuestion(exclude) {
    stopRecording();
    const r=state.recall;
    let picked;
    if(r.scope.kind==='materia') picked=await request('/subject/next?'+new URLSearchParams({materia:r.scope.id,qtype:r.type,...(exclude?{exclude}: {})}),{method:'POST'});
    else picked={lesson_id:r.scope.id,question:await request(lessonPath(r.scope.id,'/next?')+new URLSearchParams({qtype:r.type,...(exclude?{exclude_id:exclude}: {})}),{method:'POST'})};
    const l=LEZIONI.find(l=>l.id===String(picked.lesson_id));
    r.qs[r.i]=mapQuestion(picked.question,l);r.jobId=null;saveSession();await loadLesson(l);show('recall');renderQuestion();
  }
  async function generateScope() {
    const sc=state.scope;setMain({label:'Preparazione in corso…',disabled:true});
    const ls=sc.kind==='materia'?readyLessons(sc.id):[lesson()];
    for(const l of ls) {
      const accepted=await request(lessonPath(l.id,'/generate?qtype='+state.setupType),{method:'POST'});
      await waitJob(accepted);
    }
    await loadLessons();
    if(sc.kind==='lesson'){state.lessonId=sc.id;await loadLesson(lesson());}
    openSetup(sc.kind,sc.id);
  }
  async function resumeSession() {
    let saved;try {saved=JSON.parse(sessionStorage.getItem('rt-mini-session'));}catch{return;}
    if(!saved?.questionId) return;
    try {
      const data=await request(lessonPath(saved.lessonId,'/resume?')+new URLSearchParams({question_id:saved.questionId,...(saved.scope.kind==='materia'?{materia:saved.scope.id}:{})}));
      const l=LEZIONI.find(l=>l.id===String(saved.lessonId));await loadLesson(l);state.lessonId=l.id;state.scope=saved.scope;
      state.recall={type:saved.type,scope:saved.scope,i:saved.i,limit:saved.limit,qs:[],voted:{},records:[],phase:'question'};
      const r=state.recall;r.qs[r.i]=mapQuestion(data.question,l);show('recall');renderQuestion();
      if(data.answer) restoredAnswer(data);
      else if(data.pending_job){r.jobId=data.pending_job.job_id;saveSession();await grade(null,false);}
    }catch(e) {if(e.status===404){sessionStorage.removeItem('rt-mini-session');return;}throw e;}
  }

  function restoredAnswer(data) {
    const r=state.recall,q=r.qs[r.i];
    Object.assign(q,mapQuestion(data.question,q._lesson));r.text=data.answer.answer_text;
    r.transcript=data.answer.is_voice?data.answer.answer_text:'';r.evaluation=data.answer.evaluation;
    const selected=r.type==='quiz'?q.opzioni.find(o=>o.testo===data.answer.answer_text)?.id:null;
    const correct=selected!=null&&selected===q.corretta;
    const feedback=r.type==='quiz'?{kind:correct?'ok':'no',label:correct?'Corretto':'Sbagliato'}:{kind:'none',label:'Risposta registrata'};
    r.jobId=null;r.uncertain=false;renderFeedback(selected,false,feedback);saveSession();
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
    if (l.stato === 'pronto') return 'Appunti disponibili';
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
  function renderSubjects() {
    const used = Object.keys(MATERIE).filter(m => LEZIONI.some(l => l.materia === m));
    $('#lessonHead').textContent = LEZIONI.length + (LEZIONI.length === 1 ? ' lezione' : ' lezioni');
    $('#subjectRow').innerHTML = used.map(m => {
      const tot = materieCon(m).length;
      const q = readyLessons(m).reduce((n, l) => n + countQ(l), 0);
      return '<button class="subject-card" data-subject="' + esc(m) + '">' +
        '<span class="sc-name">' + esc(MATERIE[m]) + '</span>' +
        '<span class="sc-meta">' + tot + (tot === 1 ? ' lezione' : ' lezioni') + ' · ' + q + ' domande pronte</span>' +
        '<span class="sc-bar">Avvia recall →</span></button>';
    }).join('');
  }
  $('#subjectRow').addEventListener('click', e => {
    const c = e.target.closest('.subject-card'); if (!c || c.disabled) return;
    openSetup('materia', c.dataset.subject);
  });

  /* ─── dettaglio lezione ──────────────────────────────────────────── */
  async function openLesson(id) {
    try {const l=LEZIONI.find(l=>l.id===String(id));await loadLesson(l);}catch(e){errorMessage(e,()=>openLesson(id));return;}
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
      '<div class="vh"><span class="pill">' + esc(MATERIE[l.materia]) + ' ' + '</span>' +
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
          '<span class="ui-t num">' + mmss(u.t0) + '</span></button></li>').join('') + '</ul>' +
      '</div>' +
      '<div style="margin-top:14px"><button class="btn btn-secondary btn-block" data-units>' +
        '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg> Consulta le unità senza recall</button>' +
        (countQ(l) ? '<button class="btn btn-secondary btn-block" data-regen style="margin-top:10px">' +
          '<svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/><path d="M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Genera altre domande</button>' +
          '' : '') +
      '</div>';

    wireBack(v);
    v.onclick = function (e) {
      const b = e.target.closest('[data-unit]');
      if (b) { openSheet('browse', b.dataset.unit); return; }
      if (e.target.closest('[data-units]')) { openSheet('browse', l.unita[0].id); return; }
      const rg = e.target.closest('[data-regen]');
      if (rg) regenPool(l, rg);
    };
    show('lesson');
    if (l.stato === 'pronto') setMain({ label: 'Avvia recall', action: openSetup });
    else setMain({ label: l.stato === 'elaborazione' ? 'Domande in preparazione' : 'In elaborazione', disabled: true, action: null });
  }

  function countQ(l) {
    if (!l.domande) return 0;
    return ['quiz', 'mirata', 'vasta'].reduce((n, k) => n + (l.domande[k] ? l.domande[k].length : 0), 0);
  }
  function wireBack(v) {
    const b = v.querySelector('[data-back]');
    if (b) b.addEventListener('click', () => { show('lessons'); setMain(null); });
  }


function regenPool(l, btn) {
    guarded(async()=>{btn.disabled=true;btn.textContent='Generazione in corso…';
      const job=await request(lessonPath(l.id,'/generate?qtype='+state.setupType),{method:'POST'});await waitJob(job);
      l.loaded=false;await openLesson(l.id);renderSubjects();
    },()=>regenPool(l,btn));
  }

  /* ─── preparazione recall ────────────────────────────────────────── */
  const TIPI = [
    { id: 'quiz', t: 'Quiz', d: 'Scelta multipla con esito corretto o sbagliato e spiegazione.', ex: '4 opzioni' },
    { id: 'mirata', t: 'Mirata', d: 'Domanda aperta su un contenuto circoscritto, a una o due unità.', ex: 'risposta scritta o vocale' },
    { id: 'vasta', t: 'Vasta', d: 'Domanda aperta più ampia, che può coinvolgere più unità.', ex: 'risposta scritta o vocale' }
  ];

  function openSetup(kind, id) {
    if (kind === 'materia') state.scope = { kind: 'materia', id: id };
    else if (kind === 'lesson') state.scope = { kind: 'lesson', id: id };
    else if (!state.scope.id) state.scope = { kind: 'lesson', id: state.lessonId };

    const isMateria = state.scope.kind === 'materia';
    const scopeLessons = isMateria ? readyLessons(state.scope.id) : [lesson()];
    const title = isMateria ? MATERIE[state.scope.id] : lesson().titolo;
    const sub = isMateria
      ? scopeLessons.length + (scopeLessons.length === 1 ? ' lezione' : ' lezioni') + ' · domande da tutta la materia'
      : 'Scegli il tipo di domanda per questa sessione';

    const avail = { quiz: 0, mirata: 0, vasta: 0 };
    scopeLessons.forEach(l => { if (l && l.domande) ['quiz', 'mirata', 'vasta'].forEach(k => { avail[k] += (l.domande[k] || []).length; }); });
    const ready = scopeLessons.length > 0;
    if (!state.setupType || !avail[state.setupType]) state.setupType = ['quiz', 'mirata', 'vasta'].find(k => avail[k]) || 'quiz';

    const v = $('#view-setup');
    v.innerHTML =
      '<button class="back" data-back><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg> ' + esc(title) + '</button>' +
      '<div class="vh"><h1>Prepara il recall</h1><p class="sub">' + esc(sub) + '</p></div>' +
      (isMateria ? '<div class="notice info" style="margin-bottom:14px"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg><span>Sessione su tutta la materia: le domande arrivano da tutte le lezioni disponibili.</span></div>' : '') +
      TIPI.map(t =>
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
        s.innerHTML = '<div class="notice">Questa materia non ha ancora lezioni con appunti disponibili. Completa l’elaborazione in RT.</div>';
        setMain(null);
        return;
      }
      if (!avail[state.setupType]) {
        s.innerHTML = '<div class="notice"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg><span>Per questo tipo non ci sono ancora domande. Puoi generarne un nuovo gruppo.</span></div>';
        setMain({ label: 'Genera domande', action: () => guarded(generateScope,()=>openSetup()) });
        return;
      }
      s.innerHTML = '<div class="notice info"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg><span>' + avail[state.setupType] + ' domande pronte' + (isMateria ? ' dalle lezioni della materia' : '') + ' · puoi terminare la sessione in qualsiasi momento.</span></div>';
      setMain({ label: 'Avvia sessione', action: startRecall });
    }

    v.querySelectorAll('.choice').forEach(c => c.addEventListener('click', () => {
      state.setupType = c.dataset.type;
      v.querySelectorAll('.choice').forEach(x => x.setAttribute('aria-pressed', String(x === c)));
      updateStatus();
    }));
    const backBtn = v.querySelector('[data-back]');
    if (backBtn) backBtn.addEventListener('click', () => {
      if (isMateria) { show('lessons'); setMain(null); }
      else openLesson(state.lessonId);
    });
    show('setup');
    updateStatus();
  }

  /* ─── sessione recall ────────────────────────────────────────────── */
function startRecall() {
    guarded(async()=>{
      const ls=state.scope.kind==='materia'?readyLessons(state.scope.id):[lesson()];
      const limit=ls.reduce((n,l)=>n+(l.domande[state.setupType]?.length||0),0);
      state.recall={type:state.setupType,scope:{...state.scope},qs:[],i:0,limit:Math.max(1,limit),phase:'question',sel:null,text:'',transcript:'',voted:{},records:[]};
      setMain({label:'Caricamento…',disabled:true});await fetchQuestion();
    },()=>{state.recall=null;openSetup();});
  }

  function renderQuestion() {
    const r = state.recall, q = r.qs[r.i];
    r.phase = 'question'; r.sel = null; r.text = ''; r.transcript = ''; r.evaluation = ''; r.voiceBlob = null;
    $('#qProg').textContent = 'Domanda ' + (r.i + 1) + ' di ' + r.limit;
    $('#qBar').style.width = ((r.i) / r.limit * 100) + '%';
    $('#qType').textContent = r.type === 'quiz' ? 'Quiz' : r.type === 'mirata' ? 'Mirata' : 'Vasta';
    $('#qText').textContent = q.testo;
    const nU = (q.unitIds || []).length;
    $('#qUnits').textContent = nU > 1 ? 'Domanda su ' + nU + ' unità didattiche' : 'Domanda su una unità didattica';
    $('#qPhase').hidden = false; $('#qGrading').hidden = true; $('#qFeedback').hidden = true;

    const body = $('#qBody');
    if (r.type === 'quiz') {
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
        '<textarea aria-label="La tua risposta" class="textarea" id="openAnswer" placeholder="Scrivi la tua risposta, oppure rispondi a voce…"></textarea>' +
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
    $('#micBtn').onclick=async()=>{
      const btn=$('#micBtn'),lbl=$('#micLabel');
      if(recording?.state==='recording'){recording.stop();return;}
      try{
        if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Registrazione non disponibile: rispondi a testo.');
        const recallRef=state.recall;
        const stream=await navigator.mediaDevices.getUserMedia({audio:true});
        if(state.recall!==recallRef||recallRef.phase!=='question'||shell.view!=='recall'){stream.getTracks().forEach(t=>t.stop());return;}
        mediaStream=stream;
        const type=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
        recording=new MediaRecorder(mediaStream,type?{mimeType:type}:{});const chunks=[];
        recording.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
        recording.onstop=()=>{state.recall.voiceBlob=new Blob(chunks,{type:recording.mimeType});mediaStream.getTracks().forEach(t=>t.stop());mediaStream=null;lbl.textContent='Registra di nuovo';btn.classList.remove('rec');$('#micState').textContent='Vocale pronto per l’invio';setMain({label:'Invia risposta vocale',action:submitAnswer});};
        recording.start();btn.classList.add('rec');lbl.textContent='Ferma';setMain({label:'Ferma la registrazione',disabled:true});
      }catch(e){mediaStream?.getTracks().forEach(t=>t.stop());errorMessage(e);}
    };
  }

  function submitAnswer() { grade(state.recall.sel, false); }


async function grade(selected, dontKnow) {
    if(operation || state.recall.phase!=='question') return;
    stopRecording();
    await guarded(async()=>{
      const r=state.recall,q=r.qs[r.i];r.phase='grading';
      $('#qPhase').hidden=true;$('#qFeedback').hidden=true;$('#qGrading').hidden=false;setMain(null);
      try {
        let result;
        if(r.uncertain || r.jobId){
          const saved=await request(lessonPath(q._lesson.id,'/resume?')+new URLSearchParams({question_id:q.id,...(r.scope.kind==='materia'?{materia:r.scope.id}:{})}));
          if(saved.answer){restoredAnswer(saved);return;}
          result=saved.pending_job;
        }
        if(result?.job_id){r.jobId=result.job_id;}
        else if(r.voiceBlob&&!dontKnow){
          r.uncertain=true;
          const data=new FormData();data.append('question_id',q.id);
          const type=r.voiceBlob.type;const ext=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';data.append('audio',r.voiceBlob,'answer.'+ext);
          result=await request(lessonPath(q._lesson.id,'/answer-voice'),{method:'POST',body:data});
        }else {
          r.uncertain=true;
          result=await request(lessonPath(q._lesson.id,'/answer'),{method:'POST',body:{question_id:q.id,choice:r.type!=='quiz'||selected==null?null:q.opzioni.findIndex(o=>o.id===selected),answer:r.text,dont_know:dontKnow}});
        }
        if(result.job_id){
          r.jobId=result.job_id;saveSession();const answer=await waitJob(result);r.evaluation=answer.evaluation;r.transcript=answer.is_voice?answer.answer:'';r.jobId=null;
        } else {q.corretta=result.question.correct_index==null?null:String.fromCharCode(65+result.question.correct_index);q.spiegazione=result.question.explanation;}
        const feedback=dontKnow?{kind:'none',label:'Non risposto'}:r.type==='quiz'?{kind:result.correct?'ok':'no',label:result.correct?'Corretto':'Sbagliato'}:{kind:'none',label:'Valutazione della risposta'};
        r.uncertain=false;r.records.push(feedback.kind);renderFeedback(selected,dontKnow,feedback);saveSession();
      }catch(e){if(e.code==='job_failed'){r.jobId=null;r.uncertain=false;}r.phase='question';$('#qPhase').hidden=false;$('#qGrading').hidden=true;softMain();throw e;}
    },()=>grade(selected,dontKnow));
  }

  function renderFeedback(selected, dontKnow, result) {
    const r = state.recall, q = r.qs[r.i];
    r.phase = 'feedback';
    $('#qGrading').hidden = true;
    const fb = $('#qFeedback');
    fb.hidden = false;

    let badges = { ok: 'ok', no: 'no', warn: 'warn', none: 'none' };
    const icon = result.kind === 'ok'
      ? '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>'
      : result.kind === 'no' ? '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>'
      : result.kind === 'warn' ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>'
      : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.4 2.3c-.9.4-1.4 1-1.4 2"/><path d="M12 17h.01"/></svg>';

    const qLesson = curLesson();
    const scope = r.scope || state.scope;
    let html = '<div class="fb-head"><span class="badge ' + badges[result.kind] + '">' + icon + result.label + '</span>' +
      (scope.kind === 'materia' && qLesson ? '<span class="meta">' + esc(qLesson.titolo) + '</span>' : '') +
      (r.type === 'vasta' && !dontKnow ? '<span class="meta">valutazione indicativa</span>' : '') + '</div>';




    if (r.type === 'quiz') {
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

    if (q.spiegazione) {
      html += '<div class="block"><div class="b-label">Spiegazione</div><p>' + esc(q.spiegazione) + '</p></div>';
    }

    if(r.type!=='quiz') html+='<div class="block"><div class="b-label">Valutazione di RT</div><div style="white-space:pre-wrap">'+esc(r.evaluation||'Valutazione non disponibile.')+'</div></div>';

    const srcs = (q.unitIds || []).map(id => qLesson.unita.find(u => u.id === id)).filter(Boolean);
    html += '<div class="block"><div class="b-label">Unità di riferimento' + (scope.kind === 'materia' ? ' · ' + esc(qLesson.titolo) : '') + '</div>' +
      srcs.map(u => '<button class="src-chip" data-unit="' + esc(u.id) + '" data-lesson="' + qLesson.id + '"><span class="n num">' + String(qLesson.unita.indexOf(u) + 1).padStart(2, '0') + '</span>' + esc(u.titolo) + '</button>').join('') +
      '<div class="meta" style="margin-top:6px">Testo e audio si aprono senza perdere la domanda e il feedback.</div></div>';

    html += '<div class="block"><div class="vote"><span class="v-label">Questa domanda è stata utile?</span>' +
      [['up','👍'], ['down','👎'], ['lightning','⚡']].map(([v,label]) => '<button data-vote="' + v + '" aria-pressed="' + (r.voted[r.i] === v) + '" aria-label="Vota ' + label + '">' + label + '</button>').join('') +
      '</div></div>';

    fb.innerHTML = html;

    fb.querySelectorAll('[data-unit]').forEach(b => b.addEventListener('click', () => {
      const ll = LEZIONI.find(x => x.id === b.dataset.lesson) || curLesson();
      openSheet('recall', b.dataset.unit, ll);
    }));
    fb.querySelectorAll('[data-vote]').forEach(b=>b.onclick=()=>guarded(async()=>{
      await request(lessonPath(q._lesson.id,'/vote'),{method:'POST',body:{question_id:q.id,vote:b.dataset.vote}});
      r.voted[r.i]=b.dataset.vote;fb.querySelectorAll('[data-vote]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));toast('Voto registrato');
    }));

    const last = r.i === r.limit - 1;
    setMain({ label: last ? 'Termina sessione' : 'Prossima domanda', action: last ? endSession : nextQuestion });
    $('#qBar').style.width = ((r.i + 1) / r.limit * 100) + '%';
  }

function nextQuestion() {
    guarded(async()=>{const r=state.recall;r.i++;try{await fetchQuestion();}catch(e){r.i--;throw e;}},nextQuestion);
  }

function skipQuestion() {
    stopRecording();
    guarded(async()=>{const r=state.recall,q=r.qs[r.i];await request(lessonPath(q._lesson.id,'/skip'),{method:'POST',body:{question_id:q.id}});
      if(r.i>=r.limit-1){await finishSession();return;}
      r.i++;try{await fetchQuestion(r.scope.kind==='materia'?q._lesson.id+':'+q.id:q.id);}catch(e){r.i--;throw e;}
    },skipQuestion);
  }

function endSession() { guarded(finishSession,endSession); }
  async function finishSession() {
    const r=state.recall;stopRecording();
    const result=r.scope.kind==='materia'?await request('/subject/end?'+new URLSearchParams({materia:r.scope.id}),{method:'POST'}):await request(lessonPath(r.scope.id,'/end'),{method:'POST'});
    sessionStorage.removeItem('rt-mini-session');tg?.disableClosingConfirmation?.();
    const s=result.summary||{};const label=r.scope.kind==='materia'?r.scope.id:lesson()?.titolo;
    $('#view-summary').innerHTML='<div class="summary"><div class="ring">✓</div><h1>Sessione completata</h1><p class="lead">'+esc(label||'')+'</p><div class="sgrid">'+
      [[s.questions||0,'domande poste'],[s.answered||0,'risposte registrate'],[s.correct||0,'quiz corretti'],[s.quiz_answered||0,'quiz risposti']].map(([n,l])=>'<div class="cell"><div class="k num">'+n+'</div><div class="l">'+l+'</div></div>').join('')+'</div></div>';
    show('summary');setMain({label:'Torna alle lezioni',action:()=>{state.recall=null;show('lessons');setMain(null);loadLessons().catch(e=>errorMessage(e));}});
  }
  function stopRecording() {
    if(recording?.state==='recording'){recording.onstop=null;recording.stop();}
    mediaStream?.getTracks().forEach(t=>t.stop());mediaStream=null;
  }

  $('#exitRecall').addEventListener('click',endSession);
  /* ─── drawer unità ───────────────────────────────────────────────── */
  function openSheet(mode, unitId, lessonRef) {
    $('#sheetError').hidden=true;
    const l = lessonRef || (mode === 'recall' ? curLesson() : lesson());
    state.sheet = { mode: mode, unitId: unitId || (l.unita[0] && l.unita[0].id), lesson: l };
    $('#sheetCtx').textContent = mode === 'recall' ? 'Unità di riferimento · ' + MATERIE[l.materia] : MATERIE[l.materia];
    $('#sheetTitle').textContent = l.titolo;
    $('#sheetFoot').hidden = mode !== 'recall';
    $('#backToFeedback').lastChild.textContent = state.recall?.phase === 'feedback' ? ' Torna al feedback' : ' Torna alla domanda';
    renderUnitList();
    renderUnit(state.sheet.unitId);
    sheetFocus=document.activeElement;$('#sheet').classList.add('open');$('#sheetClose').focus();$('#app').inert=true;tg?.BackButton?.show();
    setMain(null);
  }
  function closeSheet() {
    stopAudio();clearImages();
    $('#sheet').classList.remove('open');$('#app').inert=false;sheetFocus?.focus();
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
      '<div class="row-between"><span class="u-time num">' + (u.t0==null||u.t1==null?'Tempi non disponibili':mmss(u.t0) + ' – ' + mmss(u.t1)) + '</span>' +
      '<span class="tag">Unità ' + idx + ' di ' + l.unita.length + '</span></div>' +
      (playable ? '<div id="audioSlot"></div>' : '') +
      '<h3>' + esc(u.titolo) + '</h3>' +
      '<div class="body-txt">' + (u.html || esc(u.testo)) + '</div>' +
      (playable ? '' : '<div id="audioSlot"></div>');
    renderAudio(u);renderDelimitedMath($('.body-txt')).catch(()=>{});
    $('.body-txt').querySelectorAll('img[data-rt-image]').forEach(async img=>{
      try {
        const blob=await request(lessonPath(l.id,'/images/'+encodeURIComponent(img.dataset.rtImage)),{blob:true});
        if(!img.isConnected||!$('#sheet').classList.contains('open'))return;
        const url=URL.createObjectURL(blob);imageUrls.push(url);img.src=url;
      }catch {img.replaceWith(document.createTextNode(img.alt||'Immagine non disponibile'));}
    });
  }
  const imageUrls=[];
  function clearImages(){imageUrls.splice(0).forEach(url=>URL.revokeObjectURL(url));}
function renderAudio(u) {
    stopAudio();const slot=$('#audioSlot');
    if(!u.t1||u.audioOff){slot.innerHTML='<div class="notice">Audio non disponibile per questa unità.</div>';return;}
    slot.innerHTML='<div class="player"><button class="btn btn-secondary" id="loadAudio">Ascolta audio</button></div><button class="btn btn-ghost" id="sendAudio">Invia audio su Telegram</button>';
    $('#loadAudio').onclick=async()=>{
      const lessonId=state.sheet.lesson.id;const unitId=u.id;const btn=$('#loadAudio');btn.disabled=true;
      try{const blob=await request(lessonPath(lessonId,'/units/'+encodeURIComponent(unitId)+'/audio'),{blob:true});
        if(state.sheet.unitId!==unitId||state.sheet.lesson.id!==lessonId||!$('#sheet').classList.contains('open'))return;
        const url=URL.createObjectURL(blob);state.audio.url=url;
        slot.querySelector('.player').innerHTML='<audio controls aria-label="Audio dell’unità"></audio>';
        const player=slot.querySelector('audio');player.src=url;state.audio.player=player;await player.play().catch(()=>{});
      }catch(e){btn.disabled=false;errorMessage(e);}
    };
    $('#sendAudio').onclick=()=>guarded(async()=>{await request(lessonPath(state.sheet.lesson.id,'/units/'+encodeURIComponent(u.id)+'/send-audio'),{method:'POST'});toast('Audio inviato su Telegram');});
  }
function stopAudio() {
    state.audio.player?.pause();state.audio.player=null;
    if(state.audio.url){URL.revokeObjectURL(state.audio.url);state.audio.url=null;}
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
        const has = state.recall.type === 'quiz' ? !!state.recall.sel : !!(state.recall.text || '').trim();
        setMain({ label: 'Invia risposta', disabled: !(has||state.recall.voiceBlob), action: submitAnswer });
      }
    } else if (shell.view === 'lesson') {
      const l = lesson();
      if (l && l.stato === 'pronto') setMain({ label: 'Avvia recall', action: openSetup });
      else if (l) setMain({ label: 'In elaborazione', disabled: true, action: null });
    } else if (shell.view === 'setup') {
      openSetup();
    } else if (shell.view === 'summary') {
      setMain({ label: 'Torna alle lezioni', action: () => { state.recall = null; show('lessons'); setMain(null); } });
    } else setMain(null);
  }


  document.addEventListener('keydown',e=>{
    if(!$('#sheet').classList.contains('open'))return;
    if(e.key==='Escape')closeSheet();
    if(e.key==='Tab'){
      const items=Array.from($('#sheet').querySelectorAll('button:not([disabled]),audio'));const first=items[0],last=items.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
  });
  function goBack(){if($('#sheet').classList.contains('open'))closeSheet();else if(shell.view==='recall')endSession();else if(shell.view==='setup'&&state.scope.kind==='lesson')openLesson(state.lessonId);else{show('lessons');setMain(null);tg?.BackButton?.hide();}}
  tg?.BackButton?.onClick(goBack);tg?.onEvent('themeChanged',applyTheme);
  $('.tg-close').onclick=()=>{if(tg)tg.close();else goBack();};
  if(tg){document.querySelector('.tg-top').hidden=true;tg.ready();tg.expand();}
  window.addEventListener('pagehide',()=>{stopAudio();stopRecording();});
  window.addEventListener('unhandledrejection',event=>{event.preventDefault();errorMessage(event.reason);});
  async function boot(){
    $('#lessonsLoading').hidden=false;$('#lessonsList').hidden=true;
    try{await authenticate();await loadLessons();await resumeSession();}
    catch(e){errorMessage(e,boot);}
    finally{$('#lessonsLoading').hidden=true;}
  }
  applyTheme();setMain(null);boot();
})();
