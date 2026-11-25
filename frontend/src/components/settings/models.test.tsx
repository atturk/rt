import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { Settings } from '@/api/settings'
import { PhaseRows } from './models'
import { testSettings } from './testSettings'

let client: QueryClient

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
})

it('mostra Chat dello Studio con opzione Come la Revisione', () => {
  const settings = {
    ...testSettings,
    phases: [
      ...testSettings.phases,
      { job: 'study_chat', label: 'Chat dello Studio', connection: null, model: null, batch: false },
    ],
  }
  render(
    <QueryClientProvider client={client}>
      <PhaseRows settings={settings} />
    </QueryClientProvider>,
  )
  const chatRow = screen.getByRole('form', { name: 'Fase Chat dello Studio' })
  expect(chatRow).toHaveTextContent('Come la Revisione')
  expect(chatRow).not.toHaveTextContent('Non assegnato')
})

it('mostra varianti batch e nota di background solo sulle fasi idonee e salva batch=true in automatico', async () => {
  const openrouterSettings: Settings = {
    ...testSettings,
    connections: [
      {
        name: 'openrouter_main',
        provider: 'openrouter',
        base_url: 'https://openrouter.ai/api/v1',
        models: ['google/gemini-2.5-flash'],
        supports_batch: true,
        batch_models: ['google/gemini-2.5-flash'],
        credentials: [{ name: 'or_1', set: true }],
      },
    ],
    phases: [
      { job: 'outline', label: 'Scaletta', connection: 'openrouter_main', model: 'google/gemini-2.5-flash', batch: false },
      { job: 'rewrite', label: 'Rielaborazione', connection: 'openrouter_main', model: 'google/gemini-2.5-flash', batch: false },
      { job: 'image_description', label: 'Descrizione immagini', connection: 'openrouter_main', model: 'google/gemini-2.5-flash', batch: false },
    ],
  }
  const put = vi.spyOn(api, 'PUT').mockResolvedValue({ data: openrouterSettings, response: new Response('{}', { status: 200 }) } as never)

  render(
    <QueryClientProvider client={client}>
      <PhaseRows settings={openrouterSettings} />
    </QueryClientProvider>,
  )

  const outlineRow = screen.getByRole('form', { name: 'Fase Scaletta' })
  const outlineBatchOption = outlineRow.querySelector(
    'option[value="google/gemini-2.5-flash:batch"]',
  ) as HTMLOptionElement | null
  expect(outlineBatchOption).not.toBeNull()
  expect(outlineBatchOption?.label).toContain('batch (−50%, risposte entro 24 h)')

  const imageRow = screen.getByRole('form', { name: 'Fase Descrizione immagini' })
  expect(imageRow.querySelector('option[value="google/gemini-2.5-flash:batch"]')).toBeNull()

  const outlineInput = within(outlineRow).getByLabelText('Modello')
  fireEvent.change(outlineInput, { target: { value: 'google/gemini-2.5-flash:batch' } })

  expect(within(outlineRow).getByTestId('phase-batch-hint')).toHaveTextContent(
    'Impostazioni → Aspetto e lettura → Chiudendo la finestra con la X',
  )

  fireEvent.blur(outlineInput)

  await waitFor(() => {
    expect(put).toHaveBeenCalledWith('/api/v1/settings/phases/{job}', {
      params: { path: { job: 'outline' } },
      body: { connection: 'openrouter_main', model: 'google/gemini-2.5-flash', batch: true },
    })
  })
})
