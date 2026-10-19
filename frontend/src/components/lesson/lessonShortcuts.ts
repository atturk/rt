import { StateEffect, StateField, type EditorState, type Range } from '@codemirror/state'
import { Decoration, type DecorationSet, EditorView, WidgetType } from '@codemirror/view'
import { unmountDomTooltip } from '@/components/ui/dom-tooltip'
import { unitRanges } from './lessonUnits'
import { timecodeSeconds } from './timecodeLock'
import { createUnitShortcuts } from './unitShortcuts'

type Options = { lessonId: number; units: string[]; navigate: (href: string) => void }
export const setUnitShortcuts = StateEffect.define<Options>()

class Shortcuts extends WidgetType {
  readonly options: Options
  readonly unit: string
  constructor(options: Options, unit: string) {
    super()
    this.options = options
    this.unit = unit
  }
  eq(other: Shortcuts) {
    return other.unit === this.unit && other.options.lessonId === this.options.lessonId
      && other.options.navigate === this.options.navigate
  }
  toDOM() {
    const node = createUnitShortcuts(this.options.lessonId, this.unit, this.options.navigate)
    node.classList.add('rt-editor-shortcuts')
    return node
  }
  destroy(node: HTMLElement) { node.querySelectorAll<HTMLElement>('a').forEach(link => unmountDomTooltip(link)) }
  ignoreEvent() { return true }
}

function build(state: EditorState, options: Options | null): DecorationSet {
  if (!options) return Decoration.none
  const ranges: Range<Decoration>[] = []
  for (const unit of unitRanges(state)) {
    if (!options.units.includes(unit.id)) continue
    const heading = state.doc.lineAt(unit.from)
    let next = heading.number + 1
    while (next <= state.doc.lines && state.doc.line(next).from <= unit.to && !state.doc.line(next).text.trim()) next++
    const line = next <= state.doc.lines && state.doc.line(next).from <= unit.to ? state.doc.line(next) : null
    const position = line && timecodeSeconds(line.text) !== null ? line.to : heading.to
    ranges.push(Decoration.widget({ widget: new Shortcuts(options, unit.id), side: 1 }).range(position))
  }
  return Decoration.set(ranges, true)
}

/** Le scorciatoie sono widget: non entrano mai nel Markdown né nei salvataggi. */
export const lessonShortcuts = StateField.define<{ options: Options | null; decorations: DecorationSet }>({
  create: () => ({ options: null, decorations: Decoration.none }),
  update(value, tr) {
    let options = value.options
    for (const effect of tr.effects) if (effect.is(setUnitShortcuts)) options = effect.value
    if (!tr.docChanged && options === value.options) return value
    return { options, decorations: build(tr.state, options) }
  },
  provide: field => EditorView.decorations.from(field, value => value.decorations),
})
