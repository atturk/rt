import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { DescribeHintDialog } from './DescribeHintDialog'
import { ImageInfoContent, ImageInfoModal } from './ImageInfoModal'

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) }) as never
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('mostra solo le parti presenti: ruolo, testo e descrizione', () => {
  render(<ImageInfoContent info={{ testo: 'Curva pressione-volume', descrizione: { visual_elements: 'grafico' }, ruolo: 'introduttiva' }} />)
  expect(screen.getByText('Introduttiva')).toBeInTheDocument()
  expect(screen.getByText('Curva pressione-volume')).toBeInTheDocument()
  expect(screen.getByText('grafico')).toBeInTheDocument()
  expect(screen.queryByText('Titolo')).toBeNull()
  cleanup()
  render(<ImageInfoContent info={{ testo: '', descrizione: {}, ruolo: 'contenuto' }} />)
  expect(screen.getByText('Nessuna informazione')).toBeInTheDocument()
})

it('chiede le informazioni della pagina d’archivio', async () => {
  const get = vi.spyOn(api, 'GET').mockResolvedValue(ok({ testo: 'Pagina 3', descrizione: {}, ruolo: null }))
  render(<QueryClientProvider client={new QueryClient()}><ImageInfoModal target={{ sha: 'abc', page: 3 }} onClose={vi.fn()} /></QueryClientProvider>)
  expect(await screen.findByText('Pagina 3')).toBeInTheDocument()
  expect(get).toHaveBeenCalledWith('/api/v1/archive/{sha}/pages/{n}/info', { params: { path: { sha: 'abc', n: 3 } } })
})

it('l’avviso su Descrivi ricorda la scelta Non mostrare più', () => {
  const confirm = vi.fn()
  render(<DescribeHintDialog open onConfirm={confirm} onCancel={vi.fn()} />)
  fireEvent.click(screen.getByLabelText('Non mostrare più'))
  fireEvent.click(screen.getByRole('button', { name: 'OK' }))
  expect(confirm).toHaveBeenCalledWith(true)
})
