import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** Suggerimento breve che compare al passaggio del mouse o al focus sul contenuto. Il testo è
 * anche nel DOM con role="tooltip": chi lo usa collega il controllo con aria-describedby={id}. */
export function Tooltip({
  id,
  content,
  children,
  className,
  bubbleClassName,
}: {
  id: string
  content: string
  children: ReactNode
  className?: string
  bubbleClassName?: string
}) {
  return (
    <span className={cn('group/tip relative inline-flex', className)}>
      {children}
      <span
        id={id}
        role="tooltip"
        className={cn(
          'pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 hidden w-max max-w-64 rounded-md bg-primary px-2 py-1 text-[11px] font-normal leading-snug text-primary-foreground shadow group-focus-within/tip:block group-hover/tip:block',
          bubbleClassName,
        )}
      >
        {content}
      </span>
    </span>
  )
}
