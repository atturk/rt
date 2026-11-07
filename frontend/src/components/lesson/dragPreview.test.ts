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

  it('startDragPreview aggiunge l\'anteprima al body spostata di circa 18px dal cursore', () => {
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
})
