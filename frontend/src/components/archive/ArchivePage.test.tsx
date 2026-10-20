import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import { archiveFilesApi, compressPages, type ArchiveDetail } from '@/api/archive'
import { ArchivePage } from './ArchivePage'

vi.mock('@/api/hooks', () => ({
  useLessons: () => ({ data: [{ id: 7, titolo: 'La lezione', materia: 'Anatomia', data: '2026-10-12' }] }),
}))
vi.mock('@/api/archive', async (original) => ({
  ...(await original<typeof import('@/api/archive')>()),
  archiveFilesApi: {
    list: vi.fn(),
    detail: vi.fn(),
    ignore: vi.fn(),
    addToLesson: vi.fn(),
    addToMedia: vi.fn(),
    crop: vi.fn(),
    delete: vi.fn(),
    deletePages: vi.fn(),
  },
}))
const detail: ArchiveDetail = {
  impronta: 'a'.repeat(64),
  nome: 'Libro.pdf',
  tipo: 'slide',
  pagine_totali: 4,
  durata_s: null,
  dimensione: 1000,
  materie: ['Anatomia'],
  usi: 1,
  da_continuare: '3–4',
  trascrizione_inizio: '',
  pagine: [1, 2, 3, 4].map((numero) => ({ numero, ignorata: false, lezione_id: numero < 3 ? 7 : null })),
  lezioni: [{ id: 7, titolo: 'La lezione', data: '2026-10-12', pagine: [1, 2] }],
}
function Location() {
  const location = useLocation()
  return (
    <span data-testid="location">
      {location.pathname}
      {location.search}
    </span>
  )
}
function setup(params = '?da=7') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/archivio${params}`]}>
        <ArchivePage />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return screen.findByRole('button', { name: 'Aggiungi alla lezione come fonte' }, { timeout: 5000 })
}
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(archiveFilesApi.list).mockResolvedValue([detail])
  vi.mocked(archiveFilesApi.detail).mockResolvedValue(detail)
})
it('selects pages with click, Shift, Cmd/Ctrl and clears with Escape', async () => {
  await setup()
  const one = await screen.findByRole('button', { name: 'Pagina 1' })
  const three = screen.getByRole('button', { name: 'Pagina 3' })
  fireEvent.click(one)
  expect(one).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(three, { shiftKey: true })
  expect(screen.getByRole('button', { name: 'Pagina 2' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(one, { metaKey: true })
  expect(one).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(screen.getByRole('button', { name: 'Pagina 4' }), { ctrlKey: true })
  expect(screen.getByText('3 pagine')).toBeInTheDocument()
  fireEvent.keyDown(document.body, { key: 'Escape' })
  expect(screen.queryByRole('toolbar')).not.toBeInTheDocument()
  fireEvent.click(three)
  fireEvent.click(three)
  expect(three).toHaveAttribute('aria-pressed', 'false')
})
it('keeps exact selected pages in the add panel and closes on Cancel', async () => {
  await setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Pagina 1' }))
  fireEvent.click(screen.getByRole('button', { name: 'Pagina 4' }), { ctrlKey: true })
  fireEvent.click(screen.getByLabelText('Aggiungi alla lezione come fonte'))
  expect(screen.getByText('Pagine: 1, 4')).toBeInTheDocument()
  expect(screen.queryByLabelText('Da')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Aggiungi' }))
  await waitFor(() =>
    expect(archiveFilesApi.addToLesson).toHaveBeenCalledWith(
      detail.impronta,
      7,
      [1, 4],
      'contesto',
      'immagini',
    ),
  )
  fireEvent.click(screen.getByLabelText('Aggiungi alla lezione come fonte'))
  fireEvent.click(screen.getByText('Annulla', { selector: 'button' }))
  expect(screen.queryByLabelText('Lezione')).not.toBeInTheDocument()
})
it('uses continuation fields with no selection and navigates back to enrichment', async () => {
  await setup()
  fireEvent.click(screen.getByLabelText('Aggiungi alla lezione come fonte'))
  expect(screen.getByLabelText('Da')).toHaveValue(3)
  expect(screen.getByLabelText('A')).toHaveValue(4)
  fireEvent.click(screen.getByLabelText('Indietro'))
  expect(screen.getByTestId('location')).toHaveTextContent('/lezioni/7?panel=arricchimento')
})
it('opens the requested page, handles arrows outside fields and resizes by keyboard', async () => {
  await setup(`?file=${detail.impronta}&pagina=3`)
  expect(await screen.findByText('3 / 4')).toBeInTheDocument()
  fireEvent.keyDown(document.body, { key: 'ArrowRight' })
  expect(screen.getByText('4 / 4')).toBeInTheDocument()
  fireEvent.keyDown(screen.getByLabelText("Cerca nell'archivio"), { key: 'ArrowLeft' })
  expect(screen.getByText('4 / 4')).toBeInTheDocument()
  fireEvent.keyDown(document.body, { key: 'ArrowLeft' })
  expect(screen.getByText('3 / 4')).toBeInTheDocument()
  const separator = screen.getByRole('separator')
  fireEvent.keyDown(separator, { key: 'ArrowLeft' })
  expect(separator).toHaveAttribute('aria-valuenow', '580')
  fireEvent.keyDown(separator, { key: 'ArrowRight', shiftKey: true })
  expect(separator).toHaveAttribute('aria-valuenow', '500')
  expect(localStorage.getItem('rt.archive.detailWidth')).toBe('500')
})
it('compresses inclusive page runs', () => {
  expect(compressPages([10, 1, 3, 2, 10, 12])).toBe('1–3, 10, 12')
})
