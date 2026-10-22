import { isolateHistory } from '@codemirror/commands'
import { Prec, StateEffect, StateField, type EditorState, type Range } from '@codemirror/state'
import { Decoration, type DecorationSet, dropCursor, EditorView, ViewPlugin, type ViewUpdate, WidgetType } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { copyMaterialPage, materialSourceId } from '@/api/images'
import { imageSections, RT_SECTION_IMAGE_DRAG_TYPE, type SectionImageDrag } from './imageSections'

export const EDITOR_INSERT_IMAGES_EVENT = 'rt-editor-insert-images'
export const EDITOR_REMOVE_IMAGES_EVENT = 'rt-editor-remove-images'
export const EDITOR_REPLACE_IMAGE_EVENT = 'rt-editor-replace-image'
export const EDITOR_CURSOR_STATE_EVENT = 'rt-editor-cursor-state'
export const EDITOR_REQUEST_CURSOR_STATE_EVENT = 'rt-editor-request-cursor-state'
export const RT_MEDIA_DRAG_TYPE = 'application/x-rt-media-image'

const addAnchor = StateEffect.define<{ id: symbol; position: number }>()
const removeAnchor = StateEffect.define<symbol>()
const anchors = StateField.define<Map<symbol, number>>({
  create: () => new Map(),
  update(value, tr) {
    const next = new Map([...value].map(([id, position]) => [id, tr.changes.mapPos(position, 1)]))
    for (const effect of tr.effects) {
      if (effect.is(addAnchor)) next.set(effect.value.id, effect.value.position)
      if (effect.is(removeAnchor)) next.delete(effect.value)
    }
    return next
  },
})
const alive = ViewPlugin.define(() => ({ active: true, destroy() { this.active = false } }))
const supported = (file: File) =>
  ['image/png', 'image/jpeg', 'image/gif'].includes(file.type) ||
  (!file.type && /\.(png|jpe?g|gif)$/i.test(file.name))

async function uploadedImageWidth(file: File): Promise<number> {
  if (typeof createImageBitmap !== 'function') return 480
  try {
    const bitmap = await createImageBitmap(file)
    const width = bitmap.width
    bitmap.close()
    return Math.min(width, 480)
  } catch { return 480 }
}

function knownImageWidth(path: string): number {
  const name = path.split('/').pop()?.split('#')[0]
  const image = Array.from(document.images).find(img => img.src.split('/').pop()?.split('#')[0] === name && img.naturalWidth)
  return Math.min(image?.naturalWidth || 480, 480)
}

type Options = {
  upload: (file: File) => Promise<Schemas['EditorImage']>
  started: (task: Promise<void>) => void
}

export type DropTargetResult = {
  insertAt: number
  headingLine?: number
  label?: string
  subunitRange?: { from: number; to: number }
}

const TIMECODE_RE = /^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*$/

/** Il testo resta libero, ma mai prima del timecode o dentro la sezione atomica. */
export function dropTarget(state: EditorState, pos: number): DropTargetResult {
  const at = Math.max(0, Math.min(pos, state.doc.length))
  const section = imageSections(state).find(unit => at >= unit.from && at <= unit.to)
  const line = state.doc.lineAt(at)
  if (section && at <= section.insertAt) return { insertAt: section.insertAt }
  if (line.text.trim().startsWith('#')) return { insertAt: line.to }
  if (!line.text.trim()) return { insertAt: line.from }
  let n = line.number
  while (n > 1) {
    const previous = state.doc.line(n - 1)
    if (!previous.text.trim() || previous.text.startsWith('#') || TIMECODE_RE.test(previous.text) ||
        (section && previous.from <= section.insertAt)) break
    n--
  }
  return { insertAt: state.doc.line(n).from }
}

export function sectionDropTarget(state: EditorState, unitId: string, beforeName?: string): DropTargetResult | null {
  const section = imageSections(state).find(unit => unit.id === unitId)
  if (!section) return null
  return { insertAt: section.images.find(image => image.name === beforeName)?.from ?? section.insertAt }
}

export function findInsertPosition(state: EditorState, position: number): number {
  return dropTarget(state, position).insertAt
}

/** Togli e inserisci in un'unica transazione (e un unico annulla). */
export function moveDocumentImage(view: EditorView, item: SectionImageDrag, target: DropTargetResult, section: boolean): boolean {
  if (view.state.readOnly) return false
  const source = item.fromUnit
    ? imageSections(view.state).find(unit => unit.id === item.fromUnit)?.images.find(image => image.name === item.name)
    : item.fromText != null ? view.state.doc.lineAt(item.fromText) : null
  if (!source) return false
  const line = view.state.doc.lineAt(source.from)
  const match = /^!\[(.*)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#w=(\d+))?\)\s*$/.exec(line.text)
  if (!match || match[2] !== item.name) return false
  const to = Math.min(view.state.doc.length, line.to + 1)
  const at = target.insertAt
  const insert = formatImagesMarkdown([{ path: `assets/images/${item.name}`, alt_text: match[1], width: item.width ?? (match[3] ? Number(match[3]) : undefined) }], section)
  if (at >= line.from && at <= to) {
    if (!section) view.dispatch({ changes: { from: line.from, to: line.to, insert: insert.trim() }, annotations: isolateHistory.of('full') })
    return true
  }
  view.dispatch({ changes: [{ from: line.from, to, insert: '' }, { from: at, insert }].sort((a, b) => a.from - b.from), annotations: isolateHistory.of('full') })
  return true
}

export function formatImagesMarkdown(items: Array<{ path: string; alt_text: string; width?: number }>, section = false): string {
  const lines = items.map((it) => {
    const alt = it.alt_text.replace(/[\\[\]\r\n]/g, ' ')
    const cleanPath = it.path.startsWith('assets/images/')
      ? it.path
      : `assets/images/${it.path.split('/').pop()}`
    const path = cleanPath.split('#')[0]
    const width = Math.max(1, Math.min(480, it.width || Number(/#w=(\d+)/.exec(cleanPath)?.[1]) || 480))
    return `![${alt}](${path}${section ? '' : `#w=${width}`})`
  })
  return `\n\n${lines.join('\n')}\n\n`
}

export function removeImagesFromDocument(view: EditorView, imageNames: string[]): boolean {
  const namesSet = new Set(imageNames.map((n) => n.split('/').pop()!.split('#')[0]))
  const doc = view.state.doc
  const linesToRemove: Array<{ from: number; to: number }> = []

  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    const text = line.text.trim()
    const match = /^!\[(.*?)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#[^)]*)?\)$/.exec(text)
    if (match && namesSet.has(match[2])) {
      const from = line.from > 0 && doc.sliceString(line.from - 1, line.from) === '\n' ? line.from - 1 : line.from
      linesToRemove.push({ from, to: line.to })
    }
  }

  if (linesToRemove.length === 0) return false

  const changes = linesToRemove.reverse().map((r) => ({ from: r.from, to: r.to, insert: '' }))
  view.dispatch({ changes })
  return true
}

export function replaceImageInDocument(
  view: EditorView,
  originalName: string,
  newName: string,
  newAltText?: string,
): boolean {
  const origClean = originalName.split('/').pop()!.split('#')[0]
  const newClean = newName.split('/').pop()!.split('#')[0]
  const doc = view.state.doc
  const changes: Array<{ from: number; to: number; insert: string }> = []

  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    const text = line.text
    const regex = /!\[(.*?)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:(#[^)]*))?\)/g
    let match: RegExpExecArray | null
    while ((match = regex.exec(text)) !== null) {
      if (match[2] === origClean) {
        const from = line.from + match.index
        const to = from + match[0].length
        const alt = newAltText !== undefined ? newAltText.replace(/[\\[\]\r\n]/g, ' ') : match[1]
        const hash = match[3] || ''
        const replacement = `![${alt}](assets/images/${newClean}${hash})`
        changes.push({ from, to, insert: replacement })
      }
    }
  }

  if (changes.length === 0) return false
  changes.reverse()
  view.dispatch({ changes })
  return true
}

class DropLineWidget extends WidgetType {
  readonly label?: string
  constructor(label?: string) {
    super()
    this.label = label
  }
  eq(other: DropLineWidget) {
    return this.label === other.label
  }
  toDOM() {
    const wrap = document.createElement('div')
    wrap.className = 'cm-drop-line-widget'
    if (this.label) {
      const badge = document.createElement('span')
      badge.className = 'cm-drop-line-label'
      badge.textContent = this.label
      wrap.appendChild(badge)
    }
    return wrap
  }
}

export const setDropHighlight = StateEffect.define<DropTargetResult | null>()

export const dropHighlightField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(decorations, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setDropHighlight)) {
        const target = effect.value
        if (!target) return Decoration.none
        const ranges: Range<Decoration>[] = []
        if (target.subunitRange) {
          const doc = tr.state.doc
          const startLine = doc.lineAt(Math.max(0, Math.min(target.subunitRange.from, doc.length))).number
          const endLine = doc.lineAt(Math.max(0, Math.min(target.subunitRange.to, doc.length))).number
          for (let n = startLine; n <= endLine; n++) {
            const line = doc.line(n)
            ranges.push(Decoration.line({ class: 'cm-drop-unit-highlight' }).range(line.from))
          }
        }
        const at = Math.min(target.insertAt, tr.state.doc.length)
        ranges.push(
          Decoration.widget({
            widget: new DropLineWidget(target.label),
            block: true,
            side: -1,
          }).range(at),
        )
        return Decoration.set(ranges, true)
      }
    }
    return tr.docChanged ? decorations.map(tr.changes) : decorations
  },
  provide: (field) => EditorView.decorations.from(field),
})

/** Incolla e trascina file: nel documento entra soltanto il riferimento relativo restituito dall'API. */
export function lessonImageUploads(options: Options) {
  const insert = (view: EditorView, files: File[], position: number, section = false) => {
    if (!files.length || view.state.readOnly) return false
    const id = Symbol('immagini')
    view.dispatch({ effects: addAnchor.of({ id, position }) })
    const task = (async () => {
      try {
        for (const file of files) {
          const image = await options.upload(file)
          const width = section ? undefined : await uploadedImageWidth(file)
          if (!view.plugin(alive)?.active || view.state.readOnly) return
          const at = view.state.field(anchors).get(id)
          if (at === undefined) return
          view.dispatch({ changes: { from: at, insert: formatImagesMarkdown([{ ...image, width }], section) } })
        }
      } finally {
        if (view.plugin(alive)?.active) view.dispatch({ effects: removeAnchor.of(id) })
      }
    })()
    options.started(task)
    return true
  }

  const insertMediaItem = (
    view: EditorView,
    item: { path?: string; alt_text?: string; in_assets?: boolean; source_name?: string; source?: string; page?: number; lessonId?: number },
    position: number,
    section = false,
  ) => {
    if (view.state.readOnly) return false
    const id = Symbol('media-insert')
    view.dispatch({ effects: addAnchor.of({ id, position }) })

    const task = (async () => {
      try {
        let finalPath = item.path || ''
        let finalAlt = item.alt_text || ''

        if (!item.in_assets) {
          const sourceId = materialSourceId(item.source)
          if (!sourceId || item.page == null || item.lessonId == null) return
          const copied = await copyMaterialPage(item.lessonId, sourceId, item.page)
          finalPath = copied.path
          finalAlt = copied.alt_text
        }

        if (!view.plugin(alive)?.active || view.state.readOnly) return
        const at = view.state.field(anchors).get(id)
        if (at === undefined) return
        const textToInsert = formatImagesMarkdown([{ path: finalPath, alt_text: finalAlt, width: knownImageWidth(finalPath) }], section)
        view.dispatch({ changes: { from: at, insert: textToInsert } })
      } finally {
        if (view.plugin(alive)?.active) view.dispatch({ effects: removeAnchor.of(id) })
      }
    })()
    options.started(task)
    return true
  }

  const mediaSyncPlugin = ViewPlugin.fromClass(
    class {
      private view: EditorView
      private onInsert: (e: Event) => void
      private onRemove: (e: Event) => void
      private onReplace: (e: Event) => void
      private onRequestCursor: () => void

      constructor(view: EditorView) {
        this.view = view
        this.onInsert = (e: Event) => {
          const custom = e as CustomEvent<{ items: Array<{ path: string; alt_text: string }> }>
          const items = custom.detail?.items
          if (!items || items.length === 0 || this.view.state.readOnly) return
          const target = dropTarget(this.view.state, this.view.state.selection.main.from)
          const pos = target.insertAt
          const textToInsert = formatImagesMarkdown(items.map(item => ({ ...item, width: knownImageWidth(item.path) })))
          this.view.dispatch({
            changes: { from: pos, insert: textToInsert },
            selection: { anchor: pos + textToInsert.length },
          })
        }
        this.onRemove = (e: Event) => {
          const custom = e as CustomEvent<{ imageNames: string[] }>
          const names = custom.detail?.imageNames
          if (!names || names.length === 0 || this.view.state.readOnly) return
          removeImagesFromDocument(this.view, names)
        }
        this.onReplace = (e: Event) => {
          const custom = e as CustomEvent<{ originalName: string; newName: string; newAltText?: string }>
          const { originalName, newName, newAltText } = custom.detail || {}
          if (!originalName || !newName || this.view.state.readOnly) return
          replaceImageInDocument(this.view, originalName, newName, newAltText)
        }
        this.onRequestCursor = () => {
          this.notifyCursorState()
        }

        window.addEventListener(EDITOR_INSERT_IMAGES_EVENT, this.onInsert)
        window.addEventListener(EDITOR_REMOVE_IMAGES_EVENT, this.onRemove)
        window.addEventListener(EDITOR_REPLACE_IMAGE_EVENT, this.onReplace)
        window.addEventListener(EDITOR_REQUEST_CURSOR_STATE_EVENT, this.onRequestCursor)
        this.notifyCursorState()
      }

      update(update: ViewUpdate) {
        if (update.selectionSet || update.focusChanged || update.docChanged) {
          this.notifyCursorState()
        }
      }

      destroy() {
        window.removeEventListener(EDITOR_INSERT_IMAGES_EVENT, this.onInsert)
        window.removeEventListener(EDITOR_REMOVE_IMAGES_EVENT, this.onRemove)
        window.removeEventListener(EDITOR_REPLACE_IMAGE_EVENT, this.onReplace)
        window.removeEventListener(EDITOR_REQUEST_CURSOR_STATE_EVENT, this.onRequestCursor)
        window.dispatchEvent(
          new CustomEvent(EDITOR_CURSOR_STATE_EVENT, { detail: { hasCursor: false } }),
        )
      }

      private notifyCursorState() {
        const hasCursor =
          !this.view.state.readOnly &&
          this.view.state.selection.main.head !== null &&
          this.view.state.doc.length >= 0
        window.dispatchEvent(
          new CustomEvent(EDITOR_CURSOR_STATE_EVENT, { detail: { hasCursor } }),
        )
      }
    },
  )

  let currentHighlight: DropTargetResult | null = null

  function sameDropHighlight(a: DropTargetResult | null, b: DropTargetResult | null): boolean {
    if (a === b) return true
    if (!a || !b) return false
    return a.insertAt === b.insertAt && a.label === b.label && a.headingLine === b.headingLine
  }

  function eventTarget(event: DragEvent, view: EditorView) {
    const element = (event.target as Element).closest<HTMLElement>('[data-unit-images]')
    const beforeName = (event.target as Element).closest<HTMLElement>('[data-image-name]')?.dataset.imageName
    const section = element?.dataset.unitImages
    const position = section ? sectionDropTarget(view.state, section, beforeName) : null
    return { section: !!position, position: position ?? dropTarget(view.state,
      view.posAtCoords({ x: event.clientX, y: event.clientY }) ?? view.state.selection.main.head) }
  }
  function clearDrag(view: EditorView) {
    view.dom.classList.remove('rt-dragging-images')
    view.dom.querySelectorAll('.rt-image-drop-hover').forEach(element => element.classList.remove('rt-image-drop-hover'))
    if (currentHighlight !== null) {
      currentHighlight = null
      view.dispatch({ effects: setDropHighlight.of(null) })
    }
  }
  return [
    anchors,
    alive,
    mediaSyncPlugin,
    dropHighlightField,
    dropCursor(),
    Prec.highest(
      EditorView.domEventHandlers({
        paste(event, view) {
          const files = Array.from(event.clipboardData?.files ?? []).filter(supported)
          const target = dropTarget(view.state, view.state.selection.main.from)
          if (!insert(view, files, target.insertAt)) return false
          event.preventDefault()
          return true
        },
        dragstart(event, view) {
          if (event.dataTransfer?.types.includes(RT_SECTION_IMAGE_DRAG_TYPE)) view.dom.classList.add('rt-dragging-images')
          return false
        },
        dragenter(event, view) {
          if (event.dataTransfer?.types.some(type => ['Files', RT_MEDIA_DRAG_TYPE, RT_SECTION_IMAGE_DRAG_TYPE].includes(type))) view.dom.classList.add('rt-dragging-images')
          return false
        },
        drop(event, view) {
          clearDrag(view)
          if (view.state.readOnly) return false
          const target = eventTarget(event, view)
          const moving = event.dataTransfer?.getData(RT_SECTION_IMAGE_DRAG_TYPE)
          if (moving) {
            event.preventDefault()
            try { return moveDocumentImage(view, JSON.parse(moving), target.position, target.section) }
            catch { return false }
          }
          const mediaData = event.dataTransfer?.getData(RT_MEDIA_DRAG_TYPE)
          if (mediaData) {
            event.preventDefault()
            try { return insertMediaItem(view, JSON.parse(mediaData), target.position.insertAt, target.section) }
            catch { return false }
          }
          const files = Array.from(event.dataTransfer?.files ?? []).filter(supported)
          if (!insert(view, files, target.position.insertAt, target.section)) return false
          event.preventDefault()
          return true
        },
        dragover(event, view) {
          if (view.state.readOnly || !event.dataTransfer?.types.some(type => ['Files', RT_MEDIA_DRAG_TYPE, RT_SECTION_IMAGE_DRAG_TYPE].includes(type))) return false
          event.preventDefault()
          view.dom.classList.add('rt-dragging-images')
          view.dom.querySelectorAll('.rt-image-drop-hover').forEach(element => element.classList.remove('rt-image-drop-hover'))
          const element = (event.target as Element).closest<HTMLElement>('[data-unit-images]')
          element?.classList.add('rt-image-drop-hover')
          const target = eventTarget(event, view)
          event.dataTransfer.dropEffect = event.dataTransfer.types.includes(RT_SECTION_IMAGE_DRAG_TYPE) ? 'move' : 'copy'
          const nextHighlight = target.section ? null : target.position
          if (!sameDropHighlight(currentHighlight, nextHighlight)) {
            currentHighlight = nextHighlight
            view.dispatch({ effects: setDropHighlight.of(nextHighlight) })
          }
          return true
        },
        dragleave(event, view) {
          if (event.relatedTarget) {
            if (!view.dom.contains(event.relatedTarget as Node)) clearDrag(view)
            return false
          }
          const rect = view.dom.getBoundingClientRect()
          const x = event.clientX
          const y = event.clientY
          if (x <= rect.left || x >= rect.right || y <= rect.top || y >= rect.bottom) {
            clearDrag(view)
          }
          return false
        },
        dragend(_event, view) { clearDrag(view); return false },
      }),
    ),
  ]
}
