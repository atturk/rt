import { cn } from '@/lib/utils'
import { UPDATE_NOTICE_LABELS, useUpdateNotice } from './useAppUpdate'
import { useComponentNotice } from './useComponentNotice'

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

/** Pallino di avviso quando il motore/modello di trascrizione necessario non è pronto né in download. */
export function ComponentNoticeDot({ className }: { className?: string }) {
  const { missing, label } = useComponentNotice()
  if (!missing || !label) return null
  return (
    <span
      aria-label={label}
      data-testid="component-notice-dot"
      className={cn('inline-block size-2.5 shrink-0 rounded-full bg-primary', className)}
    />
  )
}
