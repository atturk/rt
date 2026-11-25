import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
import { TranscriptionSection } from './general'
import { testSettings } from './testSettings'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function renderSection(transcription: Partial<Settings['transcription']>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TranscriptionSection settings={{ ...testSettings, transcription: { ...testSettings.transcription, ...transcription } }} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function engineChoices() {
  await userEvent.setup().click(screen.getByRole('button', { name: 'Motore' }))
  return screen.getAllByRole('menuitemradio').map((item) => item.textContent)
}

describe('Trascrizione: motori per sistema', () => {
  it('su Windows niente macparakeet, Parakeet ONNX consigliato e campi server nascosti', async () => {
    renderSection({ engine: 'parakeet', recommended: 'parakeet', macparakeet_available: false, macparakeet_installed: false })
    expect(await engineChoices()).toEqual(['Parakeet ONNX · consigliato', 'Server OpenAI-compatible'])
    expect(screen.getByTestId('stt-engine-hint')).toHaveTextContent('si scarica alla prima trascrizione')
    expect(screen.queryByLabelText('Base URL del server')).toBeNull()
    expect(screen.queryByLabelText('Modello')).toBeNull()
    expect(screen.queryByLabelText('Chiave API (facoltativa)')).toBeNull()
  })

  it('sul Mac macparakeet consigliato, cambio motore salva subito e custom mostra URL, modello e chiave', async () => {
    const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: testSettings, response: new Response('{}', { status: 200 }) } as never)
    renderSection({})
    expect(await engineChoices()).toEqual(['macparakeet · consigliato', 'Parakeet ONNX', 'Server OpenAI-compatible'])
    await userEvent.setup().click(screen.getByRole('menuitemradio', { name: 'Server OpenAI-compatible' }))
    expect(screen.getByTestId('stt-engine')).toHaveAttribute('data-value', 'custom')
    expect(put).toHaveBeenCalledWith('/api/v1/settings/transcription', {
      body: expect.objectContaining({ engine: 'custom' }),
    })

    const url = screen.getByLabelText('Base URL del server')
    fireEvent.change(url, { target: { value: 'http://127.0.0.1:9000/v1' } })
    fireEvent.blur(url)
    await waitFor(() => {
      expect(put).toHaveBeenCalledWith('/api/v1/settings/transcription', {
        body: expect.objectContaining({ engine: 'custom', base_url: 'http://127.0.0.1:9000/v1' }),
      })
    })
    expect(screen.getByRole('button', { name: 'Salva chiave' })).toBeDisabled()
  })
})
