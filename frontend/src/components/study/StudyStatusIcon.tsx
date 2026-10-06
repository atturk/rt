import type { StudyStatus } from '@/api/studyProgress'
import { STUDY_ICONS } from './studyProgress'

export function StudyStatusIcon({ status = 'da-imparare' }: { status?: StudyStatus }) {
  const { icon: Icon, className } = STUDY_ICONS[status]
  return <Icon aria-hidden className={`size-4 shrink-0 ${className}`} />
}
