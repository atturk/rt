import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import type { Settings } from '@/api/settings'
import { TranscriptionSection } from './general'
import { testSettings } from './testSettings'

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
  it('su Windows niente macparakeet, Parakeet ONNX consigliato', async () => {
    renderSection({ engine: 'parakeet', recommended: 'parakeet', macparakeet_available: false, macparakeet_installed: false })
    expect(await engineChoices()).toEqual(['Parakeet ONNX (locale) · consigliato', 'Server OpenAI-compatible'])
    expect(screen.getByTestId('stt-engine-hint')).toHaveTextContent('si scarica alla prima trascrizione')
  })

  it('sul Mac macparakeet consigliato, Parakeet ONNX seconda scelta', async () => {
    renderSection({})
    expect(await engineChoices()).toEqual(['macparakeet (sul Mac) · consigliato', 'Parakeet ONNX (locale)', 'Server OpenAI-compatible'])
    await userEvent.setup().click(screen.getByRole('menuitemradio', { name: 'Parakeet ONNX (locale)' }))
    expect(screen.getByTestId('stt-engine')).toHaveAttribute('data-value', 'parakeet')
    expect(screen.getByTestId('stt-engine-hint')).toHaveTextContent('Gira su questo computer')
  })
})
