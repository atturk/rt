import { StateEffect, StateField, type EditorState, type Range } from '@codemirror/state'
import { Decoration, EditorView, WidgetType, type DecorationSet } from '@codemirror/view'
import type { Schemas } from '@/api/client'
import { unitRanges } from './lessonUnits'
import { timecodeSpans } from './timecodeLock'

type Unit = Schemas['UnitRelevanceItem']
export const setClassifier = StateEffect.define<Unit[]>()

class ClassificationWidget extends WidgetType {
  readonly label: string | null
  readonly score: number | null
  constructor(label: string | null, score: number | null) { super(); this.label = label; this.score = score }
  eq(other: ClassificationWidget) { return other.label === this.label && other.score === this.score }
  toDOM() {
    const row = document.createElement('span')
    row.className = 'rt-unit-classification'
    if (this.label) {
      const label = document.createElement('span')
      label.className = 'rt-unit-label'
      label.textContent = this.label
      row.append(label)
    }
    if (this.score != null) {
      const score = document.createElement('span')
      score.className = `rt-unit-score ${this.score < .5 ? 'text-danger' : this.score < 1.5 ? 'text-warning' : 'text-success'}`
      score.textContent = this.score.toLocaleString('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
      row.append(score)
    }
    return row
  }
}

function build(state: EditorState, units: Unit[]): DecorationSet {
  const decorations: Range<Decoration>[] = []
  const spans = timecodeSpans(state)
  for (const range of unitRanges(state)) {
    const unit = units.find((u) => u.unit_id === range.id)
    if (!unit || unit.stale || unit.error) continue
    const timecode = spans.find((s) => s.from >= range.from && s.to <= range.to)
    if (!timecode) continue
    const excluded = unit.effective !== 'didactic'
    const label = excluded ? (!unit.override || unit.override === unit.prediction ? unit.label : null) ?? (unit.effective === 'organizational' ? 'Informazioni organizzative' : 'Nessun contenuto didattico') : null
    const rawScore = unit.answer?.score
    const score = typeof rawScore === 'number' && Number.isFinite(rawScore) ? rawScore : null
    if (label || score != null) decorations.push(Decoration.widget({ widget: new ClassificationWidget(label, score), side: 1 }).range(timecode.to))
    if (excluded) {
      for (let n = state.doc.lineAt(timecode.to).number + 1; n <= range.endLine; n++) {
        decorations.push(Decoration.line({ class: 'rt-unit-excluded' }).range(state.doc.line(n).from))
      }
    }
  }
  return Decoration.set(decorations, true)
}

export const lessonClassifier = StateField.define<{ units: Unit[]; decorations: DecorationSet }>({
  create: () => ({ units: [], decorations: Decoration.none }),
  update(value, tr) {
    let units = value.units
    for (const effect of tr.effects) if (effect.is(setClassifier)) units = effect.value
    return tr.docChanged || units !== value.units ? { units, decorations: build(tr.state, units) } : value
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.decorations),
})
