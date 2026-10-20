import { Prec, StateEffect, StateField, type EditorState, type Range } from '@codemirror/state'
import { Decoration, type DecorationSet, dropCursor, EditorView, ViewPlugin, type ViewUpdate, WidgetType } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { copyMaterialPage, materialSourceId } from '@/api/images'
import { readPreference } from '@/lib/preferences'

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

export type DropTargetResult = {
  insertAt: number
  headingLine?: number
  label?: string
  subunitRange?: { from: number; to: number }
}

const TIMECODE_RE = /^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*$/
const IMAGE_LINE_RE = /^!\[.*?\]\((?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)(?:#[^)]*)?\)$/

/**
 * Calcola dove inserire un'immagine trascinata o incollata.
 * - 'heading': la sottounità (###, o la macro ## se non ci sono sottounità) sotto il puntatore;
 *   l'immagine va dopo titolo, timecode e immagini già sotto il titolo.
 * - 'free': inizio del blocco sotto il puntatore, mai dentro un titolo.
 */
export function dropTarget(
  state: EditorState,
  pos: number,
  mode: 'heading' | 'free',
): DropTargetResult {
  const clampedPos = Math.max(0, Math.min(pos, state.doc.length))
  const line = state.doc.lineAt(clampedPos)

  if (mode === 'free') {
    // Mai dentro un titolo: se cade su un titolo, va sotto il titolo (+ eventuale timecode)
    if (line.text.trim().startsWith('#')) {
      let insertLine = line.number + 1
      if (insertLine <= state.doc.lines) {
        const nextLine = state.doc.line(insertLine)
        if (TIMECODE_RE.test(nextLine.text)) {
          insertLine++
        }
      }
      const insertAt = insertLine <= state.doc.lines ? state.doc.line(insertLine).from : state.doc.length
      return { insertAt }
    }

    // Inizio del blocco sotto il puntatore
    if (line.text.trim() === '') {
      return { insertAt: line.from }
    }

    let n = line.number
    while (n > 1) {
      const prev = state.doc.line(n - 1)
      if (prev.text.trim() === '' || prev.text.trim().startsWith('#')) break
      n--
    }
    return { insertAt: state.doc.line(n).from }
  }

  // mode === 'heading'
  const docLines = state.doc.lines

  type UnitInfo = {
    headingLine: number
    title: string
    from: number
    to: number
  }

  type MacroSection = {
    headingLine: number
    title: string
    from: number
    to: number
    subunits: UnitInfo[]
  }

  const macros: MacroSection[] = []
  let currentMacro: MacroSection | null = null
  let currentSub: UnitInfo | null = null

  for (let n = 1; n <= docLines; n++) {
    const l = state.doc.line(n)
    const text = l.text

    if (/^##\s+/.test(text)) {
      if (currentSub) {
        currentSub.to = state.doc.line(n - 1).to
        currentSub = null
      }
      if (currentMacro) {
        currentMacro.to = state.doc.line(n - 1).to
      }
      const m = /^##\s+(.*)$/.exec(text)
      currentMacro = {
        headingLine: n,
        title: m ? m[1].trim() : text.trim(),
        from: l.from,
        to: state.doc.length,
        subunits: [],
      }
      macros.push(currentMacro)
    } else if (/^###\s+/.test(text)) {
      if (currentSub) {
        currentSub.to = state.doc.line(n - 1).to
      }
      const m = /^###\s+(.*)$/.exec(text)
      currentSub = {
        headingLine: n,
        title: m ? m[1].trim() : text.trim(),
        from: l.from,
        to: state.doc.length,
      }
      if (currentMacro) {
        currentMacro.subunits.push(currentSub)
      }
    }
  }
  if (currentSub) currentSub.to = state.doc.length
  if (currentMacro) currentMacro.to = state.doc.length

  let chosenTarget: UnitInfo | null = null

  for (const macro of macros) {
    if (clampedPos >= macro.from && clampedPos <= macro.to) {
      if (macro.subunits.length > 0) {
        for (const sub of macro.subunits) {
          if (clampedPos >= sub.from && clampedPos <= sub.to) {
            chosenTarget = sub
            break
          }
        }
        if (!chosenTarget && macro.subunits.length > 0) {
          chosenTarget = macro.subunits[0]
        }
      } else {
        // Macro senza sottounità
        chosenTarget = {
          headingLine: macro.headingLine,
          title: macro.title,
          from: macro.from,
          to: macro.to,
        }
      }
      break
    }
  }

  // Se il documento ha solo ### senza sezioni ##
  if (!chosenTarget) {
    const allSubs: UnitInfo[] = []
    for (let n = 1; n <= docLines; n++) {
      const l = state.doc.line(n)
      if (/^###\s+/.test(l.text)) {
        if (allSubs.length > 0) allSubs[allSubs.length - 1].to = state.doc.line(n - 1).to
        const m = /^###\s+(.*)$/.exec(l.text)
        allSubs.push({
          headingLine: n,
          title: m ? m[1].trim() : l.text.trim(),
          from: l.from,
          to: state.doc.length,
        })
      }
    }
    for (const sub of allSubs) {
      if (clampedPos >= sub.from && clampedPos <= sub.to) {
        chosenTarget = sub
        break
      }
    }
    if (!chosenTarget && allSubs.length > 0) {
      chosenTarget = allSubs[0]
    }
  }

  if (!chosenTarget) {
    return { insertAt: clampedPos }
  }

  // Avanza dopo la riga del titolo, eventuale timecode e immagini già sotto il titolo
  let curLineNum = chosenTarget.headingLine + 1
  let timecodeChecked = false

  while (curLineNum <= docLines) {
    const curLine = state.doc.line(curLineNum)
    const trimmed = curLine.text.trim()

    if (trimmed === '') {
      curLineNum++
      continue
    }

    if (!timecodeChecked && TIMECODE_RE.test(trimmed)) {
      timecodeChecked = true
      curLineNum++
      continue
    }
    timecodeChecked = true

    if (IMAGE_LINE_RE.test(trimmed)) {
      curLineNum++
      continue
    }

    break
  }

  const insertAt = curLineNum <= docLines ? state.doc.line(curLineNum).from : state.doc.length
  const displayTitle = chosenTarget.title.length > 28 ? chosenTarget.title.slice(0, 27) + '…' : chosenTarget.title
  const label = `Sotto «${displayTitle}»`

  return {
    insertAt,
    headingLine: chosenTarget.headingLine,
    label,
    subunitRange: { from: chosenTarget.from, to: chosenTarget.to },
  }
}

export function findInsertPosition(state: EditorState, position: number): number {
  const mode = readPreference<'heading' | 'free'>('editor.image-drop', 'heading')
  return dropTarget(state, position, mode).insertAt
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
  const insert = (view: EditorView, files: File[], position: number) => {
    if (!files.length || view.state.readOnly) return false
    const id = Symbol('immagini')
    view.dispatch({ effects: addAnchor.of({ id, position }) })
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
    item: { path?: string; alt_text?: string; in_assets?: boolean; source_name?: string; source?: string; page?: number; lessonId?: number },
    position: number,
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
          const mode = readPreference<'heading' | 'free'>('editor.image-drop', 'heading')
          const target = dropTarget(this.view.state, this.view.state.selection.main.from, mode)
          const pos = target.insertAt
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
    dropHighlightField,
    dropCursor(),
    Prec.highest(
      EditorView.domEventHandlers({
        paste(event, view) {
          const files = Array.from(event.clipboardData?.files ?? []).filter(supported)
          const mode = readPreference<'heading' | 'free'>('editor.image-drop', 'heading')
          const target = dropTarget(view.state, view.state.selection.main.from, mode)
          if (!insert(view, files, target.insertAt)) return false
          event.preventDefault()
          return true
        },
        drop(event, view) {
          view.dispatch({ effects: setDropHighlight.of(null) })
          const mode = readPreference<'heading' | 'free'>('editor.image-drop', 'heading')
          const at =
            view.posAtCoords({ x: event.clientX, y: event.clientY }) ??
            view.state.selection.main.head
          const target = dropTarget(view.state, at, mode)

          const mediaData = event.dataTransfer?.getData(RT_MEDIA_DRAG_TYPE)
          if (mediaData) {
            event.preventDefault()
            try {
              const item = JSON.parse(mediaData)
              insertMediaItem(view, item, target.insertAt)
              return true
            } catch {
              return false
            }
          }

          const files = Array.from(event.dataTransfer?.files ?? []).filter(supported)
          if (!insert(view, files, target.insertAt)) return false
          event.preventDefault()
          return true
        },
        dragover(event, view) {
          if (
            !view.state.readOnly &&
            (Array.from(event.dataTransfer?.files ?? []).some(supported) ||
              event.dataTransfer?.types.includes(RT_MEDIA_DRAG_TYPE) ||
              event.dataTransfer?.types.includes('Files'))
          ) {
            event.preventDefault()
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
            const at =
              view.posAtCoords({ x: event.clientX, y: event.clientY }) ??
              view.state.selection.main.head
            const mode = readPreference<'heading' | 'free'>('editor.image-drop', 'heading')
            const target = dropTarget(view.state, at, mode)
            view.dispatch({ effects: setDropHighlight.of(target) })
            return true
          }
          return false
        },
        dragleave(event, view) {
          if (!event.relatedTarget || !view.dom.contains(event.relatedTarget as Node)) {
            view.dispatch({ effects: setDropHighlight.of(null) })
          }
          return false
        },
      }),
    ),
  ]
}
