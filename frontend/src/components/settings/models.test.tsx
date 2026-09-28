import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { DecisionModelSection } from './models'

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DecisionModelSection /></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

describe('DecisionModelSection', () => {
  it('distingue il tipo del prefiltro dalle tre modalità del gate JEV', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { enabled: false, shadow: true, model: '', relevance_model: '', credential: 'openrouter',
        threshold: 0.85, relevance_mode: 'shadow', relevance_prompt: '', relevance_threshold: 0.85,
        prefilter_type: 'choice', prefilter_prompt: '' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)
    renderSection()
    const user = userEvent.setup()
    const behavior = await screen.findByLabelText('Comportamento JEV')
    expect(behavior).toHaveValue('shadow')
    expect(screen.getByRole('option', { name: /Disattivato/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Ombra/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Filtro attivo/ })).toBeInTheDocument()
    const requestType = screen.getByLabelText('Tipo di richiesta Jev del prefiltro')
    await user.selectOptions(requestType, 'noul')
    expect(requestType).toHaveValue('noul')
    expect(screen.getByLabelText('Soglia di errore del prefiltro')).toBeInTheDocument()
    expect(screen.getByLabelText('Istruzioni aggiuntive per la rilevanza')).toBeInTheDocument()
    expect(screen.getByLabelText('Istruzioni aggiuntive per il prefiltro errori')).toBeInTheDocument()
  })
})
