import { useCallback, useEffect, useRef, useState, type TouchEvent } from 'react'
import type { ImageItem } from './imageUtils'

export function ImageViewer() {
  const [state, setState] = useState<{ images: ImageItem[]; index: number } | null>(null)
  const touchStartX = useRef<number | null>(null)

  const close = useCallback(() => {
    setState(null)
  }, [])

  const setIndex = useCallback((nextIndex: number) => {
    setState((prev) => {
      if (!prev) return null
      const n = prev.images.length
      const idx = (nextIndex + n) % n
      return { images: prev.images, index: idx }
    })
  }, [])

  useEffect(() => {
    const onOpen = (e: Event) => {
      const custom = e as CustomEvent<{ images: ImageItem[]; index: number }>
      if (custom.detail && custom.detail.images?.length) {
        setState({
          images: custom.detail.images,
          index: custom.detail.index || 0,
        })
      }
    }
    window.addEventListener('rt-image-viewer-open', onOpen)
    return () => window.removeEventListener('rt-image-viewer-open', onOpen)
  }, [])

  useEffect(() => {
    if (!state) return

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        close()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setIndex(state.index - 1)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        setIndex(state.index + 1)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [state, close, setIndex])

  const onTouchStart = (e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX
  }

  const onTouchEnd = (e: TouchEvent) => {
    if (touchStartX.current === null) return
    const diff = e.changedTouches[0].clientX - touchStartX.current
    touchStartX.current = null
    const threshold = 50
    if (diff > threshold) {
      // Swipe verso destra -> precedente
      if (state) setIndex(state.index - 1)
    } else if (diff < -threshold) {
      // Swipe verso sinistra -> successiva
      if (state) setIndex(state.index + 1)
    }
  }

  if (!state || state.images.length === 0) return null

  const current = state.images[state.index]
  const count = state.images.length
  const caption = current.docName
    ? `${current.docName}${current.pageNumber !== undefined ? `, pagina ${current.pageNumber}` : ''}`
    : current.alt || 'Immagine'

  return (
    <div
      className="rt-viewer-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Visore immagini"
      onClick={(e) => {
        if (e.target === e.currentTarget) close()
      }}
    >
      <div className="rt-viewer-box">
        <div className="rt-vtop">
          <span className="cap" title={caption}>{caption}</span>
          <span className="count">{state.index + 1} / {count}</span>
          <button
            type="button"
            className="vb"
            aria-label="Chiudi"
            onClick={close}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div
          className="rt-vmain"
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          <button
            type="button"
            className="vb"
            aria-label="Precedente"
            onClick={() => setIndex(state.index - 1)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>

          <div className="rt-slide-wrapper">
            <img
              src={current.src}
              alt={current.alt}
              className="rt-viewer-slide"
            />
          </div>

          <button
            type="button"
            className="vb"
            aria-label="Successiva"
            onClick={() => setIndex(state.index + 1)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="m9 18 6-6-6-6" />
            </svg>
          </button>
        </div>

        <div className="rt-vstrip">
          {state.images.map((img, idx) => {
            const pageLabel = img.pageNumber !== undefined ? `Pagina ${img.pageNumber}` : `Immagine ${idx + 1}`
            return (
              <button
                key={idx}
                type="button"
                className={idx === state.index ? 'on' : ''}
                aria-label={pageLabel}
                onClick={() => setIndex(idx)}
              >
                <img src={img.src} alt={img.alt} loading="lazy" />
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
