import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render as renderDom, screen, waitFor, fireEvent } from '@testing-library/react'
import type { ReactElement } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { AddSourceDialog } from './AddSourceDialog'
import { archiveApi, fileFacts } from '@/api/archive'

vi.mock('@/api/archive', async (original) => ({
  ...(await original<typeof import('@/api/archive')>()),
  fileFacts: vi.fn(),
  archiveApi: { lookup: vi.fn() },
}))
const render = (ui: ReactElement) => renderDom(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)
beforeEach(() => {
  vi.mocked(archiveApi.lookup).mockResolvedValue({ hash: null })
  vi.mocked(fileFacts).mockResolvedValue({ entry: null, pagine_totali: null, estrai: null })
})
it('recognizes a stored file and continues at the next unused page', async () => {
  const entry = {
    impronta: 'hash',
    pagine_totali: 64,
    da_continuare: '31–64',
    usate: [{ lezione_id: 1, titolo: 'Lezione', materia: 'Test', data: '2026-10-12', pagine: [1, 2, 3] }],
  }
  vi.mocked(fileFacts).mockResolvedValue({ entry, pagine_totali: 64, estrai: 'immagini' })
  const submit = vi.fn()
  render(
    <AddSourceDialog file={new File(['pdf'], 'book.pdf')} hasSources onClose={vi.fn()} onSubmit={submit} />,
  )
  expect(await screen.findByText("Già nell'archivio")).toBeInTheDocument()
  expect(screen.getByLabelText('Da')).toHaveValue(31)
  expect(screen.getByLabelText('A')).toHaveValue(64)
  fireEvent.click(screen.getByText('Aggiungi', { selector: 'button' }))
  await waitFor(() =>
    expect(submit).toHaveBeenCalledWith({ pagine: '31-64', estrai: 'immagini', uso: 'contesto' }),
  )
})
it.each(['notes.txt', 'notes.docx'])('defaults %s to text and Guida for an empty lesson', async (name) => {
  const submit = vi.fn()
  render(
    <AddSourceDialog
      file={new File(['text'], name)}
      hasSources={false}
      onClose={vi.fn()}
      onSubmit={submit}
    />,
  )
  fireEvent.click(screen.getByText('Aggiungi', { selector: 'button' }))
  await waitFor(() =>
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ estrai: 'testo', uso: 'guida' })),
  )
})
it('uses exact existing pages when editing and saves the selected role', async () => {
  const submit = vi.fn()
  render(
    <AddSourceDialog
      source={{ impronta: 'hash', nome: 'book.pdf' }}
      initial={{ pagine: [1, 10] }}
      hasSources
      onClose={vi.fn()}
      onSubmit={submit}
      submitLabel="Fatto"
    />,
  )
  fireEvent.click(screen.getByLabelText('Integra: può aggiungere unità'))
  fireEvent.click(screen.getByText('Fatto'))
  await waitFor(() =>
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ pagine: '1, 10', uso: 'integra' })),
  )
})
it('a portrait PDF defaults to text; Solo immagini turns Uso off and Guida waits for no recording', async () => {
  vi.mocked(fileFacts).mockResolvedValue({ entry: null, pagine_totali: 30, estrai: 'testo' })
  const submit = vi.fn()
  render(<AddSourceDialog file={new File(['pdf'], 'libro.pdf')} hasSources hasAudio onClose={vi.fn()} onSubmit={submit} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Testo' })).toHaveAttribute('aria-pressed', 'true'))
  expect(screen.getByRole('button', { name: 'Guida: fonte principale' })).toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Solo immagini' }))
  expect(screen.getByRole('button', { name: 'Integra: può aggiungere unità' })).toHaveAttribute('aria-disabled', 'true')
  fireEvent.click(screen.getByText('Aggiungi', { selector: 'button' }))
  await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({ estrai: 'solo_immagini', uso: 'contesto' })))
})
it('Word, TXT and Markdown are text only', () => {
  render(<AddSourceDialog file={new File(['t'], 'note.md')} hasSources onClose={vi.fn()} onSubmit={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Testo e immagini' })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('button', { name: 'Solo immagini' })).toHaveAttribute('aria-disabled', 'true')
})
