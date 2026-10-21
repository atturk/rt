import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BackupDialog } from './BackupDialog'

describe('BackupDialog', () => {
  beforeEach(() => {
    if (!HTMLDialogElement.prototype.showModal) {
      HTMLDialogElement.prototype.showModal = function () {
        this.setAttribute('open', '')
      }
    }
    if (!HTMLDialogElement.prototype.close) {
      HTMLDialogElement.prototype.close = function () {
        this.removeAttribute('open')
      }
    }
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    delete window.__rtBackup
    delete window.pywebview
  })

  it('gli eventi simulati su window.__rtBackup muovono la barra', () => {
    render(<BackupDialog />)

    act(() => {
      window.__rtBackup?.({ inizio: true, tipo: 'backup' })
    })

    expect(screen.getByText('Backup in corso…')).toBeInTheDocument()
    expect(screen.getByText('0%')).toBeInTheDocument()

    act(() => {
      window.__rtBackup?.({ fase: 'database', fatto: 1, totale: 1 })
    })
    expect(screen.getByText('5%')).toBeInTheDocument()
    expect(screen.getByText('Database')).toBeInTheDocument()

    act(() => {
      window.__rtBackup?.({ fase: 'media', fatto: 50, totale: 100 })
    })
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(screen.getByText('Media 50 di 100')).toBeInTheDocument()

    act(() => {
      window.__rtBackup?.({ fase: 'config', fatto: 1, totale: 1 })
    })
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(screen.getByText('Configurazione')).toBeInTheDocument()
  })

  it('la fine mostra il riepilogo e i due pulsanti', () => {
    render(<BackupDialog />)

    act(() => {
      window.__rtBackup?.({
        fine: true,
        percorso: '/Users/test/backups/rt-backup-20261019-120000',
        riepilogo: ['Database salvato.', 'Media salvati.', 'Backup completo: /Users/test/backups/rt-backup-20261019-120000'],
        avviso_chiave: 'Chiave master non presente nel backup.',
      })
    })

    expect(screen.getByText('Backup completo')).toBeInTheDocument()
    expect(screen.getByText('Database salvato.')).toBeInTheDocument()
    expect(screen.getByText('Media salvati.')).toBeInTheDocument()
    expect(screen.getByText('Chiave master non presente nel backup.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Chiudi' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Salva una copia…' })).toBeInTheDocument()
  })

  it('«Salva una copia…» chiama l’API finta e passa a «Salvo una copia…»', async () => {
    const salvaMock = vi.fn().mockResolvedValue({ avviato: true })
    window.pywebview = { api: { salva_copia_backup: salvaMock } }

    render(<BackupDialog />)

    act(() => {
      window.__rtBackup?.({
        fine: true,
        percorso: '/Users/test/backups/rt-backup-20261019-120000',
        riepilogo: ['Backup completo.'],
      })
    })

    const copiaBtn = screen.getByRole('button', { name: 'Salva una copia…' })
    await userEvent.click(copiaBtn)

    expect(salvaMock).toHaveBeenCalledWith('/Users/test/backups/rt-backup-20261019-120000')
    expect(screen.getByText('Salvo una copia…')).toBeInTheDocument()
  })

  it('l’annullamento lascia il riepilogo', async () => {
    const salvaMock = vi.fn().mockResolvedValue({ annullato: true })
    window.pywebview = { api: { salva_copia_backup: salvaMock } }

    render(<BackupDialog />)

    act(() => {
      window.__rtBackup?.({
        fine: true,
        percorso: '/Users/test/backups/rt-backup-20261019-120000',
        riepilogo: ['Backup completo.'],
      })
    })

    const copiaBtn = screen.getByRole('button', { name: 'Salva una copia…' })
    await userEvent.click(copiaBtn)

    expect(salvaMock).toHaveBeenCalled()
    expect(screen.getByText('Backup completo')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Salva una copia…' })).toBeInTheDocument()
  })

  it('un errore mostra l’avviso', () => {
    render(<BackupDialog />)

    act(() => {
      window.__rtBackup?.({ errore: 'Spazio su disco esaurito' })
    })

    expect(screen.getByText('Errore')).toBeInTheDocument()
    expect(screen.getByText('Spazio su disco esaurito')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Chiudi' })).toBeInTheDocument()
  })
})
