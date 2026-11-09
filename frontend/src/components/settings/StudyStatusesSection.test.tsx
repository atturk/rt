import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

it('trascinamento di una riga (dragStart/dragOver/drop) salva il nuovo ordine', async () => {
  const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: testSettings,
    response: new Response('{}', { status: 200 }),
  } as never)

  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={testSettings} />
    </QueryClientProvider>,
  )

  const rows = screen.getByTestId('study-statuses-list').children
  const data = new Map<string, string>()
  const dataTransfer = {
    setData: (k: string, v: string) => data.set(k, v),
    getData: (k: string) => data.get(k) ?? '',
    get types() { return [...data.keys()] },
    effectAllowed: '',
    dropEffect: '',
  }

  // Trascina la prima riga (da-imparare) sopra la terza (appreso)
  fireEvent.dragStart(rows[0], { dataTransfer })
  fireEvent.dragOver(rows[2], { dataTransfer })
  fireEvent.drop(rows[2], { dataTransfer })

  await waitFor(() => {
    expect(putSpy).toHaveBeenCalledWith(
      '/api/v1/settings/study-statuses',
      expect.objectContaining({
        body: expect.objectContaining({
          ordine_stati_studio: ['in-apprendimento', 'appreso', 'da-imparare', 'ignorata'],
        }),
      }),
    )
  })
})

it('Alt+↓ sulla maniglia sposta di una posizione', async () => {
  const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: testSettings,
    response: new Response('{}', { status: 200 }),
  } as never)

  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={testSettings} />
    </QueryClientProvider>,
  )

  const handle = screen.getByLabelText(/Riordina stato Da imparare/)
  // Senza Alt non sposta
  fireEvent.keyDown(handle, { key: 'ArrowDown' })
  expect(putSpy).not.toHaveBeenCalled()

  // Con Alt+ArrowDown sposta di una posizione
  fireEvent.keyDown(handle, { key: 'ArrowDown', altKey: true })
  await waitFor(() => {
    expect(putSpy).toHaveBeenCalledWith(
      '/api/v1/settings/study-statuses',
      expect.objectContaining({
        body: expect.objectContaining({
          ordine_stati_studio: ['in-apprendimento', 'da-imparare', 'appreso', 'ignorata'],
        }),
      }),
    )
  })
})

it('il nome dello stato si salva con Invio, non a ogni tasto', async () => {
  const settingsWithCustom = {
    ...testSettings,
    stati_studio: [{ id: 'c1', nome: 'Da ripassare', colore: 'text-amber-500', icona: 'Star' }],
    ordine_stati_studio: ['da-imparare', 'in-apprendimento', 'appreso', 'ignorata', 'c1'],
  }
  const putSpy = vi.spyOn(api, 'PUT').mockResolvedValue({
    data: settingsWithCustom, response: new Response('{}', { status: 200 }),
  } as never)
  render(
    <QueryClientProvider client={client}>
      <StudyStatusesSection settings={settingsWithCustom} />
    </QueryClientProvider>,
  )
  const input = screen.getByLabelText('Nome per stato Da ripassare')
  await userEvent.clear(input)
  await userEvent.type(input, 'Carte Anki')
  expect(putSpy).not.toHaveBeenCalled()
  await userEvent.keyboard('{Enter}')
  expect(putSpy).toHaveBeenCalledTimes(1)
  expect(putSpy).toHaveBeenCalledWith('/api/v1/settings/study-statuses', expect.objectContaining({
    body: expect.objectContaining({ stati_studio: [expect.objectContaining({ nome: 'Carte Anki' })] }),
  }))
})
