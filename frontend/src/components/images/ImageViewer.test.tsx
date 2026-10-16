import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ImageViewer } from './ImageViewer'
import type { ImageItem } from './imageUtils'

describe('ImageViewer', () => {
  const images: ImageItem[] = [
    { src: '/img1.png', alt: 'Doc.pdf, pagina 1', docName: 'Doc.pdf', pageNumber: 1 },
    { src: '/img2.png', alt: 'Doc.pdf, pagina 2', docName: 'Doc.pdf', pageNumber: 2 },
    { src: '/img3.png', alt: 'Doc.pdf, pagina 3', docName: 'Doc.pdf', pageNumber: 3 },
  ]

  it('si apre con l’evento rt-image-viewer-open e mostra didascalia e contatore', () => {
    render(<ImageViewer />)

    expect(screen.queryByRole('dialog', { name: 'Visore immagini' })).toBeNull()

    act(() => {
      window.dispatchEvent(
        new CustomEvent('rt-image-viewer-open', {
          detail: { images, index: 1 },
        })
      )
    })

    const dialog = screen.getByRole('dialog', { name: 'Visore immagini' })
    expect(dialog).toBeInTheDocument()

    expect(screen.getByText('Doc.pdf, pagina 2')).toBeInTheDocument()
    expect(screen.getByText('2 / 3')).toBeInTheDocument()

    const mainImg = dialog.querySelector('.rt-viewer-slide') as HTMLImageElement
    expect(mainImg.src).toContain('/img2.png')
  })

  it('naviga con frecce, tastiera e miniature in basso, e si chiude con Esc o tasto Chiudi', () => {
    render(<ImageViewer />)

    act(() => {
      window.dispatchEvent(
        new CustomEvent('rt-image-viewer-open', {
          detail: { images, index: 0 },
        })
      )
    })

    // Naviga con tasto Successiva
    fireEvent.click(screen.getByRole('button', { name: 'Successiva' }))
    expect(screen.getByText('2 / 3')).toBeInTheDocument()

    // Naviga con tastiera ArrowRight
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByText('3 / 3')).toBeInTheDocument()

    // Naviga con tastiera ArrowLeft
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(screen.getByText('2 / 3')).toBeInTheDocument()

    // Clic su miniatura della prima pagina
    fireEvent.click(screen.getByRole('button', { name: 'Pagina 1' }))
    expect(screen.getByText('1 / 3')).toBeInTheDocument()

    // Chiudi con Esc
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Visore immagini' })).toBeNull()
  })

  it('supporta swipe su mobile per navigare tra le immagini', () => {
    render(<ImageViewer />)

    act(() => {
      window.dispatchEvent(
        new CustomEvent('rt-image-viewer-open', {
          detail: { images, index: 0 },
        })
      )
    })

    const main = screen.getByRole('dialog').querySelector('.rt-vmain')!

    // Swipe verso sinistra (clientX da 200 a 100 -> diff = -100) -> successiva
    fireEvent.touchStart(main, { touches: [{ clientX: 200 }] })
    fireEvent.touchEnd(main, { changedTouches: [{ clientX: 100 }] })
    expect(screen.getByText('2 / 3')).toBeInTheDocument()

    // Swipe verso destra (clientX da 100 a 200 -> diff = +100) -> precedente
    fireEvent.touchStart(main, { touches: [{ clientX: 100 }] })
    fireEvent.touchEnd(main, { changedTouches: [{ clientX: 200 }] })
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
  })
})
