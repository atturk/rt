import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { CloseActionSection } from './general'
import { testSettings } from './testSettings'

let client: QueryClient

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
  sessionStorage.clear()
})

it('nascosto nel browser fuori dall’app desktop', () => {
  render(
    <QueryClientProvider client={client}>
      <CloseActionSection settings={testSettings} />
    </QueryClientProvider>,
  )
  expect(screen.queryByRole('region', { name: 'Chiudendo la finestra con la X' })).toBeNull()
})

it('passando a Chiudi del tutto chiede conferma prima di salvare', async () => {
  sessionStorage.setItem('rt-app', '1')
  vi.spyOn(api, 'GET').mockResolvedValue({ data: testSettings, response: new Response('{}', { status: 200 }) } as never)
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: { ...testSettings, preferences: { ...testSettings.preferences!, chiusura_x: 'esci' } },
    response: new Response('{}', { status: 200 }),
  } as never)

  render(
    <QueryClientProvider client={client}>
      <CloseActionSection settings={testSettings} />
    </QueryClientProvider>,
  )

  const bgRadio = screen.getByRole('radio', { name: /Continua a lavorare in background/ })
  const quitRadio = screen.getByRole('radio', { name: /Chiudi del tutto RT/ })
  expect(bgRadio).toBeChecked()
  expect(quitRadio).not.toBeChecked()

  await userEvent.click(quitRadio)
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(put).not.toHaveBeenCalled()

  // Annulla non salva
  await userEvent.click(screen.getByRole('button', { name: 'Annulla' }))
  expect(put).not.toHaveBeenCalled()

  // Conferma salva chiusura_x: 'esci'
  await userEvent.click(quitRadio)
  await userEvent.click(screen.getByRole('button', { name: 'Chiudi del tutto' }))
  expect(put).toHaveBeenCalledWith('/api/v1/settings/preferences', {
    body: expect.objectContaining({ chiusura_x: 'esci' }),
  })
})
