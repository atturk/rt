import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { ComponentStatus } from '@/api/components'
import type { ConvertersInfo } from '@/api/converters'
import { ComponentsSection } from './components'

const ok = (data: unknown) => ({ data, error: undefined, response: new Response(JSON.stringify(data), { status: 200 }) }) as never

const baseTranscription: ComponentStatus = {
  id: 'transcription',
  name: 'Modello di trascrizione',
  description: "necessario per trascrivere l'audio",
  detail: 'Parakeet ONNX + VAD',
  required: true,
  state: 'not_downloaded',
  downloaded_bytes: 0,
  total_bytes: null,
  approx_bytes: 670 * 1024 * 1024,
  percent: null,
  eta_seconds: null,
  eta_label: null,
  error: null,
  available: true,
  unavailable_reason: null,
}

const baseBrowser: ComponentStatus = {
  id: 'browser',
  name: 'Browser per le catture',
  description: 'facoltativo',
  detail: 'Chromium Playwright',
  required: false,
  state: 'not_downloaded',
  downloaded_bytes: 0,
  total_bytes: null,
  approx_bytes: 170 * 1024 * 1024,
  percent: null,
  eta_seconds: null,
  eta_label: null,
  error: null,
  available: true,
  unavailable_reason: null,
}

function renderComponents(
  components: ComponentStatus[],
  pptx: ConvertersInfo['pptx'] = { available: true, methods: ['LibreOffice'], quicklook_available: false, platform: 'darwin' },
) {
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/components') return Promise.resolve(ok(components))
    if (path === '/api/v1/system/converters') return Promise.resolve(ok({ pptx }))
    return Promise.resolve(ok({}))
  }) as never)

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ComponentsSection />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ComponentsSection', () => {
  it('mostra le righe, i diversi stati e le azioni Scarica / Pausa / Riprendi / Riprova / Elimina', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...baseTranscription, state: 'downloading' }))
    const del = vi.spyOn(api, 'DELETE').mockResolvedValue(ok(baseBrowser))

    renderComponents([
      {
        ...baseTranscription,
        state: 'downloading',
        downloaded_bytes: 281 * 1024 * 1024,
        total_bytes: 670 * 1024 * 1024,
        percent: 42,
        eta_seconds: 360,
        eta_label: 'circa 6 min',
      },
      {
        ...baseBrowser,
        state: 'ready',
        downloaded_bytes: 165 * 1024 * 1024,
        total_bytes: 165 * 1024 * 1024,
        percent: 100,
      },
    ])

    const transRow = await screen.findByTestId('component-row-transcription')
    expect(transRow).toHaveTextContent("Modello di trascrizione — necessario per trascrivere l'audio")
    expect(transRow).toHaveTextContent('42%')
    expect(transRow).toHaveTextContent('circa 6 min')
    expect(within(transRow).getByTestId('component-badge-transcription')).toHaveTextContent('In download')

    const user = userEvent.setup()
    await user.click(within(transRow).getByRole('button', { name: 'Pausa' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/cancel', { params: { path: { component_id: 'transcription' } } })

    const browserRow = screen.getByTestId('component-row-browser')
    expect(browserRow).toHaveTextContent('Browser per le catture — facoltativo')
    expect(within(browserRow).getByTestId('component-badge-browser')).toHaveTextContent('Pronto')
    await user.click(within(browserRow).getByRole('button', { name: 'Elimina' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Elimina' }))
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith('/api/v1/components/{component_id}', { params: { path: { component_id: 'browser' } } }),
    )
  })

  it('mostra Riprendi su pausa e Riprova su errore', async () => {
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({ ...baseTranscription, state: 'downloading' }))
    renderComponents([
      { ...baseTranscription, state: 'paused', downloaded_bytes: 100 * 1024 * 1024, total_bytes: 670 * 1024 * 1024, percent: 15 },
      { ...baseBrowser, state: 'error', error: 'Rete assente' },
    ])

    const user = userEvent.setup()
    const transRow = await screen.findByTestId('component-row-transcription')
    expect(within(transRow).getByTestId('component-badge-transcription')).toHaveTextContent('In pausa')
    await user.click(within(transRow).getByRole('button', { name: 'Riprendi' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', { params: { path: { component_id: 'transcription' } } })

    const browserRow = screen.getByTestId('component-row-browser')
    expect(within(browserRow).getByTestId('component-badge-browser')).toHaveTextContent('Errore')
    expect(browserRow).toHaveTextContent('Rete assente')
    await user.click(within(browserRow).getByRole('button', { name: 'Riprova' }))
    expect(post).toHaveBeenCalledWith('/api/v1/components/{component_id}/download', { params: { path: { component_id: 'browser' } } })
  })

  it.each([
    {
      pptx: { available: true, methods: ['LibreOffice'], quicklook_available: false, platform: 'darwin' },
      expected: 'Presentazioni .pptx convertite con: LibreOffice',
      badge: 'Pronto',
    },
    {
      pptx: { available: true, methods: ['PowerPoint'], quicklook_available: false, platform: 'win32' },
      expected: 'Presentazioni .pptx convertite con: PowerPoint',
      badge: 'Pronto',
    },
    {
      pptx: { available: true, methods: ['Keynote'], quicklook_available: false, platform: 'darwin' },
      expected: 'Presentazioni .pptx convertite con: Keynote',
      badge: 'Pronto',
    },
    {
      pptx: { available: false, methods: [], quicklook_available: true, platform: 'darwin' },
      expected: 'Presentazioni .pptx convertite con: Quick Look (qualità ridotta)',
      badge: 'Qualità ridotta',
    },
    {
      pptx: { available: false, methods: [], quicklook_available: false, platform: 'win32' },
      expected: 'Presentazioni .pptx convertite con: nessuno (solo testo)',
      badge: 'Solo testo',
    },
  ])('riga Presentazioni: $expected', async ({ pptx, expected, badge }) => {
    renderComponents([baseTranscription], pptx)
    const row = await screen.findByTestId('presentations-row')
    await waitFor(() => expect(row).toHaveTextContent(expected))
    expect(row).toHaveTextContent(badge)
  })
})
