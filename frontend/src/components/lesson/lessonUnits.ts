import { type EditorState, type Extension, type Range, StateEffect, StateField } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, ViewPlugin, WidgetType } from '@codemirror/view'
import type { UnitTask } from './lessonWorkflow'

/**
 * Le unità nel Markdown dell'editor della lezione: dal titolo `### 1.1 Titolo` fino al titolo
 * successivo (##/###). Servono a mettere in fondo a ciascuna il riquadro dell'arricchimento
 * (elementi DOM di React, passati con setSlots).
 */

const UNIT_RE = /^###\s+(\S+)\s/
const HEADING_RE = /^#{1,3}\s/

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

type UnitsState = { slots: Record<string, HTMLElement>; tasks: Record<string, { state: UnitTask; element: HTMLElement }>; decorations: DecorationSet }

function build(state: EditorState, slots: UnitsState['slots'], tasks: UnitsState['tasks']): UnitsState {
  const ranges: Range<Decoration>[] = []
  for (const unit of unitRanges(state)) {
    // come le intestazioni della lettura: ci si arriva con [data-unit-id]
    const task = tasks[unit.id]
    ranges.push(Decoration.line({ attributes: { 'data-unit-id': unit.id, ...(task ? { 'data-task': task.state } : {}) }, class: task?.state === 'waiting' ? 'rt-unit-waiting' : '' }).range(unit.from))
    if (task) {
      ranges.push(Decoration.widget({ widget: new SlotWidget(task.element), side: -1 }).range(unit.from))
      if (task.state === 'working') ranges.push(Decoration.widget({ widget: new PendingUnit(), block: true, side: 1 }).range(unit.to))
    }
    const slot = slots[unit.id]
    if (slot) ranges.push(Decoration.widget({ widget: new SlotWidget(slot), block: true, side: 1 }).range(unit.to))
  }
  return { slots, tasks, decorations: Decoration.set(ranges, true) }
}

const unitsField = StateField.define<UnitsState>({
  create: (state) => build(state, {}, {}),
  update(value, tr) {
    let { slots, tasks } = value
    for (const effect of tr.effects) {
      if (effect.is(setSlots)) slots = effect.value
      if (effect.is(setUnitTasks)) tasks = effect.value
    }
    if (!tr.docChanged && slots === value.slots && tasks === value.tasks) return value
    return build(tr.state, slots, tasks)
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.decorations),
})

export const lessonUnits: Extension = unitsField

const LOCAL_IMAGE_RE = /^!\[(.*)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)\)\s*$/
// Quelle che atomic-editor disegna da sé (didascalia senza parentesi quadre).
const ATOMIC_IMAGE_RE = /^!\[([^\]]*)\]\(([^\s)"']+)(?:\s+["'][^)]*["'])?\)$/

const imageUrl = (lessonId: number, name: string) => `/api/v1/lessons/${lessonId}/assets/images/${encodeURIComponent(name)}`

class LessonImageWidget extends WidgetType {
  readonly src: string
  readonly alt: string
  constructor(src: string, alt: string) {
    super()
    this.src = src
    this.alt = alt
  }
  eq(other: LessonImageWidget) {
    return other.src === this.src && other.alt === this.alt
  }
  toDOM() {
    const wrap = document.createElement('div')
    wrap.className = 'rt-editor-image'
    const img = document.createElement('img')
    img.src = this.src
    img.alt = this.alt
    wrap.append(img)
    return wrap
  }
}

/**
 * Immagini della lezione nell'editor: il Markdown dice `assets/images/x.png`, il browser le
 * trova sotto l'API (come withImageUrls per la lettura). atomic-editor non ha un risolutore,
 * quindi si corregge l'src delle <img> che disegna; quelle che salta (didascalie con [ ], come
 * "[MOCK] …") le disegna un riquadro nostro sotto la riga.
 */
export function lessonImages(lessonId: number): Extension {
  const build = (state: EditorState): DecorationSet => {
    const ranges: Range<Decoration>[] = []
    for (let n = 1; n <= state.doc.lines; n++) {
      const line = state.doc.line(n)
      const text = line.text.trim()
      const m = LOCAL_IMAGE_RE.exec(text)
      if (!m || ATOMIC_IMAGE_RE.test(text)) continue
      ranges.push(Decoration.widget({ widget: new LessonImageWidget(imageUrl(lessonId, m[2]), m[1]), block: true, side: 1 }).range(line.to))
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
        const m = /^(?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)$/.exec(img.getAttribute('src') ?? '')
        if (m) img.src = imageUrl(lessonId, m[1])
      })
    }
    const observer = new MutationObserver(fix)
    observer.observe(view.contentDOM, { childList: true, subtree: true })
    fix()
    return { destroy: () => observer.disconnect() }
  })
  return [images, urls]
}
