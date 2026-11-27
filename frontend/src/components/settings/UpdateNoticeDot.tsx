import { cn } from '@/lib/utils'
import { UPDATE_NOTICE_LABELS, useUpdateNotice } from './useAppUpdate'

/** Pallino di avviso aggiornamento (stesso stile del badge dei Job, colore primario). */
export function UpdateNoticeDot({ className }: { className?: string }) {
  const { notice } = useUpdateNotice()
  if (!notice) return null
  return (
    <span
      aria-label={UPDATE_NOTICE_LABELS[notice]}
      data-testid="update-notice-dot"
      className={cn('inline-block size-2.5 shrink-0 rounded-full bg-primary', className)}
    />
  )
}
