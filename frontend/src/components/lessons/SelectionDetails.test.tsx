import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { api } from '@/api/client'
import type { Lesson } from '@/lib/format'
import { SelectionDetails } from './SelectionDetails'

const lessons = [1, 2, 3].map(id => ({ id, folder_name: String(id), path: '', titolo: `Lezione ${id}`, materia: '', data: '', docente: '', argomenti: '', ora: '', pending_issues: 0, recall_questions: 0, recall_pending: 0, study_learned: 0, study_learning: 0, study_ignored: 0, phases: {} }) as Lesson)
const ok = (data: unknown) => ({ data, response: new Response('{}', { status: 202 }) }) as never
function setup(busy: number[] = []) {
  vi.spyOn(api, 'GET').mockResolvedValue(ok(busy.map(lesson_id => ({ lesson_id, type: 'run_pipeline', state: 'running' }))))
  const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ queued: [{ lesson_id: 1, job_id: 'a' }, { lesson_id: 2, job_id: 'b' }], skipped: [{ lesson_id: 3, motivo: 'Lezione in lavorazione' }] }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <SelectionDetails lessons={lessons} open onClose={vi.fn()} />
  </QueryClientProvider>)
  return post
}
afterEach(() => vi.restoreAllMocks())
it('quattro icone, avvio senza conferma, revisione e riepilogo senza chiudere', async () => {
  const post = setup()
  for (const name of ['Includi la revisione scientifica', 'Esegui la pipeline', 'Riesegui tutte le fasi', 'Riesegui tutto da capo']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Includi la revisione scientifica' }))
  fireEvent.click(screen.getByRole('button', { name: 'Esegui la pipeline' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/lessons/batch/pipeline', { body: { lesson_ids: [1, 2, 3], mode: 'run', with_review: true } }))
  expect(await screen.findByRole('status')).toHaveTextContent('2 avviate · 1 saltata')
  expect(screen.getByTestId('selection-details')).toBeInTheDocument()
})
it.each([['Riesegui tutte le fasi', 'Rifare tutte le fasi di 3 lezioni?', 'force'], ['Riesegui tutto da capo', 'Rieseguire da capo 3 lezioni?', 'reingest']])('conferma %s con il numero di lezioni', async (label, title, mode) => {
  const post = setup()
  fireEvent.click(screen.getByRole('button', { name: label }))
  expect(screen.getByRole('dialog', { name: title })).toHaveTextContent("con il loro costo")
  expect(post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Riesegui' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/lessons/batch/pipeline', { body: { lesson_ids: [1, 2, 3], mode, with_review: false } }))
})
it('disattiva le azioni solo quando tutte le lezioni sono occupate', async () => {
  setup([1, 2, 3])
  await waitFor(() => expect(screen.getByRole('button', { name: 'Esegui la pipeline' })).toHaveAttribute('aria-disabled', 'true'))
})
it('lascia avviare le lezioni libere in una selezione mista', async () => {
  const post = setup([1, 2])
  fireEvent.click(screen.getByRole('button', { name: 'Esegui la pipeline' }))
  await waitFor(() => expect(post).toHaveBeenCalledOnce())
})
