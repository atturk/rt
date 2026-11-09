import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  createDragPreviewDOM,
  startDragPreview,
  stopDragPreview,
} from './dragPreview'

describe('dragPreview', () => {
  beforeEach(() => {
    stopDragPreview()
  })

  afterEach(() => {
    stopDragPreview()
  })

  it('crea anteprima singola piccola con larghezza circa 68px e angoli arrotondati', () => {
    const el = createDragPreviewDOM({ urls: ['/img1.png'] })
    expect(el.className).toBe('rt-drag-preview')
    expect(el.style.width).toBe('68px')
    expect(el.style.borderRadius).toBe('8px')
    expect(el.style.pointerEvents).toBe('none')
    const img = el.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.src).toContain('img1.png')
  })

  it('startDragPreview aggiunge l\'anteprima al body in basso a destra del cursore', () => {
    const setDragImage = vi.fn()
    const mockEvent = {
      clientX: 100,
      clientY: 200,
      dataTransfer: {
        setDragImage,
      },
    } as unknown as DragEvent

    const preview = startDragPreview(mockEvent, { urls: ['/test.png'] })
    expect(preview).not.toBeNull()
    expect(document.querySelector('.rt-drag-preview')).toBe(preview)
    expect(preview?.style.left).toBe('118px')
    expect(preview?.style.top).toBe('218px')
    expect(setDragImage).toHaveBeenCalled()
  })

  it('aggiorna la posizione su dragover e pulisce su dragend', () => {
    const mockEvent = {
      clientX: 50,
      clientY: 60,
    } as unknown as DragEvent

    const preview = startDragPreview(mockEvent, { urls: ['/test.png'] })
    expect(preview?.style.left).toBe('68px')
    expect(preview?.style.top).toBe('78px')

    // Dispatcia dragover
    const dragOverEvt = new MouseEvent('dragover', {
      bubbles: true,
      clientX: 150,
      clientY: 250,
    } as any)
    window.dispatchEvent(dragOverEvt)

    expect(preview?.style.left).toBe('168px')
    expect(preview?.style.top).toBe('268px')

    // Dispatcia dragend
    const dragEndEvt = new Event('dragend', { bubbles: true })
    window.dispatchEvent(dragEndEvt)

    expect(document.querySelector('.rt-drag-preview')).toBeNull()
  })

  it('posizione aggiornata anche con dragover su un elemento non di rilascio e coordinate (0, 0) preservano l\'ultima posizione', () => {
    const header = document.createElement('header')
    header.className = 'rt-header'
    document.body.appendChild(header)

    const mockEvent = {
      clientX: 50,
      clientY: 60,
    } as unknown as DragEvent

    const preview = startDragPreview(mockEvent, { urls: ['/test.png'] })
    expect(preview?.style.left).toBe('68px')
    expect(preview?.style.top).toBe('78px')

    // Dragover sull'header (zona non di rilascio)
    const dragOverHeader = new MouseEvent('dragover', {
      bubbles: true,
      cancelable: true,
      clientX: 200,
      clientY: 300,
    }) as any
    Object.defineProperty(dragOverHeader, 'dataTransfer', {
      value: { dropEffect: 'none' },
      writable: true,
    })
    header.dispatchEvent(dragOverHeader)

    expect(preview?.style.left).toBe('218px')
    expect(preview?.style.top).toBe('318px')

    // Coordinate (0, 0) tipiche del glitch WebKit fuori zona di rilascio: mantengono l'ultima valida
    const zeroEvt = new MouseEvent('dragover', {
      bubbles: true,
      cancelable: true,
      clientX: 0,
      clientY: 0,
    }) as any
    header.dispatchEvent(zeroEvt)

    expect(preview?.style.left).toBe('218px')
    expect(preview?.style.top).toBe('318px')

    document.body.removeChild(header)
  })

  it('segno di divieto presente nelle zone non valide e poi tolto tornando in una zona valida', () => {
    const header = document.createElement('header')
    document.body.appendChild(header)

    const dropTarget = document.createElement('div')
    dropTarget.className = 'cm-editor'
    dropTarget.addEventListener('dragover', (e) => {
      e.preventDefault()
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = 'copy'
      }
    })
    document.body.appendChild(dropTarget)

    const mockEvent = {
      clientX: 50,
      clientY: 60,
    } as unknown as DragEvent

    const preview = startDragPreview(mockEvent, { urls: ['/test.png'] })

    // All'inizio sopra l'origine (non valida) o sull'header
    const dragOverHeader = new MouseEvent('dragover', {
      bubbles: true,
      cancelable: true,
      clientX: 100,
      clientY: 100,
    }) as any
    const dataTransferNonDrop = { dropEffect: 'none' }
    Object.defineProperty(dragOverHeader, 'dataTransfer', {
      value: dataTransferNonDrop,
      writable: true,
    })
    header.dispatchEvent(dragOverHeader)

    // Segno di divieto (icona Ban di lucide in cerchio rosso) presente
    expect(preview?.querySelector('.rt-drag-preview-ban')).not.toBeNull()
    expect(preview?.querySelector('.lucide-ban')).not.toBeNull()
    expect(dataTransferNonDrop.dropEffect).toBe('none')

    // Spostamento nella zona valida (editor): dropEffect diventa copy e il segno di divieto sparisce
    const dragOverDrop = new MouseEvent('dragover', {
      bubbles: true,
      cancelable: true,
      clientX: 150,
      clientY: 200,
    }) as any
    const dataTransferDrop = { dropEffect: 'none' }
    Object.defineProperty(dragOverDrop, 'dataTransfer', {
      value: dataTransferDrop,
      writable: true,
    })
    dropTarget.dispatchEvent(dragOverDrop)

    expect(dataTransferDrop.dropEffect).toBe('copy')
    expect(preview?.querySelector('.rt-drag-preview-ban')).toBeNull()

    // Ritorno sull'header: il divieto ricompare
    header.dispatchEvent(dragOverHeader)
    expect(preview?.querySelector('.rt-drag-preview-ban')).not.toBeNull()

    document.body.removeChild(header)
    document.body.removeChild(dropTarget)
  })

  it('drop fuori zona senza effetti: previene azione nativa e rimuove l\'anteprima', () => {
    const sidebar = document.createElement('aside')
    document.body.appendChild(sidebar)

    const mockEvent = {
      clientX: 50,
      clientY: 60,
    } as unknown as DragEvent

    const preview = startDragPreview(mockEvent, { urls: ['/test.png'] })
    expect(document.querySelector('.rt-drag-preview')).toBe(preview)

    // Drop sulla sidebar (zona non valida)
    const dropEvt = new MouseEvent('drop', {
      bubbles: true,
      cancelable: true,
      clientX: 80,
      clientY: 120,
    }) as any
    Object.defineProperty(dropEvt, 'dataTransfer', {
      value: { dropEffect: 'none' },
    })
    sidebar.dispatchEvent(dropEvt)

    // L'azione di drop non valida viene interrotta e l'anteprima ripulita
    expect(dropEvt.defaultPrevented).toBe(true)
    expect(document.querySelector('.rt-drag-preview')).toBeNull()

    document.body.removeChild(sidebar)
  })

  it('trascinamento multiplo dal pannello Media: badge e divieto convivono senza sovrapporsi', () => {
    const header = document.createElement('header')
    document.body.appendChild(header)

    const mockEvent = {
      clientX: 40,
      clientY: 50,
    } as unknown as DragEvent

    const preview = startDragPreview(mockEvent, {
      urls: ['/a.png', '/b.png', '/c.png'],
      count: 3,
    })

    // Mostra il badge con 3
    const badge = preview?.querySelector('.rt-drag-preview-badge')
    expect(badge?.textContent).toBe('3')

    // Dragover sulla zona non valida: divieto a sinistra, badge a destra
    const dragOverHeader = new MouseEvent('dragover', {
      bubbles: true,
      cancelable: true,
      clientX: 120,
      clientY: 140,
    }) as any
    Object.defineProperty(dragOverHeader, 'dataTransfer', {
      value: { dropEffect: 'none' },
    })
    header.dispatchEvent(dragOverHeader)

    const ban = preview?.querySelector('.rt-drag-preview-ban') as HTMLElement
    expect(ban).not.toBeNull()
    expect(ban?.style.left).toBe('-6px')
    expect(badge).not.toBeNull()

    // Rilascio fuori zona rimuove tutto
    const dropEvt = new MouseEvent('drop', {
      bubbles: true,
      cancelable: true,
    }) as any
    header.dispatchEvent(dropEvt)
    expect(document.querySelector('.rt-drag-preview')).toBeNull()

    document.body.removeChild(header)
  })
})
