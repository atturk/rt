import { act, fireEvent, render, screen } from '@testing-library/react'
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
    descritta: false,
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
    descritta: true,
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
    descritta: true,
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
    descritta: true,
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

  it('MS1b: doppio clic e tocco lungo aprono il visore, nessun pulsante forbici sulle miniature', () => {
    vi.useFakeTimers()
    const onOpenViewer = vi.fn()

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
      />,
    )

    const cell1 = screen.getByLabelText(/Pagina 1, non usata/)

    // Puntino arancione sulle non descritte
    expect(screen.getByTestId('undescribed-dot')).toBeInTheDocument()

    // Doppio clic
    fireEvent.doubleClick(cell1)
    expect(onOpenViewer).toHaveBeenCalledWith(0)

    // Tocco lungo (500ms)
    fireEvent.touchStart(cell1)
    vi.advanceTimersByTime(500)
    expect(onOpenViewer).toHaveBeenCalledWith(0)

    // Nessun pulsante forbici sulle miniature
    expect(screen.queryByLabelText(/Ritaglia/i)).not.toBeInTheDocument()

    vi.useRealTimers()
  })

  describe('Anteprima tenendo premuto (peek in vista grid)', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('pointerDown su cella in vista grid per 350 ms apre anteprima; pointerUp su window la chiude senza cambiare selezione', () => {
      const onToggleSelect = vi.fn()
      render(
        <MediaGallery
          images={mockImages}
          selectedNames={new Set()}
          view="grid"
          onToggleSelect={onToggleSelect}
          onSelectRange={vi.fn()}
          onSelectGroup={vi.fn()}
          onSelectAll={vi.fn()}
          onClearSelection={vi.fn()}
          onOpenViewer={vi.fn()}
          onCrop={vi.fn()}
        />,
      )

      const cell = screen.getByRole('button', { name: /Pagina 1/ })
      expect(cell).toHaveAttribute('aria-pressed', 'false')

      // PointerDown con mouse (tasto sinistro = button 0)
      fireEvent.pointerDown(cell, { pointerType: 'mouse', button: 0, clientX: 100, clientY: 100 })
      expect(screen.queryByRole('dialog', { name: /Anteprima pagina 1/ })).not.toBeInTheDocument()

      // Avanziamo di 350 ms
      act(() => {
        vi.advanceTimersByTime(350)
      })

      // Compare il dialog
      expect(screen.getByRole('dialog', { name: 'Anteprima pagina 1' })).toBeInTheDocument()

      // pointerUp su window chiude l'anteprima
      fireEvent.pointerUp(window)
      expect(screen.queryByRole('dialog', { name: 'Anteprima pagina 1' })).not.toBeInTheDocument()

      // Il click che segue non cambia la selezione
      fireEvent.click(cell)
      expect(onToggleSelect).not.toHaveBeenCalled()
      expect(cell).toHaveAttribute('aria-pressed', 'false')
    })

    it('pointerDown e pointerUp prima di 350 ms: nessuna anteprima, il clic seleziona normalmente', () => {
      const onToggleSelect = vi.fn()
      render(
        <MediaGallery
          images={mockImages}
          selectedNames={new Set()}
          view="grid"
          onToggleSelect={onToggleSelect}
          onSelectRange={vi.fn()}
          onSelectGroup={vi.fn()}
          onSelectAll={vi.fn()}
          onClearSelection={vi.fn()}
          onOpenViewer={vi.fn()}
          onCrop={vi.fn()}
        />,
      )

      const cell = screen.getByRole('button', { name: /Pagina 1/ })
      fireEvent.pointerDown(cell, { pointerType: 'mouse', button: 0, clientX: 100, clientY: 100 })

      act(() => {
        vi.advanceTimersByTime(200)
      })
      fireEvent.pointerUp(cell)

      act(() => {
        vi.advanceTimersByTime(200)
      })
      expect(screen.queryByRole('dialog', { name: /Anteprima pagina 1/ })).not.toBeInTheDocument()

      fireEvent.click(cell)
      expect(onToggleSelect).toHaveBeenCalledWith(mockImages[0].name)
    })

    it('pointerDown poi pointerMove di 10 px annulla l’anteprima', () => {
      render(
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

      const cell = screen.getByRole('button', { name: /Pagina 1/ })
      fireEvent.pointerDown(cell, { pointerType: 'mouse', button: 0, clientX: 100, clientY: 100 })
      fireEvent.pointerMove(cell, { clientX: 110, clientY: 100 })

      act(() => {
        vi.advanceTimersByTime(400)
      })
      expect(screen.queryByRole('dialog', { name: /Anteprima pagina 1/ })).not.toBeInTheDocument()
    })

    it('Escape chiude l’anteprima', () => {
      render(
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

      const cell = screen.getByRole('button', { name: /Pagina 1/ })
      fireEvent.pointerDown(cell, { pointerType: 'mouse', button: 0, clientX: 100, clientY: 100 })
      act(() => {
        vi.advanceTimersByTime(350)
      })
      expect(screen.getByRole('dialog', { name: 'Anteprima pagina 1' })).toBeInTheDocument()

      fireEvent.keyDown(window, { key: 'Escape' })
      expect(screen.queryByRole('dialog', { name: 'Anteprima pagina 1' })).not.toBeInTheDocument()
    })

    it('in vista rows tenere premuto non apre l’anteprima', () => {
      render(
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

      const cell = screen.getByRole('button', { name: /Pagina 1/ })
      fireEvent.pointerDown(cell, { pointerType: 'mouse', button: 0, clientX: 100, clientY: 100 })
      act(() => {
        vi.advanceTimersByTime(500)
      })
      expect(screen.queryByRole('dialog', { name: /Anteprima/ })).not.toBeInTheDocument()
    })
  })
})

describe('MediaSelectionBar', () => {
  it('mostra il conteggio e lo stato corretto dei pulsanti', () => {
    const onDescribe = vi.fn()
    const onInsertAtCursor = vi.fn()
    const onAutoPlace = vi.fn()
    const onCrop = vi.fn()
    const onRemoveFromText = vi.fn()
    const onDelete = vi.fn()

    const { rerender } = render(
      <MediaSelectionBar
        selectedCount={0}
        canDescribe={false}
        hasUsedSelected={false}
        canInsertAtCursor={false}
        onDescribe={onDescribe}
        onInsertAtCursor={onInsertAtCursor}
        onAutoPlace={onAutoPlace}
        onCrop={onCrop}
        onRemoveFromText={onRemoveFromText}
        onDelete={onDelete}
        canDelete={false}
      />,
    )

    // Nascosta se selectedCount === 0
    expect(screen.queryByTestId('media-selection-bar')).not.toBeInTheDocument()

    // Con 1 elemento selezionato
    rerender(
      <MediaSelectionBar
        selectedCount={1}
        canDescribe={false}
        hasUsedSelected={false}
        canInsertAtCursor={false}
        onDescribe={onDescribe}
        onInsertAtCursor={onInsertAtCursor}
        onAutoPlace={onAutoPlace}
        onCrop={onCrop}
        onRemoveFromText={onRemoveFromText}
        onDelete={onDelete}
        canDelete={false}
      />,
    )
    expect(screen.getByText('1 scelto')).toBeInTheDocument()

    // Descrivi è disattivato se canDescribe è false
    const descBtn = screen.getByLabelText(/Descrivi/i)
    expect(descBtn).toHaveAttribute('aria-disabled', 'true')

    // Inserisci al cursore è disabilitato se canInsertAtCursor è false
    const insBtn = screen.getByLabelText(/Inserisci al cursore/i)
    expect(insBtn).toHaveAttribute('aria-disabled', 'true')

    // Ritaglia è attivo con 1 sola immagine
    const cropBtn = screen.getByLabelText(/^Ritaglia$/i)
    expect(cropBtn).not.toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(cropBtn)
    expect(onCrop).toHaveBeenCalled()

    // Togli dal testo è disabilitato se hasUsedSelected è false
    const removeBtn = screen.getByLabelText(/Togli dal testo/i)
    expect(removeBtn).toHaveAttribute('aria-disabled', 'true')

    // Con 2 elementi selezionati, da descrivere, usati e cursore abilitato
    rerender(
      <MediaSelectionBar
        selectedCount={2}
        canDescribe={true}
        hasUsedSelected={true}
        canInsertAtCursor={true}
        onDescribe={onDescribe}
        onInsertAtCursor={onInsertAtCursor}
        onAutoPlace={onAutoPlace}
        onCrop={onCrop}
        onRemoveFromText={onRemoveFromText}
        onDelete={onDelete}
        canDelete={true}
      />,
    )
    expect(screen.getByText('2 scelti')).toBeInTheDocument()

    // Descrivi è attivo se canDescribe è true
    const activeDescBtn = screen.getByLabelText(/^Descrivi$/i)
    expect(activeDescBtn).not.toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(activeDescBtn)
    expect(onDescribe).toHaveBeenCalled()

    // Ritaglia è disattivato con 2 immagini
    const disabledCropBtn = screen.getByTestId('crop-media-button')
    expect(disabledCropBtn).toHaveAttribute('aria-disabled', 'true')

    const activeInsBtn = screen.getByLabelText(/^Inserisci al cursore$/i)
    expect(activeInsBtn).not.toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(activeInsBtn)
    expect(onInsertAtCursor).toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText(/^Posiziona$/i))
    expect(onAutoPlace).toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText(/^Togli dal testo$/i))
    expect(onRemoveFromText).toHaveBeenCalled()

    fireEvent.click(screen.getByLabelText(/^Elimina dalla lezione$/i))
    expect(onDelete).toHaveBeenCalled()
  })

  it('rt-media-select su un gruppo chiuso apre il gruppo, scorre con block: center e aggiunge rt-media-flash', async () => {
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
      />,
    )

    // Chiudi il gruppo Documento1.pdf
    const toggleButton = screen.getByRole('button', { name: /Documento1\.pdf/ })
    fireEvent.click(toggleButton)
    expect(screen.queryByTestId('media-cell-source1-p1.png')).toBeNull()

    // Prepara mock scroll
    const scrollMock = vi.fn()
    window.HTMLElement.prototype.scrollIntoView = scrollMock

    // Invia rt-media-select
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent('rt-media-select', { detail: { name: 'source1-p1.png' } }),
      )
      await new Promise((r) => setTimeout(r, 10))
    })

    const cell = await screen.findByTestId('media-cell-source1-p1.png')
    expect(cell).toBeInTheDocument()
    expect(cell).toHaveClass('rt-media-flash')
    expect(scrollMock).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
  })
})

