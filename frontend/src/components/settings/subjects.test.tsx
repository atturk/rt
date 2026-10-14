import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { SubjectsSettingsSection } from './subjects'

function renderComponent() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SubjectsSettingsSection />
    </QueryClientProvider>,
  )
}

describe('SubjectsSettingsSection (Wireframe RT-fonti-materie scena 3)', () => {
  const mockSubs = [
    { nome: 'Data mining', lezioni: 6 },
    { nome: 'Elettromagnetismo', lezioni: 1 },
    { nome: 'Farmacologia', lezioni: 0 },
  ]

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'GET').mockImplementation((path: string) => {
      if (path === '/api/v1/subjects') {
        return Promise.resolve({
          data: mockSubs,
          error: undefined,
          response: new Response(JSON.stringify(mockSubs), { status: 200 }),
        } as never)
      }
      return Promise.resolve({ data: {}, response: new Response('{}') } as never)
    })
  })

  it('mostra le materie con il conteggio delle lezioni', async () => {
    renderComponent()
    expect(await screen.findByText('Data mining')).toBeInTheDocument()
    expect(screen.getByText('6 lezioni')).toBeInTheDocument()
    expect(screen.getByText('Elettromagnetismo')).toBeInTheDocument()
    expect(screen.getByText('1 lezione')).toBeInTheDocument()
    expect(screen.getByText('Farmacologia')).toBeInTheDocument()
    expect(screen.getByText('nessuna lezione')).toBeInTheDocument()
  })

  it('mostra il pulsante Togli solo sulle materie senza lezioni', async () => {
    renderComponent()
    expect(await screen.findByText('Farmacologia')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Togli Farmacologia' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Togli Data mining' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Togli Elettromagnetismo' })).toBeNull()
  })

  it('aggiunge una materia chiamando POST /api/v1/subjects', async () => {
    const postSpy = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { nome: 'Chirurgia', lezioni: 0 },
      error: undefined,
      response: new Response('{}', { status: 201 }),
    } as never)

    renderComponent()
    const input = await screen.findByRole('textbox', { name: 'Nuova materia' })
    await userEvent.type(input, 'Chirurgia')
    const addBtn = screen.getByRole('button', { name: 'Aggiungi' })
    await userEvent.click(addBtn)

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/api/v1/subjects', { body: { nome: 'Chirurgia' } })
    })
  })

  it('rimuove una materia chiamando DELETE /api/v1/subjects/{nome}', async () => {
    const deleteSpy = vi.spyOn(api, 'DELETE').mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never)

    renderComponent()
    const deleteBtn = await screen.findByRole('button', { name: 'Togli Farmacologia' })
    await userEvent.click(deleteBtn)

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith('/api/v1/subjects/Farmacologia')
    })
  })
})
