import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearFileStatus,
  setFileStatus,
  trackFileExport,
} from '@/lib/fileStatus'
import { FileStatusBar } from './file-status'
import * as fileExport from '@/lib/fileExport'

describe('FileStatusBar & trackFileExport', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    clearFileStatus()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    clearFileStatus()
  })

  it('busy: mostra lo spinner, messaggio e pulsante Annulla', () => {
    const onCancel = vi.fn()
    render(<FileStatusBar />)
    act(() => {
      setFileStatus({ kind: 'busy', message: 'Preparo il PDF…', onCancel })
    })

    const bar = screen.getByRole('status')
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveTextContent('Preparo il PDF…')

    const cancelBtn = screen.getByRole('button', { name: 'Annulla' })
    expect(cancelBtn).toBeInTheDocument()
    act(() => {
      fireEvent.click(cancelBtn)
    })
    expect(onCancel).toHaveBeenCalled()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('nessun salvataggio automatico: anche con file veloce mostra Salva, Condividi e Annulla', async () => {
    const saveSpy = vi.spyOn(fileExport, 'saveFile').mockImplementation(() => {})
    vi.spyOn(fileExport, 'canShareFiles').mockReturnValue(true)
    render(<FileStatusBar />)

    const file = new File(['pdf-data'], 'lezione.pdf', { type: 'application/pdf' })
    const promise = Promise.resolve(file)

    await act(async () => {
      await trackFileExport(promise, {
        busyMessage: 'Preparo il PDF…',
        doneLabel: 'PDF pronto',
      })
    })

    // Non salva in automatico!
    expect(saveSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('PDF pronto: lezione.pdf')
    expect(screen.getByRole('button', { name: 'Salva' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Condividi' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Annulla' })).toBeInTheDocument()

    // Clic su Salva
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'Salva' }))
    })
    expect(saveSpy).toHaveBeenCalledWith(file)

    // Dopo done si chiude dopo 4s
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('file multipli: mostra etichetta, elenco espandibile, Salva e Condividi', () => {
    const onSave = vi.fn()
    const onShare = vi.fn()
    const onCancel = vi.fn()
    render(<FileStatusBar />)

    act(() => {
      setFileStatus({
        kind: 'ready',
        label: '3 PDF pronti',
        files: [{ name: 'Lezione 1.pdf' }, { name: 'Lezione 2.pdf' }, { name: 'Lezione 3.pdf' }],
        skippedMessage: '(1 senza documento finale saltata)',
        canShare: true,
        onSave,
        onShare,
        onCancel,
      })
    })

    const bar = screen.getByRole('status')
    expect(bar).toHaveTextContent('3 PDF pronti (1 senza documento finale saltata)')

    const listBtn = screen.getByRole('button', { name: 'Elenco' })
    expect(screen.queryByTestId('file-status-list')).not.toBeInTheDocument()

    // Mostra l'elenco dei nomi
    act(() => {
      fireEvent.click(listBtn)
    })
    expect(screen.getByTestId('file-status-list')).toBeInTheDocument()
    expect(screen.getByText('Lezione 1.pdf')).toBeInTheDocument()
    expect(screen.getByText('Lezione 2.pdf')).toBeInTheDocument()

    // Salva
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'Salva' }))
    })
    expect(onSave).toHaveBeenCalled()
  })

  it('Esc chiude il popup e chiama onCancel', () => {
    const onCancel = vi.fn()
    render(<FileStatusBar />)

    act(() => {
      setFileStatus({
        kind: 'ready',
        label: 'PDF pronto',
        filename: 'lezione.pdf',
        canShare: false,
        onSave: vi.fn(),
        onCancel,
      })
    })

    expect(screen.getByRole('status')).toBeInTheDocument()
    act(() => {
      fireEvent.keyDown(window, { key: 'Escape' })
    })
    expect(onCancel).toHaveBeenCalled()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('errore: mostra il messaggio in rosso e resta finché non si tocca la ×', async () => {
    render(<FileStatusBar />)

    const promise = Promise.reject(new Error('Errore generazione PDF'))
    await act(async () => {
      await trackFileExport(promise, {
        busyMessage: 'Preparo il PDF…',
        doneLabel: 'PDF pronto',
      })
    })

    const bar = screen.getByRole('status')
    expect(bar).toHaveTextContent('Errore generazione PDF')

    // Non si chiude da solo dopo 4s
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(screen.getByRole('status')).toBeInTheDocument()

    // Clic sulla × per chiudere
    const closeBtn = screen.getByRole('button', { name: 'Chiudi' })
    act(() => {
      fireEvent.click(closeBtn)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
