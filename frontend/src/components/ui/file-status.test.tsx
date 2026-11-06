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

  it('busy: mostra lo spinner e il messaggio durante la preparazione', () => {
    render(<FileStatusBar />)
    act(() => {
      setFileStatus({ kind: 'busy', message: 'Preparo il PDF…' })
    })

    const bar = screen.getByRole('status')
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveTextContent('Preparo il PDF…')
  })

  it('preparazione veloce (< 1.5s, non-iOS): salva da solo e si chiude dopo 4s', async () => {
    const saveSpy = vi.spyOn(fileExport, 'saveFile').mockImplementation(() => {})
    render(<FileStatusBar />)

    const file = new File(['pdf-data'], 'lezione.pdf', { type: 'application/pdf' })
    const promise = Promise.resolve(file)

    await act(async () => {
      await trackFileExport(promise, {
        busyMessage: 'Preparo il PDF…',
        doneLabel: 'PDF pronto',
      })
    })

    expect(saveSpy).toHaveBeenCalledWith(file)
    expect(screen.getByRole('status')).toHaveTextContent('PDF pronto: lezione.pdf')

    // Dopo 4s si chiude
    act(() => {
      vi.advanceTimersByTime(3999)
    })
    expect(screen.getByRole('status')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(2)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('preparazione lenta (> 1.5s): non salva da solo, mostra il pulsante Salva', async () => {
    const saveSpy = vi.spyOn(fileExport, 'saveFile').mockImplementation(() => {})
    render(<FileStatusBar />)

    const file = new File(['pdf-data'], 'lungo.pdf', { type: 'application/pdf' })
    let resolvePromise!: (f: File) => void
    const promise = new Promise<File>((resolve) => {
      resolvePromise = resolve
    })

    let trackingPromise: Promise<File | null>
    act(() => {
      trackingPromise = trackFileExport(promise, {
        busyMessage: 'Preparo il PDF…',
        doneLabel: 'PDF pronto',
      })
    })

    expect(screen.getByRole('status')).toHaveTextContent('Preparo il PDF…')

    // Avanza di 2 secondi prima che il file sia pronto
    await act(async () => {
      vi.advanceTimersByTime(2000)
      resolvePromise(file)
      await trackingPromise
    })

    expect(saveSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('PDF pronto: lungo.pdf')
    const salvaBtn = screen.getByRole('button', { name: 'Salva' })
    expect(salvaBtn).toBeInTheDocument()

    // Clic su Salva
    act(() => {
      fireEvent.click(salvaBtn)
    })
    expect(saveSpy).toHaveBeenCalledWith(file)
    expect(screen.getByRole('status')).toHaveTextContent('PDF pronto: lungo.pdf')

    // Si chiude dopo 4s
    act(() => {
      vi.advanceTimersByTime(4000)
    })
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
