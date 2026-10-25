import { type EditorState, type Extension, type Range, StateEffect, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, WidgetType } from '@codemirror/view'
import { buildImageStripDOM, buildUnitImagesButton } from '@/components/images/imageStripDOM'
import { unmountDomTooltip } from '@/components/ui/dom-tooltip'
import { parseImageAlt, type ImageItem } from '@/components/images/imageUtils'
import { imageSections } from './imageSections'

export const toggleUnitImages = StateEffect.define<string>()
const openUnitImages = StateField.define<ReadonlySet<string>>({
  create: () => new Set(),
  update(value, tr) {
    for (const effect of tr.effects) {
      if (effect.is(toggleUnitImages)) {
        const next = new Set(value)
        if (next.has(effect.value)) next.delete(effect.value)
        else next.add(effect.value)
        value = next
      }
    }
    return value
  },
})

class UnitImagesButton extends WidgetType {
  readonly unitId: string
  readonly count: number
  readonly open: boolean
  readonly below: boolean
  constructor(unitId: string, count: number, open: boolean, below = false) {
    super(); this.unitId = unitId; this.count = count; this.open = open; this.below = below
  }
  eq(other: UnitImagesButton) {
    return this.unitId === other.unitId && this.count === other.count && this.open === other.open && this.below === other.below
  }
  toDOM(view: EditorView) {
    const button = buildUnitImagesButton(this.unitId, this.count, this.open, () => view.dispatch({ effects: toggleUnitImages.of(this.unitId) }))
    if (!this.below) return button
    const row = document.createElement('div')
    row.className = 'rt-unit-images-row'
    row.classList.toggle('empty', this.count === 0)
    row.append(button)
    return row
  }
  destroy(dom: HTMLElement) { unmountDomTooltip(dom.matches('button') ? dom : dom.querySelector('button') ?? dom) }
  ignoreEvent(event: Event) { return !['drop', 'dragover', 'dragenter', 'dragleave', 'dragend'].includes(event.type) }
}

class ImageStripWidget extends WidgetType {
  readonly unitId: string
  readonly images: ImageItem[]
  readonly open: boolean
  constructor(unitId: string, images: ImageItem[], open: boolean) { super(); this.unitId = unitId; this.images = images; this.open = open }
  eq(other: ImageStripWidget) {
    return this.unitId === other.unitId && this.open === other.open && JSON.stringify(this.images) === JSON.stringify(other.images)
  }
  toDOM() {
    const section = document.createElement('div')
    section.dataset.unitImages = this.unitId
    section.className = 'rt-unit-images-section'
    if (this.open) section.append(buildImageStripDOM(this.images, { fromUnit: this.unitId }))
    else section.classList.add('closed')
    return section
  }
  ignoreEvent(event: Event) { return !['drop', 'dragover', 'dragenter', 'dragleave', 'dragend'].includes(event.type) }
}

export function findMarkdownImageStrips(state: EditorState, lessonId: number) {
  return imageSections(state).filter(section => section.images.length).map(section => ({
    unitId: section.id,
    from: section.images[0].from,
    to: section.images.at(-1)!.to,
    startLine: section.images[0].line,
    endLine: section.images.at(-1)!.line,
    images: section.images.map(image => ({
      src: `/api/v1/lessons/${lessonId}/assets/images/${encodeURIComponent(image.name)}`,
      alt: image.alt,
      ...parseImageAlt(image.alt),
    })),
  }))
}

/** Le righe della sezione sono atomiche; apertura e chiusura non modificano il Markdown. */
export function lessonImageStrips(lessonId: number): Extension {
  const build = (state: EditorState): DecorationSet => {
    const ranges: Range<Decoration>[] = []
    const open = state.field(openUnitImages)
    for (const section of imageSections(state)) {
      // Senza timecode (le sezioni, ## N.) il bottone sta in una riga sotto il titolo.
      const below = section.timecode === state.doc.lineAt(section.from).to
      const widget = new UnitImagesButton(section.id, section.images.length, open.has(section.id), below)
      ranges.push((below ? Decoration.widget({ widget, block: true, side: 1 }) : Decoration.widget({ widget, side: -1 })).range(section.timecode))
    }
    for (const strip of findMarkdownImageStrips(state, lessonId)) {
      ranges.push(Decoration.replace({ widget: new ImageStripWidget(strip.unitId, strip.images, open.has(strip.unitId)), block: true }).range(strip.from, strip.to))
    }
    return Decoration.set(ranges, true)
  }
  const strips = StateField.define<DecorationSet>({
    create: build,
    update: (value, tr) => tr.docChanged || tr.effects.some(effect => effect.is(toggleUnitImages)) ? build(tr.state) : value,
    provide: field => [EditorView.decorations.from(field), EditorView.atomicRanges.of(view => view.state.field(field))],
  })
  return [openUnitImages, strips]
}
