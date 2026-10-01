import { fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import html from '../mini-app.html?raw'

const question = { id: 'q1', type: 'quiz', question_text: 'Quale struttura?', unit_ids: ['u1'], options: ['Cuore', 'Fegato'] }
const counts = { quiz: { pending: 1 }, mirata: { pending: 1 }, vasta: { pending: 0 } }
let pending: boolean, completed: boolean, voiceResult: boolean, calls: string[]
const $ = (s: string) => document.querySelector<HTMLElement>(s)!
const click = (s: string) => fireEvent.click($(s))
const ready = (s: string, text: string) => waitFor(() => expect($(s)).toHaveTextContent(text))

beforeEach(async () => {
  vi.resetModules()
  localStorage.clear(); sessionStorage.clear()
  document.body.innerHTML = html.split('<body>')[1].split('</body>')[0]
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn() }))
  pending = false; completed = false; voiceResult = false; calls = []
  vi.stubGlobal('fetch', vi.fn(async (input: string, options: RequestInit = {}) => {
    const url = new URL(input, 'http://localhost')
    const path = url.pathname.replace('/api/v1/mini-app', '')
    calls.push((options.method || 'GET') + ' ' + path)
    let data: unknown, status = 200
    if (path === '/auth') data = { token: 'study-token' }
    else if (path === '/lessons') data = [{ id: 1, materia: 'ANATOMIA', titolo: 'Lezione di anatomia', data: '2026-09-01', ready: true, questions: counts }]
    else if (path === '/lessons/1') data = { ready: true, has_audio: false, units: [{ id: 'u1', title: 'Il cuore', content: 'Appunti di RT', html: '<p>Appunti di RT</p>', start: 0, end: 60 }], questions: counts }
    else if (path === '/lessons/1/next') data = { ...question, type: url.searchParams.get('qtype') || 'quiz' }
    else if (path === '/lessons/1/resume') data = { question, answer: null, pending_job: pending ? { job_id: 'job1', worker_available: completed } : null }
    else if (path === '/lessons/1/answer') {
      const body = JSON.parse(options.body as string)
      if (body.choice == null && !body.dont_know) { pending = true; status = 202; data = { job_id: 'job1', worker_available: false } }
      else data = { correct: true, question: { ...question, correct_index: 0, explanation: 'Spiegazione del backend' } }
    } else if (path === '/jobs/job1') data = { state: completed ? 'succeeded' : 'queued', worker_available: completed, result: { evaluation: 'Valutazione del worker', answer: 'Risposta dello studente', is_voice: voiceResult } }
    else if (path === '/lessons/1/vote') { expect(JSON.parse(options.body as string).vote).toBe('up'); data = { message: 'Voto registrato' } }
    else if (path === '/lessons/1/end') data = { summary: { questions: 1, answered: 1, quiz_answered: 1, correct: 1 } }
    else throw new Error('Unexpected API call ' + path)
    return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
  }))
  // The production entry is plain JS; Vite transforms its existing TS math import.
  // @ts-expect-error This entry intentionally has no TypeScript declaration.
  await import('../mini-app/main.js')
  await ready('#lessonsList', 'Lezione di anatomia')
})

describe('Telegram study frontend', () => {
  it('consults units independently and keeps feedback while consulting during recall', async () => {
    click('.lesson-row')
    await ready('#view-lesson', 'Consulta le unità senza recall')
    click('[data-units]')
    expect($('#sheet')).toHaveClass('open')
    expect($('#unitRead')).toHaveTextContent('Appunti di RT')
    expect($('#audioSlot')).toHaveTextContent('Audio non disponibile')
    expect(calls.some(c => c.endsWith('/next'))).toBe(false)
    click('#sheetClose')
    click('#mainBtn'); click('#mainBtn')
    await ready('#qText', 'Quale struttura?')
    expect($('#qFeedback')).toBeEmptyDOMElement()
    click('[data-opt="A"]')
    click('#consultQuestion'); click('#sheetClose')
    expect($('[data-opt="A"]')).toHaveAttribute('aria-pressed', 'true')
    expect($('#mainBtn')).toBeEnabled()
    expect(calls.some(c => c === 'POST /lessons/1/answer')).toBe(false)
    click('#mainBtn')
    await ready('#qFeedback', 'Spiegazione del backend')
    click('.src-chip'); click('#sheetClose')
    expect($('#qFeedback')).toHaveTextContent('Spiegazione del backend')
    click('[data-vote]')
    await waitFor(() => expect($('[data-vote]')).toHaveAttribute('aria-pressed', 'true'))
    click('#mainBtn')
    await ready('#view-summary', 'Sessione completata')
  })

  it('resumes a queued evaluation after worker restart without submitting again', async () => {
    click('.lesson-row')
    await ready('#view-lesson', 'Consulta le unità senza recall')
    click('#mainBtn'); click('[data-type="mirata"]'); click('#mainBtn')
    await ready('#qText', 'Quale struttura?')
    fireEvent.input($('#openAnswer'), { target: { value: 'Risposta dello studente' } })
    click('#mainBtn')
    await ready('#studyError', 'Avvia il worker')
    expect(calls.filter(c => c === 'POST /lessons/1/answer')).toHaveLength(1)
    expect(JSON.parse(sessionStorage.getItem('rt-mini-session')!).jobId).toBe('job1')
    completed = true
    click('#studyError button')
    await ready('#qFeedback', 'Valutazione del worker')
    expect(calls.filter(c => c === 'POST /lessons/1/answer')).toHaveLength(1)
  })

  it('keeps the voice transcript when resuming an evaluation after a reload', async () => {
    sessionStorage.setItem('rt-mini-session', JSON.stringify({
      scope: { kind: 'lesson', id: '1' }, type: 'mirata', i: 0, limit: 1,
      lessonId: '1', questionId: 'q1', jobId: 'job1',
    }))
    pending = true; completed = true; voiceResult = true
    document.body.innerHTML = html.split('<body>')[1].split('</body>')[0]
    vi.resetModules()
    // @ts-expect-error Production entry is plain JS.
    await import('../mini-app/main.js')
    await ready('#qFeedback', 'Trascrizione della risposta vocale')
    expect($('#qFeedback')).toHaveTextContent('Risposta dello studente')
    expect($('#qFeedback')).toHaveTextContent('Valutazione del worker')
    expect(calls.filter(c => c === 'POST /lessons/1/answer')).toHaveLength(0)
  })
})
