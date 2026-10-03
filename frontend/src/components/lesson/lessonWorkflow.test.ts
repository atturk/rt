import type { Schemas } from '@/api/client'
import { isRewriting, liveRewrite } from './lessonWorkflow'

export const outline: Schemas['Outline'] = { lesson_title: 'Lezione', approved: true, timer_suspended: false, macro_sections: [
  { id: '1', title: 'Sezione', units: ['1.1', '1.2', '1.3'].map((id) => ({ id, title: `Unità ${id}`, key_concepts: [], start_segment_id: 's1', end_segment_id: 's2' })) },
] }
const document: Schemas['LessonDocument'] = { markdown: '## 1. Sezione\n### 1.1 Prima\n00:00\nTesto nuovo.\n### 1.2 Seconda\n00:20\nTesto vecchio.\n### 1.3 Terza\n00:30\nTesto vecchio.', html: '', final: false, sections: ['1.1', '1.2', '1.3'].map((unit_id) => ({ unit_id, title: unit_id, start_segment_id: 's1', end_segment_id: 's2' })) }
const job: Schemas['Job'] = { id: 'j', type: 'run_pipeline', state: 'running', attempts: 1, cancel_requested: false, payload: {}, progress: { phase: 'rewrite', unit_id: '1.2', current: 2, total: 3 } }

it('mostra i checkpoint precedenti, lo scheletro corrente e i titoli in attesa senza testo vecchio', () => {
  const live = liveRewrite(outline, document, job)
  expect(live.tasks).toEqual({ '1.1': 'done', '1.2': 'working', '1.3': 'waiting' })
  expect(live.document.markdown).toContain('Testo nuovo.')
  expect(live.document.markdown).toContain('00:00')
  expect(live.document.markdown).not.toContain('Testo vecchio.')
  expect(live.document.sections.map((s) => s.unit_id)).toEqual(['1.1'])
})
it('rende i titoli anche prima del primo checkpoint e mantiene il resto per un job di una sola unità', () => {
  expect(liveRewrite(outline, undefined, job).tasks).toEqual({ '1.1': 'waiting', '1.2': 'working', '1.3': 'waiting' })
  expect(liveRewrite(outline, document, { ...job, type: 'rewrite_unit' }).tasks['1.3']).toBe('done')
})
it('passa al documento completo alla fine della rielaborazione, mentre altri job restano attivi', () => {
  expect(isRewriting(job, false)).toBe(true)
  expect(isRewriting({ ...job, progress: { phase: 'rewrite', completed: true } }, true)).toBe(false)
  expect(isRewriting({ ...job, type: 'unit_relevance', progress: { phase: 'unit_relevance' } }, true)).toBe(false)
  expect(isRewriting({ ...job, state: 'succeeded' }, true)).toBe(false)
})
