import { Prec, StateEffect, StateField } from '@codemirror/state'
import { EditorView, ViewPlugin } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { unitRanges } from './lessonUnits'
import { timecodeSpans } from './timecodeLock'

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
const supported = (file: File) => ['image/png', 'image/jpeg', 'image/gif'].includes(file.type) || (!file.type && /\.(png|jpe?g|gif)$/i.test(file.name))

type Options = {
  upload: (file: File) => Promise<Schemas['EditorImage']>
  started: (task: Promise<void>) => void
}

/** Incolla e trascina file: nel documento entra soltanto il riferimento relativo restituito dall'API. */
export function lessonImageUploads(options: Options) {
  const insert = (view: EditorView, files: File[], position: number) => {
    if (!files.length || view.state.readOnly) return false
    // I titoli e i timecode restano intatti: un'immagine su un titolo va nel corpo dell'unità.
    const unit = unitRanges(view.state).find((u) => position >= u.from && position <= u.to)
    const timecode = unit && timecodeSpans(view.state).find((s) => s.from >= unit.from && s.to <= unit.to)
    if (timecode && position <= timecode.to) {
      const next = view.state.doc.lineAt(timecode.to).number + 1
      position = next <= view.state.doc.lines ? view.state.doc.line(next).from : timecode.to
    }
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
  return [anchors, alive, Prec.highest(EditorView.domEventHandlers({
    paste(event, view) {
      const files = Array.from(event.clipboardData?.files ?? []).filter(supported)
      if (!insert(view, files, view.state.selection.main.from)) return false
      event.preventDefault()
      return true
    },
    drop(event, view) {
      const files = Array.from(event.dataTransfer?.files ?? []).filter(supported)
      const at = view.posAtCoords({ x: event.clientX, y: event.clientY }) ?? view.state.selection.main.head
      if (!insert(view, files, at)) return false
      event.preventDefault()
      return true
    },
    dragover(event, view) {
      if (!view.state.readOnly && Array.from(event.dataTransfer?.files ?? []).some(supported)) {
        event.preventDefault()
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
        return true
      }
      return false
    },
  }))]
}
