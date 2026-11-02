import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { PhaseRows } from './models'
import { testSettings } from './testSettings'

let client: QueryClient

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
})

it('mostra il selettore del contesto per la fase di rielaborazione e ne permette la modifica', async () => {
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: testSettings, response: new Response('{}', { status: 200 }) } as never)

  render(
    <QueryClientProvider client={client}>
      <PhaseRows settings={testSettings} />
    </QueryClientProvider>,
  )

  const rewriteContainer = screen.getByTestId('rewrite-context-mode-container')
  expect(rewriteContainer).toBeInTheDocument()

  const menuButton = screen.getByRole('button', { name: 'Contesto della rielaborazione' })
  expect(menuButton).toBeInTheDocument()
  expect(rewriteContainer).toHaveTextContent('Macro-sezione, in parallelo (predefinito)')

  await userEvent.click(menuButton)
  const option = await screen.findByRole('menuitemradio', { name: /Tutte le unità precedenti/ })
  await userEvent.click(option)

  await waitFor(() => {
    expect(put).toHaveBeenCalledWith('/api/v1/settings/rewrite', {
      body: { context_mode: 'all' },
    })
  })
})
