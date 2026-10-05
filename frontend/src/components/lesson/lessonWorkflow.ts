import { EditorState } from '@codemirror/state'
import type { Schemas } from '@/api/client'
import { unitRanges } from './lessonUnits'

export type UnitTask = 'done' | 'working' | 'waiting'

/** Il checkpoint contiene solo il testo già scritto; la scaletta dà i titoli che ancora mancano. */
export function liveRewrite(outline: Schemas['Outline'], document: Schemas['LessonDocument'] | undefined, job: Schemas['Job']) {
  const state = EditorState.create({ doc: document?.markdown ?? '' })
  const blocks = new Map(unitRanges(state).map((unit) => [unit.id, state.sliceDoc(unit.from, unit.to)]))
  const completed = new Set(document?.sections.map((s) => s.unit_id))
  const units = outline.macro_sections.flatMap((m) => m.units)
  const current = units.findIndex((u) => u.id === job.progress?.unit_id)
  const targeted = job.type === 'rewrite_unit' || typeof job.payload.unit_id === 'string'
  const force = job.payload.force === true || (typeof job.payload.options === 'object' && job.payload.options != null && 'force' in job.payload.options && job.payload.options.force === true)
  const tasks: Record<string, UnitTask> = {}
  const lines: string[] = []
  for (const macro of outline.macro_sections) {
    lines.push(`## ${macro.id}. ${macro.title}\n`)
    for (const unit of macro.units) {
      const index = units.indexOf(unit)
      const done = completed.has(unit.id) && blocks.has(unit.id) && (current < 0 ? !force : targeted ? index !== current : index < current)
      tasks[unit.id] = index === current ? 'working' : done ? 'done' : 'waiting'
      lines.push(done ? blocks.get(unit.id)! : `### ${unit.id} ${unit.title}`, '')
    }
  }
  return {
    tasks,
    document: { markdown: lines.join('\n'), html: '', final: false, pending: false, sections: document?.sections.filter((s) => tasks[s.unit_id] === 'done') ?? [] } satisfies Schemas['LessonDocument'],
  }
}

export function isRewriting(job: Schemas['Job'] | undefined, ready: boolean) {
  if (!job || !['queued', 'running'].includes(job.state)) return false
  if (job.progress?.phase === 'rewrite') return job.progress.completed !== true
  return !ready && (job.type === 'run_pipeline' && (!job.progress?.phase || job.progress.phase === 'outline') || job.type === 'run_phase' && job.payload.phase === 'rewrite' || job.type === 'rewrite_unit')
}
