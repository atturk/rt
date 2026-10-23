import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { StudyFlow } from './Study'
import type { Lesson } from '@/lib/format'
import { api as apiClient } from '@/api/client'

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
  media_count: 0,
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
  it('un clic sull’evidenziatore attivo cambia colore, dopo l’ultimo si spegne, e il colore resta', () => {
    renderStudy()
    const pen = screen.getByTestId('highlight-pen')
    expect(pen).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(pen)
    expect(pen).toHaveAttribute('aria-pressed', 'true')
    expect(pen).toHaveAttribute('data-color', '0')
    for (const expected of ['1', '2', '3', '4']) {
      fireEvent.click(pen)
      expect(pen).toHaveAttribute('data-color', expected)
    }
    fireEvent.click(pen)
    expect(pen).toHaveAttribute('aria-pressed', 'false')
    expect(pen).toHaveAttribute('data-color', '0')
    fireEvent.click(pen)
    fireEvent.click(pen)
    expect(pen).toHaveAttribute('aria-pressed', 'true')
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
    expect(screen.getByTestId('study')).toHaveAttribute('data-rsvp', 'true')
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
    act(() => { vi.advanceTimersByTime(3000) })
    act(() => { vi.advanceTimersByTime(2000) })
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
    expect(screen.getByTestId('study')).toHaveAttribute('data-rsvp', 'true')
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

  it('l nella lettura normale apre la lettura veloce; l nella lettura veloce torna allo Studio', async () => {
    renderStudy()
    await waitFor(() => expect(screen.getByTestId('study-rsvp-btn')).not.toHaveAttribute('aria-disabled', 'true'))

    // Con Shift non fa nulla
    fireEvent.keyDown(window, { key: 'L', shiftKey: true })
    expect(screen.queryByTestId('speed-reader')).not.toBeInTheDocument()

    // Con il focus in un campo non fa nulla
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    fireEvent.keyDown(input, { key: 'l' })
    expect(screen.queryByTestId('speed-reader')).not.toBeInTheDocument()
    document.body.removeChild(input)

    // l apre la lettura veloce
    fireEvent.keyDown(window, { key: 'l' })
    await waitFor(() => expect(screen.getByTestId('speed-reader')).toBeInTheDocument())

    // Shift+L in lettura veloce non chiude
    fireEvent.keyDown(window, { key: 'L', shiftKey: true })
    expect(screen.getByTestId('speed-reader')).toBeInTheDocument()

    // l chiude la lettura veloce
    fireEvent.keyDown(window, { key: 'l' })
    await waitFor(() => expect(screen.queryByTestId('speed-reader')).not.toBeInTheDocument())
  })

  it('durante la riproduzione speed-reader-panel ha opacity-25 e in pausa no', async () => {
    await open()
    const panel = screen.getByTestId('speed-reader-panel')
    expect(panel).toHaveClass('opacity-100')
    expect(panel).not.toHaveClass('opacity-25')

    fireEvent.keyDown(window, { key: ' ' })
    expect(panel).toHaveClass('opacity-25')

    fireEvent.keyDown(window, { key: ' ' })
    expect(panel).toHaveClass('opacity-100')
  })

  it('Alt+ArrowRight passa all’unità seguente, chiama preventDefault, mostra zen-notice e all’ultima unità il pulsante è disattivato', async () => {
    await open()
    const nextBtn = screen.getByRole('button', { name: /Unità successiva/ })
    expect(nextBtn).not.toHaveAttribute('aria-disabled', 'true')

    const event = new KeyboardEvent('keydown', { key: 'ArrowRight', altKey: true, bubbles: true, cancelable: true })
    const preventDefaultSpy = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)

    expect(preventDefaultSpy).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByTestId('speed-reader-word')).toHaveTextContent('Altro'))
    expect(screen.getByTestId('zen-notice')).toBeInTheDocument()

    // All'ultima unità non cambia nulla e il pulsante è disattivato
    expect(screen.getByRole('button', { name: /Unità successiva/ })).toHaveAttribute('aria-disabled', 'true')
  })

  it('s in lettura veloce cambia lo stato e mostra l’avviso', async () => {
    const put = vi.spyOn(apiClient, 'PUT').mockResolvedValue({ data: {}, response: new Response() } as never)
    await open()
    fireEvent.keyDown(window, { key: 's' })
    await waitFor(() => expect(put).toHaveBeenCalledWith(
      '/api/v1/lessons/{lesson_id}/study/units/{unit_id}',
      expect.objectContaining({ body: { status: 'in-apprendimento' } }),
    ))
    expect(screen.getByTestId('zen-notice')).toBeInTheDocument()
  })
})

it('evidenziatore e gomma mostrano il suggerimento di RT', async () => {
  renderStudy()
  fireEvent.mouseEnter(screen.getByTestId('highlight-pen'))
  expect(await screen.findByRole('tooltip', { name: /Evidenziatore giallo · clic: colore successivo, dopo l’ultimo si spegne · E/ })).toBeVisible()
  fireEvent.mouseLeave(screen.getByTestId('highlight-pen'))
  fireEvent.mouseEnter(screen.getByTestId('highlight-eraser'))
  expect(await screen.findByRole('tooltip', { name: /Gomma · clic su/ })).toBeVisible()
})

it('E e G attivano e tolgono lo strumento, ⇧E cambia colore; esclusi i campi', () => {
  renderStudy()
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'false')
  fireEvent.keyDown(window, { key: 'e' })
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'true')
  fireEvent.keyDown(window, { key: 'e' })
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'false')
  fireEvent.keyDown(window, { key: 'g' })
  expect(screen.getByTestId('highlight-eraser')).toHaveAttribute('aria-pressed', 'true')
  fireEvent.keyDown(window, { key: 'g' })
  expect(screen.getByTestId('highlight-eraser')).toHaveAttribute('aria-pressed', 'false')
  const input = document.createElement('input')
  document.body.append(input)
  fireEvent.keyDown(input, { key: 'e' })
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'false')
  input.remove()
  fireEvent.keyDown(window, { key: 'E', shiftKey: true })
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('data-color', '1')
})

it('con Chiedi o Verifica aperti le scorciatoie degli strumenti funzionano, con altri dialoghi no', () => {
  renderStudy()
  const popup = document.createElement('div')
  popup.setAttribute('role', 'dialog')
  popup.dataset.testid = 'study-note-popup'
  popup.append(document.createElement('button'))
  document.body.append(popup)
  fireEvent.keyDown(window, { key: 'g' })
  expect(screen.getByTestId('highlight-eraser')).toHaveAttribute('aria-pressed', 'true')
  fireEvent.keyDown(popup.firstChild!, { key: 'e' })
  expect(screen.getByTestId('highlight-pen')).toHaveAttribute('aria-pressed', 'true')
  popup.remove()
  const other = document.createElement('div')
  other.setAttribute('role', 'dialog')
  document.body.append(other)
  fireEvent.keyDown(window, { key: 'g' })
  expect(screen.getByTestId('highlight-eraser')).toHaveAttribute('aria-pressed', 'false')
  other.remove()
})

it('Z entra in zen, resta al cambio di unità; Esc chiude prima le impostazioni', () => {
  renderStudy()
  fireEvent.keyDown(window, { key: 'z' })
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
  expect(screen.getByTestId('study-dots')).not.toBeVisible()
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  expect(screen.getByRole('heading', { name: '1.2 Secondo' })).toBeVisible()
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Impostazioni zen' }))
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
  expect(screen.getByTestId('zen-settings')).not.toHaveAttribute('open')
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.getByTestId('study')).not.toHaveAttribute('data-zen')
})

it('D senza domande apre Genera anche in zen e blocca le scorciatoie', () => {
  renderStudy()
  fireEvent.keyDown(window, { key: 'z' })
  fireEvent.keyDown(window, { key: 'd' })
  expect(screen.getByTestId('study-generate-modal')).toHaveAttribute('open')
  fireEvent.keyDown(window, { key: 'z' })
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
})

it('S/E/G non rimontano il testo e non spostano lo scroll', async () => {
  renderStudy()
  await waitFor(() => expect(api.list).toHaveBeenCalled())
  const text = screen.getByTestId('study-text')
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  const by = vi.spyOn(window, 'scrollBy').mockImplementation(() => {})
  for (const key of ['s', 'e', 'g', 'E']) fireEvent.keyDown(window, { key, shiftKey: key === 'E' })
  expect(screen.getByTestId('study-text')).toBe(text)
  expect(scroll).not.toHaveBeenCalled()
  expect(by).not.toHaveBeenCalled()
  scroll.mockRestore(); by.mockRestore()
})

it('M apre e chiude la sezione immagini, anche in zen', async () => {
  renderStudy()
  await waitFor(() => expect(screen.getByTestId('study-text')).toBeInTheDocument())
  const text = screen.getByTestId('study-text')
  const button = document.createElement('button')
  button.className = 'rt-unit-images-button'
  button.dataset.unitImages = '1.1'
  let opened = false
  const slot = document.createElement('div')
  slot.className = 'rt-image-strip-slot'
  slot.dataset.unitImages = '1.1'
  slot.hidden = true
  button.onclick = () => {
    opened = !opened
    slot.hidden = !opened
  }
  text.before(button)
  text.before(slot)

  fireEvent.keyDown(window, { key: 'm' })
  expect(slot.hidden).toBe(false)

  fireEvent.keyDown(window, { key: 'm' })
  expect(slot.hidden).toBe(true)

  fireEvent.keyDown(window, { key: 'z' })
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')

  fireEvent.keyDown(window, { key: 'm' })
  expect(slot.hidden).toBe(false)

  fireEvent.keyDown(window, { key: 'm' })
  expect(slot.hidden).toBe(true)

  button.remove()
  slot.remove()
})

it('il triplo clic non seleziona il paragrafo', async () => {
  renderStudy()
  await waitFor(() => expect(api.list).toHaveBeenCalled())
  fireEvent.click(screen.getByTestId('highlight-pen'))
  expect(fireEvent.mouseDown(screen.getByTestId('study-text'), { detail: 3 })).toBe(false)
  expect(api.add).not.toHaveBeenCalled()
})

it.each(['evidenzia', 'gomma'])('il clic destro toglie un’evidenziazione in modalità %s', async mode => {
  api.list.mockResolvedValueOnce([{ id: 3, unit_id: '1.1', color: 2, source: { startMeta: { parentTagName: 'P', parentIndex: 0, textOffset: 3 }, endMeta: { parentTagName: 'P', parentIndex: 0, textOffset: 7 }, text: 'rene', id: 'a' } }])
  renderStudy()
  await waitFor(() => expect(screen.getByTestId('study-text').querySelector('.rt-hl')).toBeInTheDocument())
  if (mode === 'gomma') fireEvent.click(screen.getByTestId('highlight-eraser'))
  expect(fireEvent.contextMenu(screen.getByTestId('study-text').querySelector('.rt-hl')!)).toBe(false)
  await waitFor(() => expect(api.remove).toHaveBeenCalledWith(1, 3))
  expect(screen.getByTestId('study-text').querySelector('.rt-hl')).not.toBeInTheDocument()
  expect(fireEvent.contextMenu(screen.getByTestId('study-text'))).toBe(true)
})

it('al bordo la linguetta dura 5 s, si rinnova, si ferma col mouse e la freccia opposta la chiude', () => {
  vi.useFakeTimers()
  renderStudy()
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  expect(screen.getByTestId('lesson-jump-tab-right')).toBeVisible()
  act(() => { vi.advanceTimersByTime(4000) })
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  act(() => { vi.advanceTimersByTime(4000) })
  expect(screen.getByTestId('lesson-jump-tab-right')).toBeVisible()
  fireEvent.mouseEnter(screen.getByTestId('lesson-jump-tab-right'))
  act(() => { vi.advanceTimersByTime(6000) })
  expect(screen.getByTestId('lesson-jump-tab-right')).toBeVisible()
  fireEvent.mouseLeave(screen.getByTestId('lesson-jump-tab-right'))
  act(() => { vi.advanceTimersByTime(5000) })
  expect(screen.queryByTestId('lesson-jump-tab-right')).not.toBeInTheDocument()
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  fireEvent.keyDown(window, { key: 'ArrowLeft' })
  expect(screen.queryByTestId('lesson-jump-tab-right')).not.toBeInTheDocument()
})

it('la zen condivisa resta accesa quando la route rimonta il flusso', async () => {
  const { StudyZenContext } = await import('@/lib/zen')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const renderFlow = (key: string) => <QueryClientProvider client={client}><MemoryRouter>
    <StudyZenContext value={[true, () => undefined]}><StudyFlow key={key} lessons={[LESSON]} back={{ to: '/', label: 'Esci' }} /></StudyZenContext>
  </MemoryRouter></QueryClientProvider>
  const view = render(renderFlow('prima-lezione'))
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
  view.rerender(renderFlow('seconda-lezione'))
  expect(screen.getByTestId('study')).toHaveAttribute('data-zen', 'true')
})

it('il gruppo degli strumenti dello Studio si apre al passaggio del mouse e si chiude dopo 3 s', () => {
  vi.useFakeTimers()
  renderStudy()
  const toggle = screen.getByTestId('study-tools-toggle')
  expect(toggle).toBeVisible()
  expect(toggle).toHaveAttribute('aria-label', 'Strumenti')
  const toolsGroup = screen.getByTestId('highlight-tools')
  expect(toolsGroup).toHaveClass('hidden')

  // Hovering opens the group
  fireEvent.pointerEnter(toggle.parentElement!)
  expect(screen.queryByTestId('study-tools-toggle')).not.toBeInTheDocument()
  expect(toolsGroup).not.toHaveClass('hidden')
  expect(screen.getByTestId('highlight-clear')).toBeInTheDocument()

  // Leaving starts 3s delay
  fireEvent.pointerLeave(toolsGroup.parentElement!)
  act(() => { vi.advanceTimersByTime(2900) })
  expect(toolsGroup).not.toHaveClass('hidden')

  act(() => { vi.advanceTimersByTime(200) })
  expect(toolsGroup).toHaveClass('hidden')
  expect(screen.getByTestId('study-tools-toggle')).toBeVisible()

  // Keyboard shortcut works even when closed and updates closed icon/state
  fireEvent.keyDown(window, { key: 'e' })
  const toggleActive = screen.getByTestId('study-tools-toggle')
  expect(toggleActive).toBeVisible()
  expect(toggleActive.querySelector('.rt-hl-0')).toBeInTheDocument()

  // Clicking toggle opens it
  fireEvent.click(toggleActive)
  expect(toolsGroup).not.toHaveClass('hidden')

  // Esc closes it immediately
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(toolsGroup).toHaveClass('hidden')
})

