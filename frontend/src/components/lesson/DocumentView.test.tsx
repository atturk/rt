import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { vi } from 'vitest'

import { AudioProvider } from './audio'
import { DocumentView } from './DocumentView'
import { unmountDomTooltip } from '@/components/ui/dom-tooltip'

vi.mock('@/components/ui/dom-tooltip', () => ({ mountDomTooltip: vi.fn(), unmountDomTooltip: vi.fn() }))

function CurrentLocation() {
  const location = useLocation()
  return <output data-testid="document-location">{location.pathname + location.search}</output>
}

const doc = {
  final: false, pending: false,
  markdown: '',
  sections: [],
  html: '<h3 data-unit-id="1.1">Primo</h3><p>uno</p><h3 data-unit-id="1.2">Secondo</h3><p>due</p>',
}

describe('DocumentView', () => {
  it('link di Studio e ripasso anche senza timestamp, niente link organizzativi o duplicati, cleanup completo', () => {
    const document = { ...doc, html: doc.html + '<h3 data-unit-id="1.3">Organizzazione</h3>', sections: [
      { unit_id: '1.1', title: 'Primo', start_segment_id: 'seg_1', end_segment_id: 'seg_2', start_seconds: 0, end_seconds: 60, start_formatted: '00:00' },
      { unit_id: '1.2', title: 'Secondo', start_segment_id: 'seg_3', end_segment_id: 'seg_4', start_seconds: null, end_seconds: null },
      { unit_id: '1.3', title: 'Organizzazione', start_segment_id: 'seg_5', end_segment_id: 'seg_5', start_seconds: null, end_seconds: null, relevance: 'organizational' as const },
    ] }
    const client = new QueryClient()
    const tree = (hasAudio: boolean) => <QueryClientProvider client={client}><MemoryRouter initialEntries={['/lezioni/7']}>
      <CurrentLocation /><AudioProvider><DocumentView document={document} hasAudio={hasAudio} lessonId={7} /></AudioProvider>
    </MemoryRouter></QueryClientProvider>
    const view = render(tree(false))
    for (const unit of ['1.1', '1.2']) {
      expect(screen.getByRole('link', { name: `Studia l'unità ${unit}` })).toHaveAttribute('href', `/studio/lezione/7?unita=${unit}`)
      expect(screen.getByRole('link', { name: `Ripassa l'unità ${unit}` })).toHaveAttribute('href', `/studio/lezione/7?unita=${unit}&azione=ripasso`)
    }
    expect(screen.queryByRole('link', { name: /l'unità 1.3/ })).not.toBeInTheDocument()
    const oldLinks = screen.getAllByRole('link')
    view.rerender(tree(true))
    expect(screen.getAllByRole('link')).toHaveLength(4)
    for (const link of oldLinks) expect(unmountDomTooltip).toHaveBeenCalledWith(link)
    fireEvent.click(screen.getByRole('link', { name: "Studia l'unità 1.2" }))
    expect(screen.getByTestId('document-location')).toHaveTextContent('/studio/lezione/7?unita=1.2')
    const remaining = screen.getAllByRole('link')
    view.unmount()
    for (const link of remaining) expect(unmountDomTooltip).toHaveBeenCalledWith(link)
  })

  it('il link "Vai all\'unità" (#unit-<id>) porta in vista e segna quell\'unità', () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/lezioni/1#unit-1.2']}>
          <AudioProvider><DocumentView document={doc} hasAudio={false} lessonId={1} /></AudioProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const marked = Array.from(container.querySelectorAll('.rt-claim-unit')).map((el) => el.textContent)
    expect(marked).toEqual(['Secondo', 'due'])
    expect(scroll).toHaveBeenCalledOnce()
  })

  it('mostra la linea audio AU1 sull’unità attiva e non su quelle future quando hasAudio è true', () => {
    const docWithSections = {
      ...doc,
      sections: [
        {
          unit_id: '1.1',
          title: 'Primo',
          start_segment_id: 'seg_1',
          end_segment_id: 'seg_2',
          start_seconds: 0,
          end_seconds: 60,
          speech_segments: [[0, 40], [50, 60]],
        },
        {
          unit_id: '1.2',
          title: 'Secondo',
          start_segment_id: 'seg_3',
          end_segment_id: 'seg_4',
          start_seconds: 60,
          end_seconds: 120,
          speech_segments: [[60, 120]],
        },
      ],
    }

    let result!: ReturnType<typeof render>
    act(() => {
      result = render(
        <QueryClientProvider client={new QueryClient()}>
          <MemoryRouter initialEntries={['/lezioni/1']}>
            <AudioProvider>
              <DocumentView document={docWithSections} hasAudio={true} lessonId={1} />
            </AudioProvider>
          </MemoryRouter>
        </QueryClientProvider>,
      )
    })
    const { getByTestId, queryByTestId } = result

    // A tempo 0, l'unità 1.1 è attiva
    expect(getByTestId('audio-line-1.1')).toBeInTheDocument()
    expect(getByTestId('audio-line-1.1')).toHaveAttribute('data-active', 'true')
    // L'unità 1.2 non è ancora raggiunta
    expect(queryByTestId('audio-line-1.2')).not.toBeInTheDocument()
  })
})

it('mostra la graffetta prima del timecode e solo le immagini dichiarate nella sezione', () => {
  const document = { ...doc, html: '<h3 data-unit-id="1.1">Primo</h3><p data-unit-timecode="1.1">00:00</p><p><img src="assets/images/a.png" alt="Pagina"></p><p>Testo</p><p><img src="assets/images/b.png#w=240" width="240"></p>', sections: [
    { unit_id: '1.1', title: 'Primo', start_segment_id: 'seg_1', end_segment_id: 'seg_2', start_seconds: 0, start_formatted: '00:00', immagini_sezione: ['a.png'] },
  ] }
  const tree = <QueryClientProvider client={new QueryClient()}><MemoryRouter><AudioProvider><DocumentView document={document} hasAudio={false} lessonId={1} /></AudioProvider></MemoryRouter></QueryClientProvider>
  const view = render(tree)
  const button = screen.getByRole('button', { name: 'Mostra le immagini' })
  expect(button).toHaveTextContent('1')
  expect(button.nextElementSibling).toHaveClass('rt-timecode')
  const slot = view.container.querySelector<HTMLElement>('.rt-unit-images-section')!
  expect(slot.hidden).toBe(true)
  fireEvent.click(button)
  expect(slot.hidden).toBe(false)
  expect(view.container.querySelectorAll('.rt-unit-images-section img')).toHaveLength(1)
  expect(view.container.querySelector('p img[width="240"]')).toBeInTheDocument()
})
