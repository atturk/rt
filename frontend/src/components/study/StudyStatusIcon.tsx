import { useSettings } from '@/api/settings'
import { resolveStudyStatus, type CustomStudyStatus } from './studyProgress'

export function StudyStatusIcon({ status = 'da-imparare' }: { status?: string }) {
  const settings = useSettings()
  const customStatuses = settings.data?.stati_studio as CustomStudyStatus[] | undefined
  const { icon: Icon, className } = resolveStudyStatus(status, customStatuses)
  return <Icon aria-hidden className={`size-4 shrink-0 ${className}`} />
}
