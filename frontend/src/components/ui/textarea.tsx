import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return <textarea className={cn('w-full rounded-md border border-input bg-card p-3 text-body focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50', className)} {...props} />
}
