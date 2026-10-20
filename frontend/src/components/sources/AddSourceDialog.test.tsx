import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { AddSourceDialog } from './AddSourceDialog'
import { archiveApi } from '@/api/archive'

vi.mock('@/api/archive', async (original) => ({
  ...(await original<typeof import('@/api/archive')>()),
  fileSha: vi.fn().mockResolvedValue('hash'),
  archiveApi: { lookup: vi.fn() },
}))
beforeEach(() => {
  vi.mocked(archiveApi.lookup).mockResolvedValue({ hash: null })
})
it('recognizes a stored file and continues at the next unused page', async () => {
  vi.mocked(archiveApi.lookup).mockResolvedValue({
    hash: {
      impronta: 'hash',
      pagine_totali: 64,
      da_continuare: '31–64',
      usate: [{ lezione_id: 1, titolo: 'Lezione', materia: 'Test', data: '2026-10-12', pagine: [1, 2, 3] }],
    },
  })
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
