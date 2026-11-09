import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  Bookmark,
  Circle,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Contrast,
  Eye,
  Flag,
  Flame,
  HelpCircle,
  Repeat,
  Star,
} from 'lucide-react'

export type StudyStatus = string

export interface CustomStudyStatus {
  id: string
  nome: string
  colore: string
  icona: string
  /** Aprendo lo Studio le unità con questo stato si saltano, come Appresa e Ignorata. */
  salta?: boolean
}

export const PRESET_ICONS: Record<string, LucideIcon> = {
  Circle,
  Star,
  Flag,
  Bookmark,
  Flame,
  Eye,
  HelpCircle,
  Repeat,
  Clock,
  AlertTriangle,
}

export const PRESET_COLORS = [
  { id: 'text-sky-500', label: 'Azzurro', className: 'text-sky-500' },
  { id: 'text-indigo-500', label: 'Indaco', className: 'text-indigo-500' },
  { id: 'text-purple-500', label: 'Viola', className: 'text-purple-500' },
  { id: 'text-amber-500', label: 'Ambra', className: 'text-amber-500' },
  { id: 'text-emerald-500', label: 'Smeraldo', className: 'text-emerald-500' },
  { id: 'text-rose-500', label: 'Rosa', className: 'text-rose-500' },
  { id: 'text-teal-500', label: 'Verde acqua', className: 'text-teal-500' },
  { id: 'text-slate-400', label: 'Grigio', className: 'text-slate-400' },
]

export const DEFAULT_STATUS_IDS = ['da-imparare', 'in-apprendimento', 'appreso', 'ignorata']

export const DEFAULT_STATUS_DEFINITIONS: Record<
  string,
  { label: string; icon: LucideIcon; className: string }
> = {
  'da-imparare': { label: 'Da imparare', icon: CircleDashed, className: 'text-muted-foreground' },
  'in-apprendimento': { label: 'In apprendimento', icon: Contrast, className: 'text-study-learning' },
  appreso: {
    label: 'Appresa',
    icon: CircleCheck,
    className: 'text-study-learned [&_circle]:fill-study-learned [&_path]:stroke-background',
  },
  ignorata: { label: 'Ignorata', icon: CircleX, className: 'text-study-ignored' },
}

export function resolveStudyStatus(
  status: string = 'da-imparare',
  customStatuses: CustomStudyStatus[] = []
): { label: string; icon: LucideIcon; className: string; isDefault: boolean } {
  if (DEFAULT_STATUS_DEFINITIONS[status]) {
    return { ...DEFAULT_STATUS_DEFINITIONS[status], isDefault: true }
  }
  const custom = customStatuses.find((s) => s.id === status)
  if (custom) {
    const icon = PRESET_ICONS[custom.icona] ?? Circle
    return {
      label: custom.nome,
      icon,
      className: custom.colore,
      isDefault: false,
    }
  }
  return { ...DEFAULT_STATUS_DEFINITIONS['in-apprendimento'], isDefault: true }
}

export function resolveStatusOrder(
  customStatuses: CustomStudyStatus[] = [],
  savedOrder: string[] = []
): string[] {
  const customIds = customStatuses.map((s) => s.id)
  const allValid = new Set([...DEFAULT_STATUS_IDS, ...customIds])

  const order = savedOrder.filter((id) => allValid.has(id))

  // Inserisci i default mancanti nella loro posizione iniziale
  DEFAULT_STATUS_IDS.forEach((defId, idx) => {
    if (!order.includes(defId)) {
      order.splice(idx, 0, defId)
    }
  })

  // Aggiungi i nuovi custom id in fondo
  customIds.forEach((cId) => {
    if (!order.includes(cId)) {
      order.push(cId)
    }
  })

  return order
}

export function nextStudyStatus(
  currentStatus: string = 'da-imparare',
  order: string[] = DEFAULT_STATUS_IDS
): string {
  const effectiveOrder = order.length > 0 ? order : DEFAULT_STATUS_IDS
  const currentIndex = effectiveOrder.indexOf(currentStatus)
  if (currentIndex === -1 || currentIndex >= effectiveOrder.length - 1) {
    return effectiveOrder[0]
  }
  return effectiveOrder[currentIndex + 1]
}

export const STUDY_ICONS = new Proxy(DEFAULT_STATUS_DEFINITIONS, {
  get(target, prop: string) {
    if (prop in target) return target[prop]
    return { icon: Circle, className: 'text-muted-foreground' }
  },
}) as Record<string, { icon: LucideIcon; className: string }>

export const STATUS_LABELS = new Proxy(
  {
    'da-imparare': 'Da imparare',
    'in-apprendimento': 'In apprendimento',
    appreso: 'Appresa',
    ignorata: 'Ignorata',
  } as Record<string, string>,
  {
    get(target, prop: string) {
      if (prop in target) return target[prop]
      return prop
    },
  }
)

export const SKIPPED_DEFAULT_STATUSES = ['appreso', 'ignorata']

export function initialStudyUnit(units: { status?: StudyStatus }[], customStatuses: CustomStudyStatus[] = []): number {
  const skipped = new Set([...SKIPPED_DEFAULT_STATUSES, ...customStatuses.filter((s) => s.salta).map((s) => s.id)])
  const index = units.findIndex((unit) => !skipped.has(unit.status ?? 'da-imparare'))
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
  return date.toLocaleDateString('it-IT', {
    day: 'numeric',
    month: 'short',
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  })
}
