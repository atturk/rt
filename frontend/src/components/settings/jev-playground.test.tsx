import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { TYPES, PHASES, type Decision } from '@/lib/jev'
import { DecisionEditor, DecisionModelSection } from './jev-playground'

const relevanceChoice: Decision = {
  recall_richness: false, question: 'Classifica l’unità.', type: 'choice', fallback_label: 'Didattica', levels: [],
  options: [
    { label: 'didactic', description: 'Contenuto didattico' },
    { label: 'organizational', description: 'Solo organizzazione' },
    { label: 'no_content', description: 'Nessun contenuto' },
  ],
  rules: [
    { label: 'Organizzativa', outcome: 'organizational', match: 'all', conditions: [
      { field: 'choice', op: 'eq', value: 'organizational' }, { field: 'confidence', op: 'gte', value: 0.85 }] },
    { label: 'Senza contenuto', outcome: 'no_content', match: 'all', conditions: [
      { field: 'choice', op: 'eq', value: 'no_content' }, { field: 'confidence', op: 'gte', value: 0.85 }] },
  ],
}
const relevanceNoul: Decision = {
  recall_richness: false, question: 'Stima la probabilità che l’unità non sia didattica.', type: 'noul', fallback_label: 'Didattica', options: [], levels: [],
  rules: [{ label: 'Non didattica', outcome: 'no_content', match: 'all', conditions: [{ field: 'noul', op: 'gte', value: 0.85 }] }],
}
const prefilterChoice: Decision = {
  recall_richness: false, question: 'Gravità degli errori.', type: 'choice', fallback_label: 'Da revisionare', levels: [],
  options: [{ label: 'corretta', description: 'Corretta' }, { label: 'errore_grave', description: 'Errore grave' }],
  rules: [{ label: 'Nessun errore grave', outcome: 'skip_review', match: 'all', conditions: [
    { field: 'choice', op: 'ne', value: 'errore_grave' }, { field: 'confidence', op: 'gte', value: 0.85 }] }],
}
const scoreTemplate: Decision = { ...relevanceNoul, type: 'score', levels: ['Probabilità 0–1'], rules: [] }

const settings = {
  enabled: false, shadow: true, model: '', relevance_model: 'typesafe/jev-1.13', credential: 'openrouter',
  threshold: 0.85, relevance_mode: 'shadow', relevance_prompt: '', relevance_threshold: 0.85,
  prefilter_type: 'choice', prefilter_prompt: '',
  relevance_decision: relevanceChoice, prefilter_decision: prefilterChoice,
  relevance_customized: false, prefilter_customized: false,
  templates: {
    relevance: { choice: relevanceChoice, noul: relevanceNoul, score: scoreTemplate },
    prefilter: { choice: prefilterChoice, noul: relevanceNoul, score: scoreTemplate },
  },
}

const ok = (data: unknown) => ({ data, error: undefined, response: new Response('{}', { status: 200 }) }) as never

function mockGet() {
  return vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    if (path === '/api/v1/settings/decision-model') return Promise.resolve(ok(settings))
    if (path === '/api/v1/settings') return Promise.resolve(ok({ credentials: [{ name: 'openrouter', set: true }] }))
    if (path === '/api/v1/lessons') return Promise.resolve(ok([{ id: 7, titolo: 'Lipidi', folder_name: 'lipidi' }]))
    return Promise.resolve(ok({ mode: 'shadow', units: [{ unit_id: '1.2', title: 'Trigliceridi', content: 'Testo', effective: 'didactic' }] }))
  }) as never)
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DecisionModelSection /></QueryClientProvider>)
}

afterEach(() => vi.restoreAllMocks())

async function choose(label: string, option: string | RegExp) {
  await userEvent.click(await screen.findByRole('button', { name: label }))
  await userEvent.click(await screen.findByRole('menuitemradio', { name: option }))
}
async function options(label: string) {
  await userEvent.click(screen.getByRole('button', { name: label }))
  const values = screen.getAllByRole('menuitemradio')
  await userEvent.keyboard('{Escape}')
  return values
}


describe('DecisionModelSection', () => {
  it('sceglie la fase e mostra domanda, opzioni e mappatura predefinite', async () => {
    mockGet()
    renderSection()
    expect(await screen.findByLabelText('Domanda')).toHaveValue('Classifica l’unità.')
    expect(screen.getByTestId('jev-phase')).toHaveAttribute('data-value', 'relevance')
    expect(screen.queryByTestId('relevance-mode')).toBeNull()
    expect(screen.getAllByTestId('jev-option')).toHaveLength(3)
    expect(screen.getAllByTestId('jev-rule')).toHaveLength(2)
    expect(screen.getByText('Domanda predefinita')).toBeInTheDocument()

    await choose('Fase', PHASES.prefilter)
    expect(screen.getByLabelText('Domanda')).toHaveValue('Gravità degli errori.')
    expect(screen.queryByLabelText('Abilita il prefiltro errori')).toBeNull()
    expect(screen.getByTestId('Esito RT (regola 1)')).toHaveAttribute('data-value', 'skip_review')
    expect(screen.getByTestId('Operatore (regola 1, condizione 1)')).toHaveAttribute('data-value', 'ne')
  })

  it('cambiando tipo carica il modello della fase: noul ha solo la probabilità', async () => {
    mockGet()
    renderSection()
    await choose('Tipo di domanda', TYPES.noul)
    expect(screen.queryAllByTestId('jev-option')).toHaveLength(0)
    expect((await options('Campo (regola 1, condizione 1)')).map(o => o.textContent)).toEqual(['probabilità (noul)'])
    expect(screen.getByText('Modifiche non salvate')).toBeInTheDocument()
    await choose('Tipo di domanda', TYPES.score)
    expect(screen.getAllByTestId('jev-level')).toHaveLength(1)
  })

  it('prova la bozza sull’unità scelta e mostra etichetta, probabilità e JSON', async () => {
    mockGet()
    const post = vi.spyOn(api, 'POST').mockResolvedValue(ok({
      phase: 'relevance', unit_id: '1.2', unit_title: 'Trigliceridi', state: 'Titolo: Trigliceridi', request: {},
      response: { model: 'typesafe/jev-1.13', answers: { rilevanza: { type: 'choice', choice: 'organizational' } } },
      answer: { type: 'choice', choice: 'organizational', confidence: 0.91, probabilities: { didactic: 0.05, organizational: 0.91, no_content: 0.04 } },
      label: 'Organizzativa', outcome: 'organizational', rule: 0,
    }))
    renderSection()
    const user = userEvent.setup()
    await choose('Lezione di prova', 'Lipidi')
    await choose('Unità', /1\.2 · Trigliceridi/)
    await user.clear(screen.getByLabelText('Etichetta (regola 1)'))
    await user.type(screen.getByLabelText('Etichetta (regola 1)'), 'Logistica')
    await user.click(screen.getByRole('button', { name: 'Prova configurazione' }))

    const body = post.mock.calls[0][1] as { body: { phase: string; lesson_id: number; unit_id: string; decision: Decision } }
    expect(post.mock.calls[0][0]).toBe('/api/v1/settings/decision-model/test')
    expect(body.body).toMatchObject({ phase: 'relevance', lesson_id: 7, unit_id: '1.2', model: 'typesafe/jev-1.13' })
    expect(body.body.decision.rules?.[0].label).toBe('Logistica')
    const result = await screen.findByTestId('jev-result')
    expect(within(result).getByText('Organizzativa')).toBeInTheDocument()
    expect(within(result).getAllByText('91%')).toHaveLength(2) // confidenza e probabilità della scelta
    expect(within(result).getByText('5%')).toBeInTheDocument()
    expect(within(result).getByText('JSON del classificatore')).toBeInTheDocument()
  })

  it('salva entrambe le fasi con la bozza modificata', async () => {
    mockGet()
    const put = vi.spyOn(api, 'PUT').mockResolvedValue(ok(settings))
    renderSection()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Aggiungi etichetta' }))
    await user.click(screen.getByRole('button', { name: 'Salva' }))
    const body = (put.mock.calls[0][1] as { body: { relevance_decision: Decision; prefilter_decision: Decision } }).body
    expect(body.relevance_decision.rules).toHaveLength(3)
    expect(body.prefilter_decision).toEqual(prefilterChoice)
  })
})

function Editor({ initial }: { initial: Decision }) {
  const [decision, setDecision] = useState(initial)
  return <DecisionEditor phase="relevance" decision={decision} onChange={setDecision} onTypeChange={() => undefined} />
}

describe('DecisionEditor', () => {
  it('aggiunge e rimuove opzioni e condizioni con valori tipizzati', async () => {
    render(<Editor initial={relevanceChoice} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Aggiungi opzione' }))
    expect(screen.getAllByTestId('jev-option')).toHaveLength(4)
    await user.click(screen.getByRole('button', { name: 'Rimuovi opzione 4' }))
    expect(screen.getAllByTestId('jev-option')).toHaveLength(3)

    // Scelta: valore da un elenco delle opzioni, solo uguale/diverso.
    const value = screen.getByLabelText('Valore (regola 1, condizione 1)')
    expect(value.tagName).toBe('BUTTON')
    expect(await options('Operatore (regola 1, condizione 1)')).toHaveLength(2)
    // Campo numerico: input numerico e tutti gli operatori.
    await choose('Campo (regola 1, condizione 1)', 'probabilità di organizational')
    expect(screen.getByLabelText('Valore (regola 1, condizione 1)')).toHaveAttribute('type', 'number')
    expect(await options('Operatore (regola 1, condizione 1)')).toHaveLength(6)

    await user.click(screen.getByRole('button', { name: 'Aggiungi condizione (regola 1)' }))
    expect(within(screen.getAllByTestId('jev-rule')[0]).getAllByTestId('jev-condition')).toHaveLength(3)
    await choose('Combina condizioni (regola 1)', 'Almeno una')
    expect(within(screen.getAllByTestId('jev-rule')[0]).getAllByText('oppure')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Rimuovi regola 2' }))
    expect(screen.getAllByTestId('jev-rule')).toHaveLength(1)
  })
})
