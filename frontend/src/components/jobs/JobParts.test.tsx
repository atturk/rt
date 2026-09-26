import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { RetryButton } from './JobParts'

function renderButton(onRetried = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RetryButton jobId="vecchio" onRetried={onRetried} />
    </QueryClientProvider>,
  )
  return onRetried
}

afterEach(() => vi.restoreAllMocks())

describe('RetryButton', () => {
  it('crea il nuovo job con POST /jobs/{id}/retry', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { job_id: 'nuovo', type: 'run_pipeline', state: 'queued', lesson_id: 3, worker_available: true, retry_of: 'vecchio' },
      error: undefined,
      response: new Response('{}', { status: 202 }),
    } as never)
    const onRetried = renderButton()
    fireEvent.click(screen.getByRole('button', { name: 'Riprova' }))
    await vi.waitFor(() => expect(onRetried).toHaveBeenCalledWith('nuovo'))
    expect(post).toHaveBeenCalledWith('/api/v1/jobs/{job_id}/retry', { params: { path: { job_id: 'vecchio' } } })
  })
  it('spiega il 409 della lezione occupata', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue({
      data: undefined,
      error: { error: { code: 'lesson_busy', message: 'occupata' } },
      response: new Response('{}', { status: 409 }),
    } as never)
    renderButton()
    fireEvent.click(screen.getByRole('button', { name: 'Riprova' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Un altro job sta lavorando su questa lezione')
  })
})
