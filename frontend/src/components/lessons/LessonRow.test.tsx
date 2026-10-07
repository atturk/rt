import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { MemoryRouter } from 'react-router'
import { LessonRow, StudyRing } from './LessonsView'
import type { Lesson } from '@/lib/format'

export const lesson = { id: 15, titolo: 'Emogasanalisi', materia: '', data: '', docente: '', argomenti: '', ora: '', folder_name: '', path: '', unit_count: 10, study_learned: 3, study_learning: 2, study_ignored: 1, recall_questions: 4, recall_pending: 0, pending_issues: 0, phases: { rewrite: 'VALID', review: 'VALID', build: 'VALID' } } as Lesson
it('l’anello usa i colori dello studio con stacchi fra gli archi', () => {
  render(<MemoryRouter><StudyRing lesson={lesson} /></MemoryRouter>)
  const ring = screen.getByTestId('lesson-study-ring')
  for (const color of ['track', 'learned', 'learning', 'ignored']) expect(ring.querySelector(`.stroke-study-${color}`)).toBeInTheDocument()
  expect(ring.querySelector('.stroke-study-learned')).toHaveAttribute('stroke-dasharray', '27 73')
})


it.each([
  ['VALID', 'VALID', 0, 'text-study-learned'],
  ['VALID', 'MISSING', 0, 'text-study-learning'],
  ['VALID', 'VALID', 3, 'text-study-learning'],
  ['MISSING', 'MISSING', 0, null],
])('scudo per rewrite=%s, review=%s e issue=%s', (rewrite, review, pending, color) => {
  render(<MemoryRouter><ul><LessonRow lesson={{ ...lesson, phases: { rewrite: rewrite as string, review: review as string }, pending_issues: pending as number }} grouping="materia" running={false} selecting={false} selected={false} onSelect={() => {}} /></ul></MemoryRouter>)
  expect(document.querySelector('a a')).toBeNull()
  expect(screen.getByRole('link', { name: 'Emogasanalisi' })).toHaveAttribute('href', '/lezioni/15')
  expect(screen.getByTestId('lesson-study-ring')).toHaveAttribute('href', '/studio/lezione/15')
  expect(screen.getByTestId('lesson-study-ring')).toHaveAttribute('aria-label', '3 apprese · 6 da apprendere · 1 ignorata')
  expect(screen.getByTestId('lesson-study-ring')).toHaveTextContent('')
  if (color) {
    expect(screen.getByTestId('lesson-review-shield')).toHaveAttribute('href', '/lezioni/15?panel=verifica')
    expect(screen.getByTestId('lesson-review-shield').querySelector('svg')).toHaveClass(color as string)
  } else expect(screen.queryByTestId('lesson-review-shield')).not.toBeInTheDocument()
})
