import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PermissionsPage } from './permissions'

let client: QueryClient

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
  sessionStorage.clear()
  delete (window as unknown as { pywebview?: unknown }).pywebview
})

function renderPage() {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/permessi']}>
        <PermissionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Pagina /permessi', () => {
  it('nel browser mostra solo la nota Disponibile nell app RT', () => {
    renderPage()
    expect(screen.getByText("Disponibile nell'app RT.")).toBeInTheDocument()
    expect(screen.queryByText('Microfono')).toBeNull()
  })

  it('su Mac elenca i permessi e chiama l API desktop sui clic', async () => {
    sessionStorage.setItem('rt-app', '1')
    const openSettings = vi.fn().mockResolvedValue({ ok: true })
    const askMic = vi.fn().mockResolvedValue({ status: 'authorized' })
    const statusMock = vi.fn().mockResolvedValue({
      platform: 'darwin',
      microfono: 'undetermined',
      file_e_cartelle: { rilevante: true, stato: 'denied', percorso: '/Users/x/Desktop/Lezioni' },
      automazione_keynote: { rilevante: true },
      elementi_background: { stato: 'authorized' },
      rete_locale: { attivo: true },
    })
    const micStatusMock = vi.fn().mockResolvedValue('undetermined')
    ;(window as unknown as { pywebview: unknown }).pywebview = {
      api: {
        stato_permessi: statusMock,
        stato_microfono: micStatusMock,
        richiedi_microfono: askMic,
        apri_impostazioni_sistema: openSettings,
      },
    }

    renderPage()

    expect(await screen.findByText('Microfono')).toBeInTheDocument()
    expect(screen.getByText('File e cartelle')).toBeInTheDocument()
    expect(screen.getByText('Automazione → Keynote')).toBeInTheDocument()
    expect(screen.getByText('Elementi in background')).toBeInTheDocument()
    expect(screen.getByText('Rete locale')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Chiedi di nuovo' }))
    expect(askMic).toHaveBeenCalledTimes(1)

    const buttons = screen.getAllByRole('button', { name: 'Apri impostazioni di sistema' })
    expect(buttons).toHaveLength(5)
    await userEvent.click(buttons[1])
    expect(openSettings).toHaveBeenCalledWith('file_e_cartelle')
    await userEvent.click(buttons[3])
    expect(openSettings).toHaveBeenCalledWith('elementi_background')
    await userEvent.click(buttons[4])
    expect(openSettings).toHaveBeenCalledWith('rete_locale')
  })

  it('su Windows mostra Microfono, Firewall (Reti private) e nota background', async () => {
    sessionStorage.setItem('rt-app', '1')
    const openSettings = vi.fn().mockResolvedValue({ ok: true })
    ;(window as unknown as { pywebview: unknown }).pywebview = {
      api: {
        stato_permessi: vi.fn().mockResolvedValue({
          platform: 'win32',
          microfono: 'unknown',
          rete_locale: { attivo: false },
        }),
        stato_microfono: vi.fn().mockResolvedValue('unknown'),
        apri_impostazioni_sistema: openSettings,
      },
    }

    renderPage()

    expect(await screen.findByText('Microfono')).toBeInTheDocument()
    expect(screen.getByText('Firewall di Windows')).toBeInTheDocument()
    expect(screen.getByText(/Reti private/)).toBeInTheDocument()
    expect(screen.getByText('Avvio e lavoro in background')).toBeInTheDocument()
    expect(screen.queryByText('Automazione → Keynote')).toBeNull()

    const buttons = screen.getAllByRole('button', { name: 'Apri impostazioni di sistema' })
    expect(buttons).toHaveLength(2)
    await userEvent.click(buttons[1])
    expect(openSettings).toHaveBeenCalledWith('firewall')
  })
})
