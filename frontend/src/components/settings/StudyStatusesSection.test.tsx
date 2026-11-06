import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { StudyStatusesSection } from './StudyStatusesSection'
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

it('mostra i quattro stati di default e non consente di eliminarli', () => {
  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={testSettings} />
    </QueryClientProvider>,
  )

  expect(screen.getByText('Da imparare')).toBeInTheDocument()
  expect(screen.getByText('In apprendimento')).toBeInTheDocument()
  expect(screen.getByText('Appresa')).toBeInTheDocument()
  expect(screen.getByText('Ignorata')).toBeInTheDocument()

  // I default non hanno bottone di eliminazione
  expect(screen.queryByLabelText(/Elimina stato Da imparare/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/Elimina stato In apprendimento/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/Elimina stato Appresa/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/Elimina stato Ignorata/i)).not.toBeInTheDocument()
})

it('permette di aggiungere uno stato personalizzato e di eliminarlo', async () => {
  const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: {
      ...testSettings,
      stati_studio: [{ id: 'c1', nome: 'Nuovo stato', colore: 'text-amber-500', icona: 'Star' }],
      ordine_stati_studio: ['da-imparare', 'in-apprendimento', 'appreso', 'ignorata', 'c1'],
    },
    response: new Response('{}', { status: 200 }),
  } as never)

  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={testSettings} />
    </QueryClientProvider>,
  )

  const addBtn = screen.getByRole('button', { name: /Aggiungi stato/i })
  await userEvent.click(addBtn)

  expect(putSpy).toHaveBeenCalledWith(
    '/api/v1/settings/study-statuses',
    expect.objectContaining({
      body: expect.objectContaining({
        stati_studio: [
          expect.objectContaining({
            id: 'c1',
            nome: 'Nuovo stato',
          }),
        ],
      }),
    }),
  )
})

it('elimina uno stato personalizzato con richiesta di conferma se in uso', async () => {
  const settingsWithCustom = {
    ...testSettings,
    stati_studio: [{ id: 'c1', nome: 'Da ripassare', colore: 'text-amber-500', icona: 'Star' }],
    ordine_stati_studio: ['da-imparare', 'c1', 'in-apprendimento', 'appreso', 'ignorata'],
  }

  // Simula 3 unità in uso
  vi.spyOn(api, 'GET').mockResolvedValue({
    data: { count: 3 },
    response: new Response('{}', { status: 200 }),
  } as never)

  const deleteEndpoint = vi.spyOn(api, 'DELETE').mockResolvedValue({
    data: { reassigned: 3 },
    response: new Response('{}', { status: 200 }),
  } as never)

  const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: testSettings,
    response: new Response('{}', { status: 200 }),
  } as never)

  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={settingsWithCustom as never} />
    </QueryClientProvider>,
  )

  const deleteBtn = screen.getByLabelText(/Elimina stato Da ripassare/i)
  await userEvent.click(deleteBtn)

  // Modale di conferma compare
  expect(screen.getByTestId('confirm-delete-status-modal')).toBeInTheDocument()
  expect(screen.getByText(/3/)).toBeInTheDocument()

  // Conferma eliminazione
  const confirmBtn = screen.getByRole('button', { name: /Elimina e converti/i })
  await userEvent.click(confirmBtn)

  expect(deleteEndpoint).toHaveBeenCalledWith(
    '/api/v1/study/statuses/{status_id}',
    expect.objectContaining({
      params: { path: { status_id: 'c1' } },
    }),
  )
  expect(putSpy).toHaveBeenCalled()
})

it('permette di riordinare gli stati', async () => {
  const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: testSettings,
    response: new Response('{}', { status: 200 }),
  } as never)

  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={testSettings} />
    </QueryClientProvider>,
  )

  // Riga "da-imparare": prova a spostare giù
  const firstRow = screen.getByTestId('status-row-da-imparare')
  const downBtn = firstRow.querySelector('button[aria-label="Sposta giù"]')
  expect(downBtn).toBeInTheDocument()
  await userEvent.click(downBtn!)

  expect(putSpy).toHaveBeenCalledWith(
    '/api/v1/settings/study-statuses',
    expect.objectContaining({
      body: expect.objectContaining({
        ordine_stati_studio: ['in-apprendimento', 'da-imparare', 'appreso', 'ignorata'],
      }),
    }),
  )
})
