import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import { useRef } from 'react'
import { EnrichmentCard, EnrichmentSlots, GeneratedElement } from './Enrichment'
import type { Element } from '@/api/enrichment'

const mocks = vi.hoisted(() => ({ generate: vi.fn(), action: vi.fn(), refresh: vi.fn(), elements: [] as unknown[] }))
vi.mock('@/api/enrichment', () => ({
  useEnrichment: () => ({ data: { elements: mocks.elements } }),
  useEnrichmentActions: () => ({ generate: { mutate: mocks.generate }, action: { mutate: mocks.action }, refresh: mocks.refresh }),
}))
vi.mock('@/components/JobProgress', () => ({ JobProgress: () => <p>Job in corso</p> }))
const idea: Element = { id: 'abc', unit_id: '1.1', kind: 'visualization', title: 'Matrice dei vincoli', description: 'Esplora righe e variabili',
  prompt: 'Rappresenta la matrice', mode: 'interactive', status: 'suggestion', source_hash: 'hash', utility: .95, stale: false,
  manual: false, edited: false, job_id: null, error: null, asset_image: null, asset_html: null }
afterEach(() => { cleanup(); vi.clearAllMocks(); mocks.elements = [] })

describe('Arricchimento', () => {
  it('genera solo dopo Aggiungi e collega Modifica al form precompilato', () => {
    render(<MemoryRouter><EnrichmentCard element={idea} lessonId={7} /></MemoryRouter>)
    expect(mocks.generate).not.toHaveBeenCalled()
    expect(screen.getByRole('link', { name: 'Modifica' })).toHaveAttribute('href', '/lezioni/7/arricchimento?edit=abc#generazione')
    fireEvent.click(screen.getByRole('button', { name: 'Aggiungi' }))
    expect(mocks.generate).toHaveBeenCalledWith({ element_id: 'abc' })
    fireEvent.click(screen.getByRole('button', { name: 'Ignora Matrice dei vincoli' }))
    expect(mocks.action).toHaveBeenCalledWith({ element: 'abc', action: 'dismiss' })
  })
  it('mostra il frame in caricamento e conserva il contenuto durante la rigenerazione', () => {
    render(<MemoryRouter><EnrichmentCard element={{ ...idea, status: 'generating', job_id: 'job', asset_image: 'assets/enrichment/previous.png' }} lessonId={7} /></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('Rigenerazione in corso')
    expect(screen.getByAltText(idea.title)).toHaveAttribute('src', '/api/v1/lessons/7/assets/enrichment/previous.png')
    expect(screen.queryByRole('button', { name: 'Aggiungi' })).not.toBeInTheDocument()
  })
  it('isola la visualizzazione senza accesso same-origin', () => {
    render(<GeneratedElement lessonId={7} element={{ ...idea, asset_image: 'assets/enrichment/image.png', asset_html: 'assets/enrichment/view.html' }} />)
    const frame = screen.getByTitle(idea.title)
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts')
    expect(frame).toHaveAttribute('src', '/api/v1/lessons/7/assets/enrichment/view.html')
    const iframe = frame as HTMLIFrameElement
    window.dispatchEvent(new MessageEvent('message', { source: window, data: { type: 'rt-enrichment-resize', height: 900 } }))
    expect(iframe.style.height).toBe('600px')
    fireEvent(window, new MessageEvent('message', { source: iframe.contentWindow, data: { type: 'rt-enrichment-resize', height: 900 } }))
    expect(iframe.style.height).toBe('900px')
    fireEvent(window, new MessageEvent('message', { source: iframe.contentWindow, data: { type: 'rt-enrichment-resize', height: 99999 } }))
    expect(iframe.style.height).toBe('4000px')
  })
  it('inserisce le idee dopo il testo della subunità e omette quelle ignorate', async () => {
    mocks.elements = [idea, { ...idea, id: 'dismissed', status: 'dismissed' }]
    function Document() {
      const ref = useRef<HTMLDivElement>(null)
      return <><div ref={ref} dangerouslySetInnerHTML={{ __html: '<h3 data-unit-id="1.1">1.1 Matrice</h3><p>Testo della fonte</p><h3 data-unit-id="1.2">1.2 Successiva</h3><p>Altro testo</p>' }} />
        <EnrichmentSlots root={ref} lessonId={7} documentKey="document" /></>
    }
    const { container } = render(<MemoryRouter><Document /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText(idea.title)).toBeInTheDocument())
    expect(container.querySelector('p')?.nextElementSibling).toHaveClass('rt-enrichment-slot')
    expect(container.querySelector('[data-enrichment-id="dismissed"]')).toBeNull()
  })
})
