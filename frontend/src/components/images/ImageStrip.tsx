import { useEffect, useRef } from 'react'
import { buildImageStripDOM } from './imageStripDOM'
import type { ImageItem } from './imageUtils'

export type ImageStripProps = { images: ImageItem[]; lessonId?: number; onImageClick?: (index: number) => void }

/** Rail condivisa; l'apertura appartiene alla singola sottounità. */
export function ImageStrip({ images, onImageClick }: ImageStripProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const root = ref.current
    if (!root) return
    const strip = buildImageStripDOM(images, { onImageClick })
    root.append(strip)
    return () => strip.remove()
  }, [images, onImageClick])
  return <div ref={ref} />
}
