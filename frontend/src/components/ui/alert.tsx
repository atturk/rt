import * as React from 'react'

import { cn } from '@/lib/utils'

export function Alert({ className, tone = 'neutral', ...props }: React.ComponentProps<'div'> & { tone?: 'neutral' | 'danger' | 'warning' }) {
  const tones = { neutral: 'bg-muted text-muted-foreground', danger: 'bg-danger-soft text-danger', warning: 'bg-warning-soft text-warning' }
  return <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('rounded-lg px-3 py-2.5 text-sm', tones[tone], className)} {...props} />
}
