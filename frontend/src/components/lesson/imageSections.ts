import type { EditorState } from '@codemirror/state'

export const SECTION_IMAGE_RE = /^!\[(.*)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)\)\s*$/
export const TIMECODE_RE = /^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*$/
export const RT_SECTION_IMAGE_DRAG_TYPE = 'application/x-rt-section-image'
export type SectionImageDrag = { name: string; fromUnit?: string; fromText?: number; width?: number }
export type SectionImage = { from: number; to: number; line: number; name: string; alt: string }
export type ImageSection = { id: string; from: number; to: number; timecode: number; insertAt: number; images: SectionImage[] }

/** Stessa distinzione del parser Python: solo immagini prima del testo e senza #w=; nelle unità dopo il timecode. */
export function imageSections(state: EditorState): ImageSection[] {
  const sections: ImageSection[] = []
  let current: ImageSection | null = null
  let leading = false
  let timed = false
  for (let n = 1; n <= state.doc.lines; n++) {
    const line = state.doc.line(n)
    if (/^(#\s|##\s+\d+\.\s|###\s+\d+(\.\d+)+\.?\s)/.test(line.text)) {
      if (current) current.to = line.from
      const heading = /^###\s+(\d+(?:\.\d+)+)\.?\s/.exec(line.text)
      // Anche le sezioni (## N.) hanno le loro immagini, subito sotto il titolo e senza timecode.
      const macro = /^##\s+(\d+)\.\s/.exec(line.text)
      const id = heading?.[1] ?? macro?.[1]
      current = id ? { id, from: line.from, to: state.doc.length, timecode: line.to, insertAt: line.to, images: [] } : null
      if (current) sections.push(current)
      leading = true
      timed = Boolean(macro)
      continue
    }
    if (!current || !leading || !line.text.trim()) continue
    if (!timed && TIMECODE_RE.test(line.text)) {
      current.timecode = line.from
      current.insertAt = line.to
      timed = true
      continue
    }
    const image = timed && SECTION_IMAGE_RE.exec(line.text.trim())
    if (image) {
      current.images.push({ from: line.from, to: line.to, line: n, name: image[2], alt: image[1] })
      current.insertAt = line.to
    } else leading = false
  }
  return sections
}
