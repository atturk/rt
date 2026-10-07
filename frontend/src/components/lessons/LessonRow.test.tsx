import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { StudyRing } from './LessonsView'
import type { Lesson } from '@/lib/format'

export const lesson = { id: 15, titolo: 'Emogasanalisi', materia: '', data: '', docente: '', argomenti: '', ora: '', folder_name: '', path: '', unit_count: 10, study_learned: 3, study_learning: 2, study_ignored: 1, recall_questions: 4, recall_pending: 0, pending_issues: 0, phases: { rewrite: 'VALID', review: 'VALID', build: 'VALID' } } as Lesson
it('l’anello usa i colori dello studio con stacchi fra gli archi', () => {
  render(<StudyRing lesson={lesson} />)
  const ring = screen.getByTestId('lesson-study-ring')
  for (const color of ['track', 'learned', 'learning', 'ignored']) expect(ring.querySelector(`.stroke-study-${color}`)).toBeInTheDocument()
  expect(ring.querySelector('.stroke-study-learned')).toHaveAttribute('stroke-dasharray', '27 73')
})
