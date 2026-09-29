import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { TopicArchiveExport } from './TopicArchiveExport'

const ok = (data: unknown, status = 200) => ({ data, error: undefined, response: new Response('{}', { status }) }) as never

function renderExport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TopicArchiveExport topic={{ id: 42, name: 'Biochimica' }} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('TopicArchiveExport', () => {
  it('accoda l\'esportazione e a job concluso offre il download', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({
      job_id: 'exp-1', type: 'telegram_topic_export', state: 'queued', lesson_id: null, worker_available: true, retry_of: null,
    }, 202))
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/workers') return Promise.resolve(ok([{ worker_id: 'w' }]))
      return Promise.resolve(ok({
        id: 'exp-1', type: 'telegram_topic_export', state: 'succeeded', progress: null, error: null,
        result: { topic_id: 42, file: 'telegram-topic-42.zip', size: 2048, messages: 12, media_bytes: 1024 },
      }))
    }) as never)
    renderExport()
    fireEvent.click(screen.getByRole('button', { name: 'Esporta con cronologia e media' }))
    const link = await screen.findByRole('link', { name: /Scarica «Biochimica»/ })
    expect(link).toHaveAttribute('href', '/api/v1/settings/telegram/user/archives/exp-1')
    expect(link).toHaveAttribute('download', 'telegram-topic-42.zip')
    expect(link).toHaveTextContent('12 messaggi')
    expect(post).toHaveBeenCalledWith('/api/v1/settings/telegram/user/topics/{topic_id}/archive', { params: { path: { topic_id: 42 } } })
  })

  it('mostra l\'errore del job senza link di download', async () => {
    vi.spyOn(api, 'POST').mockResolvedValue(ok({
      job_id: 'exp-2', type: 'telegram_topic_export', state: 'queued', lesson_id: null, worker_available: true, retry_of: null,
    }, 202))
    vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
      if (path === '/api/v1/workers') return Promise.resolve(ok([{ worker_id: 'w' }]))
      return Promise.resolve(ok({ id: 'exp-2', type: 'telegram_topic_export', state: 'failed', progress: null, error: 'Media del messaggio 43 non scaricato.', result: null }))
    }) as never)
    renderExport()
    fireEvent.click(screen.getByRole('button', { name: 'Esporta con cronologia e media' }))
    expect(await screen.findByText(/Media del messaggio 43 non scaricato/)).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByRole('button', { name: 'Esporta di nuovo' })).toBeEnabled()
  })
})
