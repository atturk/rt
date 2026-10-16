import { Prec, StateEffect, StateField, type EditorState } from '@codemirror/state'
import { dropCursor, EditorView, ViewPlugin, type ViewUpdate } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { copyMaterialPage } from '@/api/images'
import { unitRanges } from './lessonUnits'
import { timecodeSpans } from './timecodeLock'

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

type Options = {
  upload: (file: File) => Promise<Schemas['EditorImage']>
  started: (task: Promise<void>) => void
}

export function findInsertPosition(state: EditorState, position: number): number {
  let pos = position
  const line = state.doc.lineAt(pos)
  if (line.text.trim().startsWith('#')) {
    const next = line.number + 1
    pos = next <= state.doc.lines ? state.doc.line(next).from : state.doc.length
  }
  const unit = unitRanges(state).find((u) => pos >= u.from && pos <= u.to)
  const timecode = unit && timecodeSpans(state).find((s) => s.from >= unit.from && s.to <= unit.to)
  if (timecode && pos <= timecode.to) {
    const next = state.doc.lineAt(timecode.to).number + 1
    pos = next <= state.doc.lines ? state.doc.line(next).from : timecode.to
  }
  return pos
}

export function formatImagesMarkdown(items: Array<{ path: string; alt_text: string }>): string {
  const lines = items.map((it) => {
    const alt = it.alt_text.replace(/[\\[\]\r\n]/g, ' ')
    const cleanPath = it.path.startsWith('assets/images/')
      ? it.path
      : `assets/images/${it.path.split('/').pop()}`
    return `![${alt}](${cleanPath})`
  })
  return `\n\n${lines.join('\n')}\n\n`
}

export function removeImagesFromDocument(view: EditorView, imageNames: string[]): boolean {
  const namesSet = new Set(imageNames.map((n) => n.split('/').pop()!))
  const doc = view.state.doc
  const linesToRemove: Array<{ from: number; to: number }> = []

  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    const text = line.text.trim()
    const match = /^!\[(.*?)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)\)$/.exec(text)
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
  const origClean = originalName.split('/').pop()!
  const newClean = newName.split('/').pop()!
  const doc = view.state.doc
  const changes: Array<{ from: number; to: number; insert: string }> = []

  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    const text = line.text
    const regex = /!\[(.*?)\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)\)/g
    let match: RegExpExecArray | null
    while ((match = regex.exec(text)) !== null) {
      if (match[2] === origClean) {
        const from = line.from + match.index
        const to = from + match[0].length
        const alt = newAltText !== undefined ? newAltText.replace(/[\\[\]\r\n]/g, ' ') : match[1]
        const replacement = `![${alt}](assets/images/${newClean})`
        changes.push({ from, to, insert: replacement })
      }
    }
  }

  if (changes.length === 0) return false
  changes.reverse()
  view.dispatch({ changes })
  return true
}

/** Incolla e trascina file: nel documento entra soltanto il riferimento relativo restituito dall'API. */
export function lessonImageUploads(options: Options) {
  const insert = (view: EditorView, files: File[], position: number) => {
    if (!files.length || view.state.readOnly) return false
    const pos = findInsertPosition(view.state, position)
    const id = Symbol('immagini')
    view.dispatch({ effects: addAnchor.of({ id, position: pos }) })
    const task = (async () => {
      try {
        for (const file of files) {
          const image = await options.upload(file)
          if (!view.plugin(alive)?.active || view.state.readOnly) return
          const at = view.state.field(anchors).get(id)
          if (at === undefined) return
          const alt = image.alt_text.replace(/[\\[\]\r\n]/g, ' ')
          view.dispatch({ changes: { from: at, insert: `\n\n![${alt}](${image.path})\n\n` } })
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
    item: { path?: string; alt_text?: string; in_assets?: boolean; source_name?: string; page?: number; lessonId?: number },
    position: number,
  ) => {
    if (view.state.readOnly) return false
    const pos = findInsertPosition(view.state, position)
    const id = Symbol('media-insert')
    view.dispatch({ effects: addAnchor.of({ id, position: pos }) })

    const task = (async () => {
      try {
        let finalPath = item.path || ''
        let finalAlt = item.alt_text || ''

        if (!item.in_assets && item.source_name && item.page != null && item.lessonId != null) {
          const copied = await copyMaterialPage(item.lessonId, item.source_name, item.page)
          finalPath = copied.path
          finalAlt = copied.alt_text
        }

        if (!view.plugin(alive)?.active || view.state.readOnly) return
        const at = view.state.field(anchors).get(id)
        if (at === undefined) return
        const textToInsert = formatImagesMarkdown([{ path: finalPath, alt_text: finalAlt }])
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
          const pos = findInsertPosition(this.view.state, this.view.state.selection.main.from)
          const textToInsert = formatImagesMarkdown(items)
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

  return [
    anchors,
    alive,
    mediaSyncPlugin,
    dropCursor(),
    Prec.highest(
      EditorView.domEventHandlers({
        paste(event, view) {
          const files = Array.from(event.clipboardData?.files ?? []).filter(supported)
          if (!insert(view, files, view.state.selection.main.from)) return false
          event.preventDefault()
          return true
        },
        drop(event, view) {
          const mediaData = event.dataTransfer?.getData(RT_MEDIA_DRAG_TYPE)
          if (mediaData) {
            event.preventDefault()
            const at =
              view.posAtCoords({ x: event.clientX, y: event.clientY }) ??
              view.state.selection.main.head
            try {
              const item = JSON.parse(mediaData)
              insertMediaItem(view, item, at)
              return true
            } catch {
              return false
            }
          }

          const files = Array.from(event.dataTransfer?.files ?? []).filter(supported)
          const at =
            view.posAtCoords({ x: event.clientX, y: event.clientY }) ??
            view.state.selection.main.head
          if (!insert(view, files, at)) return false
          event.preventDefault()
          return true
        },
        dragover(event, view) {
          if (
            !view.state.readOnly &&
            (Array.from(event.dataTransfer?.files ?? []).some(supported) ||
              event.dataTransfer?.types.includes(RT_MEDIA_DRAG_TYPE))
          ) {
            event.preventDefault()
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
            return true
          }
          return false
        },
      }),
    ),
  ]
}
