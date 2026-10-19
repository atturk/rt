import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import type { LessonImage } from '@/api/images'
import { MediaGallery } from './MediaGallery'
import { MediaSelectionBar } from './MediaSelectionBar'

const mockImages: LessonImage[] = [
  {
    name: 'source1-p1.png',
    url: '/media/source1-p1.png',
    source_name: 'Documento1.pdf',
    source: 'material',
    alt_text: 'Documento1.pdf, pagina 1',
    slide_title: '',
    page: 1,
    in_document: false,
    units: [],
    in_assets: false,
  },
  {
    name: 'source1-p2.png',
    url: '/media/source1-p2.png',
    source_name: 'Documento1.pdf',
    source: 'material',
    alt_text: 'Documento1.pdf, pagina 2',
    slide_title: '',
    page: 2,
    in_document: true,
    units: ['2.1'],
    in_assets: true,
  },
  {
    name: 'source1-p3.png',
    url: '/media/source1-p3.png',
    source_name: 'Documento1.pdf',
    source: 'material',
    alt_text: 'Documento1.pdf, pagina 3',
    slide_title: '',
    page: 3,
    in_document: false,
    units: [],
    in_assets: false,
  },
  {
    name: 'web-img1.png',
    url: '/media/web-img1.png',
    source_name: 'Dal web',
    source: 'web',
    alt_text: 'Immagine web',
    slide_title: '',
    page: null,
    in_document: true,
    units: ['1.2'],
    in_assets: true,
  },
]

describe('MediaGallery (MS1a & MS1b)', () => {
  it('raggruppa le immagini per fonte e mostra didascalia e stato d’uso', () => {
    const onToggleSelect = vi.fn()
    render(
      <MediaGallery
        images={mockImages}
        selectedNames={new Set()}
        onToggleSelect={onToggleSelect}
        onSelectRange={vi.fn()}
        onSelectGroup={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onOpenViewer={vi.fn()}
        onCrop={vi.fn()}
      />,
    )

    // Intestazioni dei gruppi
    expect(screen.getByText('Documento1.pdf')).toBeInTheDocument()
    expect(screen.getByText('1 usate su 3')).toBeInTheDocument()
    expect(screen.getByText('Dal web')).toBeInTheDocument()

    // Didascalie
    expect(screen.getByText('Pag. 1')).toBeInTheDocument()
    expect(screen.getByText('Pag. 2')).toBeInTheDocument()
    expect(screen.getByText('2.1')).toBeInTheDocument()
    expect(screen.getAllByText(/non usata/).length).toBe(2)
  })

  it('gestisce la vista rows (senza grid-cols-3, riquadro aspect-video) e grid (grid-cols-3)', () => {
    const { rerender } = render(
      <MediaGallery
        images={mockImages}
        selectedNames={new Set()}
        view="rows"
        onToggleSelect={vi.fn()}
        onSelectRange={vi.fn()}
        onSelectGroup={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onOpenViewer={vi.fn()}
        onCrop={vi.fn()}
      />,
    )

    const group = screen.getByRole('group', { name: 'Documento1.pdf' })
    expect(group).not.toHaveClass('grid-cols-3')
    expect(group).toHaveClass('flex-col')
    const button = screen.getByRole('button', { name: /Pagina 1/ })
    expect(button).toHaveClass('aspect-video')
    expect(button).not.toHaveClass('aspect-[4/3]')

    rerender(
      <MediaGallery
        images={mockImages}
        selectedNames={new Set()}
        view="grid"
        onToggleSelect={vi.fn()}
        onSelectRange={vi.fn()}
        onSelectGroup={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onOpenViewer={vi.fn()}
        onCrop={vi.fn()}
      />,
    )

    expect(group).toHaveClass('grid-cols-3')
    expect(button).toHaveClass('aspect-[4/3]')
    expect(button).not.toHaveClass('aspect-video')
    expect(screen.getByText(/Pag\. 1 ·/)).toBeInTheDocument()
  })

  it('permette di comprimere ed espandere un gruppo', () => {
    render(
      <MediaGallery
        images={mockImages}
        selectedNames={new Set()}
        onToggleSelect={vi.fn()}
        onSelectRange={vi.fn()}
        onSelectGroup={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onOpenViewer={vi.fn()}
        onCrop={vi.fn()}
      />,
    )

    const groupHeader = screen.getByRole('button', { name: /Documento1\.pdf/ })
    expect(groupHeader).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText(/Pagina 1, non usata/)).toBeInTheDocument()

    // Clic per comprimere
    fireEvent.click(groupHeader)
    expect(groupHeader).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText(/Pagina 1, non usata/)).not.toBeInTheDocument()

    // Clic per riespandere
    fireEvent.click(groupHeader)
    expect(groupHeader).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText(/Pagina 1, non usata/)).toBeInTheDocument()
  })

  it('MS1b: gestisce selezione singola, intervallo con shift e seleziona gruppo', () => {
    const onToggleSelect = vi.fn()
    const onSelectRange = vi.fn()
    const onSelectGroup = vi.fn()
    const onSelectAll = vi.fn()
    const onClearSelection = vi.fn()

    render(
      <MediaGallery
        images={mockImages}
        selectedNames={new Set(['source1-p1.png'])}
        onToggleSelect={onToggleSelect}
        onSelectRange={onSelectRange}
        onSelectGroup={onSelectGroup}
        onSelectAll={onSelectAll}
        onClearSelection={onClearSelection}
        onOpenViewer={vi.fn()}
        onCrop={vi.fn()}
      />,
    )

    const cell1 = screen.getByLabelText(/Pagina 1, non usata/)
    expect(cell1).toHaveAttribute('aria-pressed', 'true')

    // Clic su un'altra immagine
    const cell2 = screen.getByLabelText(/Pagina 2, usata in 2.1/)
    fireEvent.click(cell2)
    expect(onToggleSelect).toHaveBeenCalledWith('source1-p2.png')

    // Shift + Clic per intervallo
    const cell3 = screen.getByLabelText(/Pagina 3, non usata/)
    fireEvent.click(cell3, { shiftKey: true })
    expect(onSelectRange).toHaveBeenCalledWith(['source1-p2.png', 'source1-p3.png'])

    // Seleziona tutte le pagine della fonte dal pulsante del gruppo
    const groupSelectBtn = screen.getAllByLabelText('Seleziona tutte le pagine di questa fonte')[0]
    fireEvent.click(groupSelectBtn)
    expect(onSelectGroup).toHaveBeenCalledWith(mockImages.slice(0, 3))

    // ⌘A col fuoco sulla galleria
    const gallery = screen.getByTestId('media-gallery')
    fireEvent.keyDown(gallery, { key: 'a', metaKey: true })
    expect(onSelectAll).toHaveBeenCalled()

    // Esc annulla la selezione
    fireEvent.keyDown(gallery, { key: 'Escape' })
    expect(onClearSelection).toHaveBeenCalled()
  })

  it('MS1b: doppio clic e tocco lungo aprono il visore, forbici apre ritaglio', () => {
    vi.useFakeTimers()
    const onOpenViewer = vi.fn()
    const onCrop = vi.fn()

    render(
      <MediaGallery
        images={mockImages}
        selectedNames={new Set()}
        onToggleSelect={vi.fn()}
        onSelectRange={vi.fn()}
        onSelectGroup={vi.fn()}
        onSelectAll={vi.fn()}
        onClearSelection={vi.fn()}
        onOpenViewer={onOpenViewer}
        onCrop={onCrop}
      />,
    )

    const cell1 = screen.getByLabelText(/Pagina 1, non usata/)

    // Doppio clic
    fireEvent.doubleClick(cell1)
    expect(onOpenViewer).toHaveBeenCalledWith(0)

    // Tocco lungo (500ms)
    fireEvent.touchStart(cell1)
    vi.advanceTimersByTime(500)
    expect(onOpenViewer).toHaveBeenCalledWith(0)

    // Icona forbici
    const cropBtn = screen.getByLabelText('Ritaglia la pagina 1')
    fireEvent.click(cropBtn)
    expect(onCrop).toHaveBeenCalledWith(mockImages[0])

    vi.useRealTimers()
  })
})

describe('MediaSelectionBar', () => {
  it('mostra il conteggio e lo stato corretto dei pulsanti', () => {
    const onSelectAll = vi.fn()
    const onInsertAtCursor = vi.fn()
    const onAutoPlace = vi.fn()
    const onRemoveFromText = vi.fn()
    const onClearSelection = vi.fn()

    const { rerender } = render(
      <MediaSelectionBar
        selectedCount={0}
        hasUsedSelected={false}
        canInsertAtCursor={false}
        onSelectAll={onSelectAll}
        onInsertAtCursor={onInsertAtCursor}
        onAutoPlace={onAutoPlace}
        onRemoveFromText={onRemoveFromText}
        onClearSelection={onClearSelection}
      />,
    )

    // Nascosta se selectedCount === 0
    expect(screen.queryByTestId('media-selection-bar')).not.toBeInTheDocument()

    // Con 1 elemento selezionato
    rerender(
      <MediaSelectionBar
        selectedCount={1}
        hasUsedSelected={false}
        canInsertAtCursor={false}
        onSelectAll={onSelectAll}
        onInsertAtCursor={onInsertAtCursor}
        onAutoPlace={onAutoPlace}
        onRemoveFromText={onRemoveFromText}
        onClearSelection={onClearSelection}
      />,
    )
    expect(screen.getByText('1 selezionata')).toBeInTheDocument()

    // Inserisci al cursore è disabilitato se canInsertAtCursor è false
    const insBtn = screen.getByLabelText('Inserisci al cursore')
    expect(insBtn).toBeDisabled()

    // Togli dal testo è disabilitato se hasUsedSelected è false
    const removeBtn = screen.getByLabelText('Togli dal testo (resta nei media)')
    expect(removeBtn).toBeDisabled()

    // Con elementi usati e cursore abilitato
    rerender(
      <MediaSelectionBar
        selectedCount={2}
        hasUsedSelected={true}
        canInsertAtCursor={true}
        onSelectAll={onSelectAll}
        onInsertAtCursor={onInsertAtCursor}
        onAutoPlace={onAutoPlace}
        onRemoveFromText={onRemoveFromText}
        onClearSelection={onClearSelection}
      />,
    )
    expect(screen.getByText('2 selezionate')).toBeInTheDocument()
    expect(screen.getByLabelText('Inserisci al cursore')).not.toBeDisabled()
    expect(screen.getByLabelText('Togli dal testo (resta nei media)')).not.toBeDisabled()

    fireEvent.click(screen.getByLabelText('Inserisci al cursore'))
    expect(onInsertAtCursor).toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('Colloca in automatico le selezionate'))
    expect(onAutoPlace).toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('Togli dal testo (resta nei media)'))
    expect(onRemoveFromText).toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText('Annulla la selezione'))
    expect(onClearSelection).toHaveBeenCalled()
  })
})
