import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import { LessonRow, StudyRing } from './LessonsView'
import type { Lesson } from '@/lib/format'

vi.mock('@/api/settings', () => ({
  useSettings: () => ({ data: { stati_studio: [{ id: 'ripasso', nome: 'Ripasso', colore: 'text-blue-500', icona: 'Star' }] } }),
}))

export const lesson = { id: 15, titolo: 'Emogasanalisi', materia: '', data: '', docente: '', argomenti: '', ora: '', folder_name: '', path: '', unit_count: 10, study_learned: 3, study_learning: 2, study_ignored: 1, recall_questions: 4, recall_pending: 0, pending_issues: 0, media_count: 0, phases: { rewrite: 'VALID', review: 'VALID', build: 'VALID' } } as Lesson
it('l’anello usa i colori dello studio con stacchi fra gli archi', () => {
  render(<MemoryRouter><StudyRing lesson={lesson} /></MemoryRouter>)
  const ring = screen.getByTestId('lesson-study-ring')
  for (const color of ['track', 'learned', 'learning', 'ignored']) expect(ring.querySelector(`.stroke-study-${color}`)).toBeInTheDocument()
  expect(ring.querySelector('.stroke-study-learned')).toHaveAttribute('stroke-dasharray', '27 73')
})

it('l’anello mostra gli stati personalizzati col loro colore, dopo «in apprendimento»', () => {
  render(<MemoryRouter><StudyRing lesson={{ ...lesson, study_learning: 5, study_custom: { ripasso: 3, eliminato: 1 } }} /></MemoryRouter>)
  const ring = screen.getByTestId('lesson-study-ring')
  // 5 in apprendimento di cui 3 «Ripasso»: restano 2 gialle (anche quella con stato eliminato)
  expect(ring.querySelector('[data-testid="study-ring-learning"]')).toHaveAttribute('stroke-dasharray', '17 83')
  const custom = ring.querySelector('[data-testid="study-ring-ripasso"]')
  expect(custom).toHaveClass('stroke-current', 'text-blue-500')
  expect(custom).toHaveAttribute('stroke-dasharray', '27 73')
  expect(custom).toHaveAttribute('stroke-dashoffset', '-50')
  expect(ring).toHaveAttribute('aria-label', '3 apprese · 3 ripasso · 6 da apprendere · 1 ignorata')
})


it.each([
  ['VALID', 'VALID', 0, true],
  ['VALID', 'MISSING', 0, false],
  ['VALID', 'VALID', 3, false],
  ['MISSING', 'MISSING', 0, false],
  ['MISSING', 'VALID', 0, true],
])('verificato nel sottotitolo per rewrite=%s, review=%s e issue=%s', (rewrite, review, pending, verified) => {
  render(<MemoryRouter><ul><LessonRow lesson={{ ...lesson, phases: { rewrite: rewrite as string, review: review as string, build: 'VALID' }, pending_issues: pending as number }} grouping="materia" running={false} selecting={false} selected={false} onSelect={() => {}} /></ul></MemoryRouter>)
  expect(document.querySelector('a a')).toBeNull()
  expect(screen.getByRole('link', { name: 'Emogasanalisi' })).toHaveAttribute('href', '/lezioni/15')
  expect(screen.getByTestId('lesson-study-ring')).toHaveAttribute('href', '/studio/lezione/15')
  expect(screen.getByTestId('lesson-study-ring')).toHaveAttribute('aria-label', '3 apprese · 6 da apprendere · 1 ignorata')
  expect(screen.getByTestId('lesson-study-ring')).toHaveTextContent('')
  expect(screen.queryByTestId('lesson-review-shield')).not.toBeInTheDocument()
  if (verified) {
    expect(screen.getByTestId('lesson-subtitle')).toHaveTextContent('Verificato')
  } else {
    expect(screen.getByTestId('lesson-subtitle')).not.toHaveTextContent('Verificato')
  }
})

it.each([[3, 4, 3, 10, true], [10, 0, 0, 10, true], [3, 3, 3, 10, false], [0, 0, 0, 0, false]])('spunta con %s apprese, %s in apprendimento, %s ignorate su %s', (learned, learning, ignored, total, complete) => {
  render(<MemoryRouter><StudyRing lesson={{ ...lesson, study_learned: learned as number, study_learning: learning as number, study_ignored: ignored as number, unit_count: total as number }} /></MemoryRouter>)
  expect(!!screen.queryByTestId('lesson-study-complete')).toBe(complete)
})
