import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { usePreference } from '@/lib/preferences'
import { Tooltip } from '@/components/ui/tooltip'
import {
  formatStripLabel,
  setStripClosedPreference,
  type ImageItem,
} from './imageUtils'

export type ImageStripProps = {
  images: ImageItem[]
  lessonId?: number
  onImageClick?: (index: number) => void
}

export function ImageStrip({ images, onImageClick }: ImageStripProps) {
  const [closed, setClosed] = usePreference('strip_closed', false)
  const thumbsRef = useRef<HTMLDivElement>(null)
  const [scrollEdges, setScrollEdges] = useState({ left: false, right: false })

  const { countPill, docLabel } = formatStripLabel(images)

  const checkEdges = () => {
    const el = thumbsRef.current
    if (!el) return
    setScrollEdges({
      left: el.scrollLeft > 2,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 2,
    })
  }

  useEffect(() => {
    checkEdges()
    const el = thumbsRef.current
    if (!el) return
    el.addEventListener('scroll', checkEdges, { passive: true })
    window.addEventListener('resize', checkEdges)
    const t = setTimeout(checkEdges, 100)
    return () => {
      el.removeEventListener('scroll', checkEdges)
      window.removeEventListener('resize', checkEdges)
      clearTimeout(t)
    }
  }, [images, closed])

  const scrollBy = (amount: number) => {
    thumbsRef.current?.scrollBy({ left: amount, behavior: 'smooth' })
  }

  const toggleClosed = (e: MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const next = !closed
    setClosed(next)
    setStripClosedPreference(next)
  }

  return (
    <div className={`rt-strip ${closed ? 'closed' : ''}`} data-n={images.length}>
      <div className="rt-strip-head">
        <Tooltip content={closed ? 'Mostra le immagini' : 'Chiudi le immagini'}>
          {(trigger) => (
            <button
              {...trigger}
              type="button"
              className="ib tg"
              aria-expanded={!closed}
              aria-label={closed ? 'Mostra le immagini' : 'Chiudi le immagini'}
              onClick={toggleClosed}
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                className="chev"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
          )}
        </Tooltip>
        <span className="rt-strip-icon">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className="rt-strip-clip"
          >
            <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </span>
        <span className="name">
          <span className="count-pill">{countPill}</span> · {docLabel}
        </span>
      </div>

      <div className={`rail ${scrollEdges.left ? 'l' : ''} ${scrollEdges.right ? 'r' : ''}`}>
        <button
          type="button"
          className={`nav prev ${scrollEdges.left ? 'show' : ''}`}
          aria-label="Scorri a sinistra"
          onClick={() => scrollBy(-(thumbsRef.current?.clientWidth ?? 200) * 0.8)}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>

        <div className="thumbs" ref={thumbsRef}>
          {images.map((img, idx) => {
            const pageLabel = img.pageNumber !== undefined ? `pagina ${img.pageNumber}` : `${idx + 1}`
            return (
              <button
                key={idx}
                type="button"
                className="thumb"
                aria-label={`Apri ${pageLabel}`}
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onImageClick?.(idx)
                  window.dispatchEvent(
                    new CustomEvent('rt-image-viewer-open', {
                      detail: { images, index: idx },
                    })
                  )
                }}
              >
                <img src={img.src} alt={img.alt} loading="lazy" />
                {img.pageNumber !== undefined && <span className="pg">p. {img.pageNumber}</span>}
              </button>
            )
          })}
        </div>

        <button
          type="button"
          className={`nav next ${scrollEdges.right ? 'show' : ''}`}
          aria-label="Scorri a destra"
          onClick={() => scrollBy((thumbsRef.current?.clientWidth ?? 200) * 0.8)}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m9 18 6-6-6-6" />
          </svg>
        </button>
      </div>
    </div>
  )
}
