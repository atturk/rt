import { type EditorState, type Extension, type Range, StateEffect, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, ViewPlugin, WidgetType } from '@codemirror/view'
import type { UnitTask } from './lessonWorkflow'
import { findMarkdownImageStrips } from './lessonImageStrips'
import { parseImageAlt, type ImageItem } from '@/components/images/imageUtils'
import { isEnrichmentPanelOpen } from '@/components/shell/globalFileDropUtils'
import { imageSections, RT_SECTION_IMAGE_DRAG_TYPE } from './imageSections'

/**
 * Le unità nel Markdown dell'editor della lezione: dal titolo `### 1.1 Titolo` fino al titolo
 * successivo (##/###). Servono a mettere in fondo a ciascuna il riquadro dell'arricchimento
 * (elementi DOM di React, passati con setSlots).
 */

const UNIT_RE = /^###\s+(\S+)\s/
// Solo i titoli numerati di RT ("## 2. …", "### 2.1 …") e l'H1 chiudono un'unità: un titolo senza numero
// scritto dentro un'unità ("### Approfondimento") è testo dell'unità, come per il server.
const HEADING_RE = /^(#\s|##\s+\d+\.\s|###\s+\d+(\.\d+)+\.?\s)/

export type UnitRange = { id: string; from: number; to: number; endLine: number }

export function unitRanges(state: EditorState): UnitRange[] {
  const out: UnitRange[] = []
  let open: UnitRange | null = null
  const close = (lineNo: number) => {
    if (!open) return
    // senza le righe vuote in fondo
    let end = lineNo
    while (end > state.doc.lineAt(open.from).number && !state.doc.line(end).text.trim()) end--
    open.endLine = end
    open.to = state.doc.line(end).to
    out.push(open)
    open = null
  }
  for (let n = 1; n <= state.doc.lines; n++) {
    const line = state.doc.line(n)
    if (!HEADING_RE.test(line.text)) continue
    close(n - 1)
    const m = UNIT_RE.exec(line.text + ' ')
    if (m && line.text.startsWith('### ')) open = { id: m[1], from: line.from, to: line.to, endLine: n }
  }
  close(state.doc.lines)
  return out
}

export const setSlots = StateEffect.define<Record<string, HTMLElement>>()
export const setUnitTasks = StateEffect.define<Record<string, { state: UnitTask; element: HTMLElement }>>()
export const setLinkedUnit = StateEffect.define<string | null>()

class SlotWidget extends WidgetType {
  readonly element: HTMLElement
  constructor(element: HTMLElement) {
    super()
    this.element = element
  }
  eq(other: SlotWidget) {
    return other.element === this.element
  }
  // Lo stesso elemento a ogni ridisegno: React ci tiene dentro il suo portal.
  toDOM() {
    return this.element
  }
  ignoreEvent() {
    return true
  }
  destroy() {}
}

class PendingUnit extends WidgetType {
  toDOM() {
    const node = document.createElement('div')
    node.className = 'rt-unit-pending'
    node.setAttribute('aria-hidden', 'true')
    for (let i = 0; i < 3; i++) node.append(document.createElement('div'))
    return node
  }
}

type UnitsState = { slots: Record<string, HTMLElement>; tasks: Record<string, { state: UnitTask; element: HTMLElement }>; linked: string | null; decorations: DecorationSet }

function build(state: EditorState, slots: UnitsState['slots'], tasks: UnitsState['tasks'], linked: string | null): UnitsState {
  const ranges: Range<Decoration>[] = []
  for (const unit of unitRanges(state)) {
    // come le intestazioni della lettura: ci si arriva con [data-unit-id]
    const task = tasks[unit.id]
    const className = [task?.state === 'waiting' && 'rt-unit-waiting', linked === unit.id && 'rt-claim-unit'].filter(Boolean).join(' ')
    ranges.push(Decoration.line({ attributes: { 'data-unit-id': unit.id, ...(task ? { 'data-task': task.state } : {}) }, class: className }).range(unit.from))
    if (task) {
      ranges.push(Decoration.widget({ widget: new SlotWidget(task.element), side: -1 }).range(unit.from))
      if (task.state === 'working') ranges.push(Decoration.widget({ widget: new PendingUnit(), block: true, side: 1 }).range(unit.to))
    }
    const slot = slots[unit.id]
    if (slot) ranges.push(Decoration.widget({ widget: new SlotWidget(slot), block: true, side: 1 }).range(unit.to))
  }
  return { slots, tasks, linked, decorations: Decoration.set(ranges, true) }
}

const unitsField = StateField.define<UnitsState>({
  create: (state) => build(state, {}, {}, null),
  update(value, tr) {
    let { slots, tasks, linked } = value
    for (const effect of tr.effects) {
      if (effect.is(setSlots)) slots = effect.value
      if (effect.is(setUnitTasks)) tasks = effect.value
      if (effect.is(setLinkedUnit)) linked = effect.value
    }
    if (!tr.docChanged && slots === value.slots && tasks === value.tasks && linked === value.linked) return value
    return build(tr.state, slots, tasks, linked)
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.decorations),
})

export const lessonUnits: Extension = unitsField

const LOCAL_IMAGE_RE = /^!\[(.*)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#w=(\d+))?\)\s*$/
// Quelle che atomic-editor disegna da sé (didascalia senza parentesi quadre).
const ATOMIC_IMAGE_RE = /^!\[([^\]]*)\]\(([^\s)"']+)(?:\s+["'][^)]*["'])?\)$/

const imageUrl = (lessonId: number, name: string) => `/api/v1/lessons/${lessonId}/assets/images/${encodeURIComponent(name)}`

function handleImageClick(view: EditorView, lessonId: number, img: HTMLImageElement, name: string) {
  if (isEnrichmentPanelOpen()) {
    window.dispatchEvent(new CustomEvent('rt-media-select', { detail: { name } }))
  } else {
    const allImages: ImageItem[] = []
    let activeIdx = 0
    const docText = view.state.doc.toString()
    const imgRe = /!\[(.*?)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#[^)]*)?\)/g
    let match: RegExpExecArray | null
    while ((match = imgRe.exec(docText)) !== null) {
      const imgAlt = match[1]
      const imgName = match[2]
      const { docName, pageNumber } = parseImageAlt(imgAlt)
      if (imgName === name && activeIdx === 0 && allImages.length > 0) {
        activeIdx = allImages.length
      }
      allImages.push({
        src: imageUrl(lessonId, imgName),
        alt: imgAlt,
        docName,
        pageNumber,
      })
    }
    if (allImages.length === 0) {
      allImages.push({
        src: img.src,
        alt: img.alt,
        docName: parseImageAlt(img.alt).docName,
      })
    }
    window.dispatchEvent(
      new CustomEvent('rt-image-viewer-open', {
        detail: { images: allImages, index: activeIdx },
      }),
    )
  }
}

function attachResizeHandles(view: EditorView, img: HTMLImageElement, name: string) {
  img.draggable = true
  img.ondragstart = event => {
    const sections = imageSections(view.state)
    const source = Array.from({ length: view.state.doc.lines }, (_, i) => view.state.doc.line(i + 1)).find(line =>
      new RegExp(`^!\\[.*\\]\\((?:\\.\\/)?assets/images/${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:#w=\\d+)?\\)\\s*$`).test(line.text) &&
      !sections.some(section => section.images.some(image => image.from === line.from)))
    if (!source || view.state.readOnly) { event.preventDefault(); return }
    event.stopPropagation()
    event.dataTransfer?.setData(RT_SECTION_IMAGE_DRAG_TYPE, JSON.stringify({ name, fromText: source.from, width: img.naturalWidth || 480 }))
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
    view.dom.classList.add('rt-dragging-images')
  }
  const wrap = img.parentElement
  if (!wrap) return

  const existingLeft = wrap.querySelector('.rt-image-resize-handle-left')
  const existingRight = wrap.querySelector('.rt-image-resize-handle-right')

  if (existingLeft && existingRight) return

  wrap.style.position = 'relative'
  wrap.style.display = 'inline-block'
  wrap.style.maxWidth = '100%'

  const makeHandle = (side: 'left' | 'right') => {
    const handle = document.createElement('div')
    handle.className = `rt-image-resize-handle rt-image-resize-handle-${side}`
    handle.style.position = 'absolute'
    handle.style.bottom = '4px'
    handle.style[side] = '4px'
    handle.style.width = '12px'
    handle.style.height = '12px'
    handle.style.backgroundColor = '#3b82f6'
    handle.style.borderRadius = '2px'
    handle.style.cursor = 'ew-resize'
    handle.style.zIndex = '10'

    handle.addEventListener('pointerdown', (e) => {
      e.preventDefault()
      e.stopPropagation()
      const startX = e.clientX
      const startWidth = img.getBoundingClientRect().width || img.clientWidth || 300
      const maxWidth = view.contentDOM.clientWidth || 800

      const onPointerMove = (moveEvt: PointerEvent) => {
        moveEvt.preventDefault()
        const delta = moveEvt.clientX - startX
        const nextWidth = Math.round(
          Math.min(maxWidth, Math.max(120, side === 'right' ? startWidth + delta : startWidth - delta)),
        )
        img.style.width = `${nextWidth}px`
      }

      const onPointerUp = (upEvt: PointerEvent) => {
        upEvt.preventDefault()
        window.removeEventListener('pointermove', onPointerMove)
        window.removeEventListener('pointerup', onPointerUp)

        const finalWidth = parseInt(img.style.width, 10)
        if (isNaN(finalWidth)) return

        const doc = view.state.doc
        const escName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        const regex = new RegExp(`(!\\[.*?\\]\\((?:\\.\\/)?assets\\/images\\/${escName})(?:#[^)]*)?(\\))`)
        for (let n = 1; n <= doc.lines; n++) {
          const line = doc.line(n)
          const match = regex.exec(line.text)
          if (match) {
            const from = line.from + match.index
            const to = from + match[0].length
            const insert = `${match[1]}#w=${finalWidth}${match[2]}`
            view.dispatch({ changes: { from, to, insert } })
            break
          }
        }
      }

      window.addEventListener('pointermove', onPointerMove)
      window.addEventListener('pointerup', onPointerUp)
    })

    return handle
  }

  wrap.appendChild(makeHandle('left'))
  wrap.appendChild(makeHandle('right'))
}

class LessonImageWidget extends WidgetType {
  readonly src: string
  readonly alt: string
  readonly name: string
  readonly width?: number
  readonly lessonId: number

  constructor(src: string, alt: string, name: string, width: number | undefined, lessonId: number) {
    super()
    this.src = src
    this.alt = alt
    this.name = name
    this.width = width
    this.lessonId = lessonId
  }
  eq(other: LessonImageWidget) {
    return other.src === this.src && other.alt === this.alt && other.width === this.width
  }
  toDOM(view: EditorView) {
    const wrap = document.createElement('div')
    wrap.className = 'rt-editor-image'
    wrap.style.position = 'relative'
    wrap.style.display = 'inline-block'
    wrap.style.maxWidth = '100%'

    const img = document.createElement('img')
    img.src = this.src
    img.alt = this.alt
    img.dataset.imageName = this.name
    if (this.width) img.style.width = `${this.width}px`
    img.style.maxWidth = '100%'

    img.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      handleImageClick(view, this.lessonId, img, this.name)
    })

    wrap.addEventListener('mouseenter', () => {
      attachResizeHandles(view, img, this.name)
    })

    wrap.append(img)
    attachResizeHandles(view, img, this.name)
    return wrap
  }
}

/**
 * Immagini della lezione nell'editor: il Markdown dice `assets/images/x.png`, il browser le
 * trova sotto l'API (come withImageUrls per la lettura). atomic-editor non ha un risolutore,
 * quindi si corregge l'src delle <img> che disegna; quelle che salta (didascalie con [ ], come
 * "[MOCK] …") le disegna un riquadro nostro sotto la riga.
 * Le immagini consecutive (strisce) sono gestite da lessonImageStrips e vengono saltate qui.
 */
export function lessonImages(lessonId: number): Extension {
  const build = (state: EditorState): DecorationSet => {
    const strips = findMarkdownImageStrips(state, lessonId)
    const stripLines = new Set<number>()
    for (const s of strips) {
      for (let ln = s.startLine; ln <= s.endLine; ln++) {
        stripLines.add(ln)
      }
    }
    const ranges: Range<Decoration>[] = []
    for (let n = 1; n <= state.doc.lines; n++) {
      if (stripLines.has(n)) continue
      const line = state.doc.line(n)
      const text = line.text.trim()
      const m = LOCAL_IMAGE_RE.exec(text)
      if (!m || ATOMIC_IMAGE_RE.test(text)) continue
      const width = m[3] ? parseInt(m[3], 10) : undefined
      ranges.push(
        Decoration.widget({
          widget: new LessonImageWidget(imageUrl(lessonId, m[2]), m[1], m[2], width, lessonId),
          block: true,
          side: 1,
        }).range(line.to),
      )
    }
    return Decoration.set(ranges, true)
  }
  const images = StateField.define<DecorationSet>({
    create: build,
    update: (value, tr) => (tr.docChanged ? build(tr.state) : value),
    provide: (field) => EditorView.decorations.from(field),
  })
  const urls = ViewPlugin.define((view) => {
    const fix = () => {
      view.contentDOM.querySelectorAll<HTMLImageElement>('img').forEach((img) => {
        const rawSrc = img.getAttribute('src') ?? ''
        const m = /^(?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#w=(\d+))?$/.exec(rawSrc)
        if (m) {
          const name = m[1]
          const w = m[2]
          img.src = imageUrl(lessonId, name)
          img.dataset.imageName = name
          if (w) img.style.width = `${w}px`
          img.style.maxWidth = '100%'
        }
        const name = img.dataset.imageName
        if (name && !img.dataset.hasHandlers) {
          img.dataset.hasHandlers = 'true'
          img.addEventListener('click', (e) => {
            e.preventDefault()
            e.stopPropagation()
            handleImageClick(view, lessonId, img, name)
          })
          img.parentElement?.addEventListener('mouseenter', () => {
            attachResizeHandles(view, img, name)
          })
          attachResizeHandles(view, img, name)
        }
      })
    }
    const observer = new MutationObserver(fix)
    observer.observe(view.contentDOM, { childList: true, subtree: true })
    fix()
    return { destroy: () => observer.disconnect() }
  })
  return [images, urls]
}
