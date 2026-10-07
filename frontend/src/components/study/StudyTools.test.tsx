import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { StudyFlow } from './Study'
import type { Lesson } from '@/lib/format'

const api = vi.hoisted(() => ({
  list: vi.fn(async () => [] as unknown[]),
  add: vi.fn(async () => ({ id: 7 })),
  remove: vi.fn(async () => undefined),
  clear: vi.fn(async () => undefined),
}))
vi.mock('@/api/highlights', () => ({ highlightsApi: api }))
// Le preferenze su RT qui stanno solo nella copia locale.
vi.mock('@/lib/preferences', async () => {
  const { useState } = await import('react')
  return {
    usePreference<T>(name: string, fallback: T) {
      const [value, setValue] = useState<T>(() => JSON.parse(localStorage.getItem(`rt-pref:${name}`) ?? 'null') ?? fallback)
      return [value, (next: T) => { localStorage.setItem(`rt-pref:${name}`, JSON.stringify(next)); setValue(next) }]
    },
  }
})

const LESSON = {
  id: 1, materia: 'FISIOLOGIA', titolo: 'Acidosi', ora: '', data: '2026-10-02', folder_name: 'a',
  phases: { build: 'VALID', rewrite: 'VALID' }, argomenti: '', docente: '', path: '', duration_seconds: 0,
  unit_count: 2, pending_issues: 0, recall_pending: 0, study_learned: 0, study_learning: 0, study_ignored: 0, recall_questions: 0,
} as Lesson
const UNITS = [
  { id: '1.1', title: 'Primo', html: '<p>Il rene filtra il sangue. Poi, riassorbe acqua e sali.</p>', questions: 0, pending: {} },
  { id: '1.2', title: 'Secondo', html: '<p>Altro testo.</p>', questions: 0, pending: {} },
]
vi.mock('@/api/recall', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/recall')>()),
  useStudyLesson: () => ({ data: { id: 1, units: UNITS, has_audio: false }, isPending: false, isError: false }),
}))

function renderStudy() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><StudyFlow lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  Object.values(api).forEach((fn) => fn.mockClear())
})
afterEach(() => {
  vi.useRealTimers()
  document.documentElement.classList.remove('dark')
})

describe('evidenziatore dello Studio', () => {
  it('un clic sull’evidenziatore attivo cambia colore a giro, e il colore resta', () => {
    renderStudy()
    const pen = screen.getByTestId('highlight-pen')
    expect(pen).toHaveAttribute('aria-pressed', 'true')
    expect(pen).toHaveAttribute('data-color', '0')
    for (const expected of ['1', '2', '3', '4', '0', '1']) {
      fireEvent.click(pen)
      expect(pen).toHaveAttribute('data-color', expected)
    }
    expect(JSON.parse(localStorage.getItem('rt-pref:study.highlighter')!)).toMatchObject({ color: 1, arrows: true })
  })

  it('con la gomma un clic sull’evidenzatore torna all’evidenziatore senza cambiare colore', () => {
    renderStudy()
    fireEvent.click(screen.getByTestId('highlight-eraser'))
    expect(screen.getByTestId('highlight-eraser')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('study-text')).toHaveAttribute('data-hl-mode', 'erase')
    fireEvent.click(screen.getByTestId('highlight-pen'))
    expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('highlight-pen')).toHaveAttribute('data-color', '0')
  })

  it('il cestino chiede conferma e toglie tutte le evidenziazioni dell’unità', async () => {
    renderStudy()
    fireEvent.click(screen.getByTestId('highlight-clear'))
    expect(screen.getByText('Togli tutte le evidenziazioni di questa unità?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Annulla' }))
    expect(api.clear).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('highlight-clear'))
    fireEvent.click(screen.getByTestId('highlight-clear-confirm'))
    await waitFor(() => expect(api.clear).toHaveBeenCalledWith(1, '1.1'))
    await waitFor(() => expect(screen.queryByText('Togli tutte le evidenziazioni di questa unità?')).not.toBeInTheDocument())
  })

  it('all’apertura dell’unità ridisegna le evidenziazioni salvate e salta quelle che non si ritrovano', async () => {
    api.list.mockResolvedValueOnce([
      { id: 3, unit_id: '1.1', color: 2, source: { startMeta: { parentTagName: 'P', parentIndex: 0, textOffset: 3 }, endMeta: { parentTagName: 'P', parentIndex: 0, textOffset: 7 }, text: 'rene', id: 'a' } },
      { id: 4, unit_id: '1.1', color: 0, source: { startMeta: { parentTagName: 'P', parentIndex: 0, textOffset: 0 }, endMeta: { parentTagName: 'P', parentIndex: 0, textOffset: 2 }, text: 'XX', id: 'b' } },
    ])
    renderStudy()
    await waitFor(() => expect(screen.getByTestId('study-text').querySelector('.rt-hl-2')).toHaveTextContent('rene'))
    expect(screen.getByTestId('study-text').querySelectorAll('.rt-hl')).toHaveLength(1)
    expect(api.list).toHaveBeenCalledWith(1, '1.1')
  })
})

describe('lettura veloce', () => {
  async function open() {
    renderStudy()
    await waitFor(() => expect(screen.getByTestId('study-rsvp-btn')).not.toHaveAttribute('aria-disabled', 'true'))
    fireEvent.click(screen.getByTestId('study-rsvp-btn'))
    return screen.getByTestId('speed-reader')
  }

  it('si apre sull’unità, con il tema dell’app, e Esc torna allo Studio', async () => {
    document.documentElement.classList.add('dark')
    const reader = await open()
    expect(reader).not.toHaveAttribute('data-theme-mode')
    expect(reader).not.toHaveClass('fixed')
    expect(screen.queryByRole('button', { name: /Giorno|Notte/ })).not.toBeInTheDocument()
    expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Il')
    expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
    expect(screen.queryByTestId('study-title-button')).not.toBeInTheDocument()
    expect(document.documentElement).toHaveClass('dark')
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('speed-reader')).not.toBeInTheDocument())
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Primo' })).toBeInTheDocument()
  })

  it('le scorciatoie non intercettano i controlli dell’intestazione e delle impostazioni', async () => {
    await open()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Torna allo Studio' }), { key: ' ' })
    expect(screen.getByRole('button', { name: 'Avvia' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Impostazioni della lettura veloce' }))
    fireEvent.keyDown(screen.getByRole('slider', { name: 'Tono' }), { key: 'ArrowUp' })
    expect(screen.getByText('300')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.getByRole('button', { name: 'Impostazioni della lettura veloce' })).toHaveFocus()
  })

  it('il testo intorno si vede solo in pausa', async () => {
    await open()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Poi,')
    expect(screen.getByTestId('speed-reader-after')).toHaveTextContent('riassorbe acqua e sali.')
    vi.useFakeTimers()
    fireEvent.keyDown(window, { key: ' ' })
    expect(screen.getByTestId('speed-reader-after')).toBeEmptyDOMElement()
    expect(screen.getByTestId('speed-reader-before')).toBeEmptyDOMElement()
    act(() => { vi.advanceTimersByTime(5000) })
    expect(screen.getByTestId('speed-reader-word')).not.toHaveTextContent('Poi,')
    fireEvent.keyDown(window, { key: ' ' })
    expect(screen.getByTestId('speed-reader-before')).not.toBeEmptyDOMElement()
  })

  it('tasti: frasi, velocità, Home, e le frecce non cambiano unità dello Studio', async () => {
    await open()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Poi,')
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Il')
    fireEvent.keyDown(window, { key: 'ArrowUp' })
    expect(screen.getByText('325')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    expect(screen.getByText('275')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    fireEvent.keyDown(window, { key: 'Home' })
    expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Il')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.getByRole('heading', { level: 2, name: '1.1 Primo' })).toBeInTheDocument()
  })

  it('l’indice cambia unità restando in zen, il libro torna al testo e conserva le preferenze', async () => {
    await open()
    fireEvent.click(screen.getByTestId('unit-index-toggle'))
    fireEvent.click(screen.getByRole('menuitem', { name: /1.2 Secondo/ }))
    await waitFor(() => expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Altro'))
    expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Impostazioni della lettura veloce' }))
    fireEvent.change(screen.getByRole('slider', { name: 'Pausa dopo la frase' }), { target: { value: '650' } })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByTestId('speed-reader-settings')).not.toBeInTheDocument()
    expect(screen.getByTestId('speed-reader')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Torna allo Studio' }))
    await waitFor(() => expect(screen.queryByTestId('speed-reader')).not.toBeInTheDocument())
    expect(JSON.parse(localStorage.getItem('rt-pref:study.rsvp')!)).toMatchObject({ pauseMs: 650 })
    expect(screen.getByRole('heading', { level: 2, name: '1.2 Secondo' })).toBeInTheDocument()
  })

  it('con "virgola come pausa piena" la parola con la virgola diventa fine frase', async () => {
    await open()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByTestId('speed-reader-word')).toHaveAttribute('data-kind', 'normale')
    fireEvent.click(screen.getByRole('button', { name: 'Impostazioni della lettura veloce' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Virgola come pausa piena' }))
    expect(screen.getByTestId('speed-reader-word')).toHaveAttribute('data-kind', 'fine')
  })
})

it('evidenziatore e gomma mostrano il suggerimento di RT', async () => {
  renderStudy()
  fireEvent.mouseEnter(screen.getByTestId('highlight-pen'))
  expect(await screen.findByRole('tooltip', { name: /Evidenziatore giallo · clic: colore successivo · E/ })).toBeVisible()
  fireEvent.mouseLeave(screen.getByTestId('highlight-pen'))
  fireEvent.mouseEnter(screen.getByTestId('highlight-eraser'))
  expect(await screen.findByRole('tooltip', { name: /Gomma · clic su/ })).toBeVisible()
})
