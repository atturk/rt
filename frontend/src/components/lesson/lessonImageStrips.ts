import { type EditorState, type Extension, type Range, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, WidgetType } from '@codemirror/view'
import { buildImageStripDOM, MIN_STRIP_IMAGES } from '@/components/images/imageStripDOM'
import { parseImageAlt, type ImageItem } from '@/components/images/imageUtils'

const MARKDOWN_IMAGE_LINE_RE = /^!\[(.*)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)\)\s*$/

class ImageStripWidget extends WidgetType {
  readonly images: ImageItem[]

  constructor(images: ImageItem[]) {
    super()
    this.images = images
  }

  eq(other: ImageStripWidget) {
    if (other.images.length !== this.images.length) return false
    return this.images.every((img, i) => img.src === other.images[i].src && img.alt === other.images[i].alt)
  }

  toDOM() {
    return buildImageStripDOM(this.images)
  }

  ignoreEvent() {
    return true
  }
}

type StripRange = {
  from: number
  to: number
  startLine: number
  endLine: number
  images: ImageItem[]
}

export function findMarkdownImageStrips(state: EditorState, lessonId: number): StripRange[] {
  const strips: StripRange[] = []
  const doc = state.doc
  let currentImages: ImageItem[] = []
  let stripStartLine = -1
  let stripEndLine = -1

  for (let n = 1; n <= doc.lines; n++) {
    const line = doc.line(n)
    const text = line.text.trim()
    const match = MARKDOWN_IMAGE_LINE_RE.exec(text)

    if (match) {
      if (currentImages.length === 0) {
        stripStartLine = n
      }
      stripEndLine = n
      const alt = match[1]
      const filename = match[2]
      const { docName, pageNumber } = parseImageAlt(alt)
      currentImages.push({
        src: `/api/v1/lessons/${lessonId}/assets/images/${encodeURIComponent(filename)}`,
        alt,
        docName,
        pageNumber,
      })
    } else if (text === '') {
      // Linea vuota tra immagini: continua a raccogliere
      continue
    } else {
      // Testo ordinario: chiude l'eventuale striscia
      if (currentImages.length >= MIN_STRIP_IMAGES && stripStartLine > 0 && stripEndLine > 0) {
        strips.push({
          from: doc.line(stripStartLine).from,
          to: doc.line(stripEndLine).to,
          startLine: stripStartLine,
          endLine: stripEndLine,
          images: currentImages,
        })
      }
      currentImages = []
      stripStartLine = -1
      stripEndLine = -1
    }
  }

  if (currentImages.length >= MIN_STRIP_IMAGES && stripStartLine > 0 && stripEndLine > 0) {
    strips.push({
      from: doc.line(stripStartLine).from,
      to: doc.line(stripEndLine).to,
      startLine: stripStartLine,
      endLine: stripEndLine,
      images: currentImages,
    })
  }

  return strips
}

/**
 * Estensione CodeMirror per la gestione delle immagini in striscia di miniature:
 * - Immagini singole o serie consecutive formano una striscia (~90px)
 * - Con cursore fuori dalla striscia: rimpiazzo visivo con la striscia di miniature
 * - Con cursore dentro la striscia: compaiono le righe markdown per la modifica
 */
export function lessonImageStrips(lessonId: number): Extension {
  const build = (state: EditorState): DecorationSet => {
    const strips = findMarkdownImageStrips(state, lessonId)
    const ranges: Range<Decoration>[] = []

    for (const strip of strips) {
      // Verifica se il cursore (o la selezione) si trova dentro l'intervallo della striscia
      const hasCursor = state.selection.ranges.some((r) => r.from <= strip.to && r.to >= strip.from)

      if (hasCursor) {
        // Cursore dentro: mostra le righe markdown, nascondendo blocchi singoli atomici
        for (let n = strip.startLine; n <= strip.endLine; n++) {
          ranges.push(Decoration.line({ class: 'rt-strip-editing-line' }).range(state.doc.line(n).from))
        }
      } else {
        // Cursore fuori: rimpiazza l'intero blocco delle immagini con la striscia
        ranges.push(
          Decoration.replace({
            widget: new ImageStripWidget(strip.images),
            block: true,
          }).range(strip.from, strip.to)
        )
      }
    }

    return Decoration.set(ranges, true)
  }

  const stripsField = StateField.define<DecorationSet>({
    create: build,
    update: (value, tr) => (tr.docChanged || tr.selection ? build(tr.state) : value),
    provide: (field) => EditorView.decorations.from(field),
  })

  return [stripsField]
}
