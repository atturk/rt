import { keysForEvent } from './liveUpdates'
import { lessonKeys, reviewKeys } from './hooks'

it('ogni unità finita ricarica subito issue e unità della sola lezione', () => {
  const keys = keysForEvent({ id: 1, job_id: 'verifica', job_type: 'run_phase', lesson_id: 7, type: 'review_unit_done' })
  expect(keys).toContainEqual(reviewKeys.issues(7))
  expect(keys).toContainEqual(reviewKeys.units(7))
  expect(keys).toContainEqual(lessonKeys.jobs(7))
  expect(keys).not.toContainEqual(['lesson', 7])
  expect(keys).not.toContainEqual(['lessons'])
  expect(keys).not.toContainEqual(['costs'])
  expect(keys).not.toContainEqual(reviewKeys.issues(8))
})
