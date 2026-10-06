import { CircleCheck, CircleDashed, Contrast } from 'lucide-react'
import type { StudyStatus } from '@/api/studyProgress'

export const STUDY_ICONS = {
  'da-imparare': { icon: CircleDashed, className: 'text-muted-foreground' },
  'in-apprendimento': { icon: Contrast, className: 'text-warning' },
  appreso: { icon: CircleCheck, className: 'text-success [&_circle]:fill-success [&_path]:stroke-background' },
} as const

export const STATUS_LABELS: Record<StudyStatus, string> = {
  'da-imparare': 'da imparare',
  'in-apprendimento': 'in apprendimento',
  appreso: 'appreso',
}

export function nextStudyStatus(status: StudyStatus = 'da-imparare'): StudyStatus {
  return status === 'da-imparare' ? 'in-apprendimento' : status === 'in-apprendimento' ? 'appreso' : 'da-imparare'
}

export function initialStudyUnit(units: { status?: StudyStatus }[]): number {
  const index = units.findIndex(unit => unit.status !== 'appreso')
  return index < 0 ? 0 : index
}

/** Data nel fuso del dispositivo, come gli altri dati personali dell'app. */
export function studyDate(value: string | null | undefined, now = new Date()): string {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
  if (date.toDateString() === now.toDateString()) return 'oggi'
  if (date.toDateString() === yesterday.toDateString()) return 'ieri'
  return date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short',
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }) })
}
