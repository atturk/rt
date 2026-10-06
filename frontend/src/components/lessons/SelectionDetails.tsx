import { ArrowDown, ArrowUp } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { formatCost, lessonTitle, type Lesson } from '@/lib/format'
import { formatDuration, selectionDetails, studyTotal, shortDate, sortSelection, type SelectionSort } from '@/lib/lessonsPage'
import { studyDate } from '@/components/study/studyProgress'

const COLUMNS: { key: SelectionSort; label: string }[] = [
  { key: 'lezione', label: 'Lezione' }, { key: 'audio', label: 'Audio' }, { key: 'studio', label: 'Studio' },
  { key: 'domande', label: 'Domande' }, { key: 'costo', label: 'Costo' },
]

export function SelectionDetails({ lessons, open, onClose }: { lessons: Lesson[]; open: boolean; onClose: () => void }) {
  const [sort, setSort] = useState<{ key: SelectionSort; direction: 'asc' | 'desc' }>({ key: 'costo', direction: 'desc' })
  const totals = selectionDetails(lessons)
  const cards = [
    { label: 'Audio', value: formatDuration(totals.duration), note: totals.firstDate ? `dal ${shortDate(totals.firstDate)} al ${shortDate(totals.lastDate!)}` : '—' },
    { label: 'Unità', value: totals.units ?? '—', note: totals.units == null ? '—' : `${totals.learned} apprese · ${totals.learning} in apprendimento` },
    { label: 'Domande', value: totals.questions ?? '—', note: totals.pending == null ? '—' : `${totals.pending} da fare` },
    { label: 'Costo', value: formatCost(totals.cost), note: totals.costPerHour == null ? '—' : `${formatCost(totals.costPerHour)} per ora di audio` },
    { label: 'Ultimo studio', value: totals.lastStudy ? studyDate(totals.lastStudy.at) : '—', note: totals.lastStudy?.lesson ?? '—' },
    { label: 'Stato', value: `${totals.ready} pronte`, note: [totals.toVerify > 0 && `${totals.toVerify} da verificare`, totals.errors > 0 && `${totals.errors} con errore`].filter(Boolean).join(' · ') || '—' },
  ]
  return <Modal open={open} onClose={onClose} title={lessons.length === 1 ? '1 lezione selezionata' : `${lessons.length} lezioni selezionate`}
    className="w-[min(680px,calc(100vw-32px))]" testId="selection-details">
    <div className="mt-5 grid grid-cols-3 gap-3 max-sm:grid-cols-2">
      {cards.map(card => <div key={card.label} className="min-w-0 rounded-lg border p-3">
        <div className="text-meta text-muted-foreground">{card.label}</div>
        <div className="my-1 text-body font-semibold tabular-nums">{card.value}</div>
        <div className="text-meta text-muted-foreground [overflow-wrap:anywhere]">{card.note}</div>
      </div>)}
    </div>
    <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-muted" role="img"
      aria-label={`${totals.learned} unità apprese, ${totals.learning} in apprendimento, ${totals.ignored} ignorate su ${totals.units ?? 0}`}>
      <span className="bg-success" style={{ width: `${totals.percentages.learned}%` }} />
      <span className="bg-warning" style={{ width: `${totals.percentages.learning}%` }} />
      <span style={{ flex: 1 }} />
      <span className="bg-danger" style={{ width: `${totals.percentages.ignored}%` }} />
    </div>
    <div className="mt-2 flex flex-wrap gap-3 text-meta text-muted-foreground">
      {([['learned', 'apprese', 'bg-success'], ['learning', 'in apprendimento', 'bg-warning'], ['toLearn', 'da imparare', 'bg-muted'], ['ignored', 'ignorate', 'bg-danger']] as const).map(([key, label, color]) =>
        <span key={key} className="inline-flex items-center gap-1.5"><i aria-hidden className={`size-2 rounded-sm ${color}`} />
          {totals.units ? `${Math.round(totals.percentages[key])}%` : '—'} {label}
        </span>)}
    </div>
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-meta tabular-nums">
        <thead><tr>{COLUMNS.map(column => <th key={column.key} scope="col"
          aria-sort={sort.key === column.key ? sort.direction === 'asc' ? 'ascending' : 'descending' : 'none'}
          className={column.key === 'lezione' ? 'text-left' : 'text-right'}>
          <Button variant="ghost" size="sm" className="h-8 gap-1 px-1 text-meta" onClick={() => setSort({ key: column.key,
            direction: sort.key === column.key ? sort.direction === 'asc' ? 'desc' : 'asc' : column.key === 'lezione' ? 'asc' : 'desc' })}>
            {column.label}{sort.key === column.key && (sort.direction === 'asc' ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />)}
          </Button>
        </th>)}</tr></thead>
        <tbody>{sortSelection(lessons, sort.key, sort.direction).map(lesson => <tr key={lesson.id} className="border-t">
          <td className="min-w-48 py-2 pr-3">{lessonTitle(lesson)}</td>
          <td className="whitespace-nowrap px-2 text-right">{formatDuration(lesson.duration_seconds)}</td>
          <td className="whitespace-nowrap px-2 text-right">{lesson.unit_count == null ? '—' : `${lesson.study_learned ?? 0}/${studyTotal(lesson)}`}</td>
          <td className="px-2 text-right">{lesson.recall_questions ?? '—'}</td>
          <td className="whitespace-nowrap pl-2 text-right">{formatCost(lesson.cost_usd)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="mt-4 grid gap-2 text-meta text-muted-foreground">
      <div><strong className="font-semibold text-foreground">Materie</strong> {totals.subjects.map(group => `${group.name} ${group.count}`).join(' · ') || '—'}</div>
      <div><strong className="font-semibold text-foreground">Docenti</strong> {totals.teachers.map(group => `${group.name} ${group.count}`).join(' · ') || '—'}</div>
    </div>
  </Modal>
}
