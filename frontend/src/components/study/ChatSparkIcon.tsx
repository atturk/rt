import { MessageSquare, Sparkles } from 'lucide-react'

import { cn } from '@/lib/utils'

/** Icona della Chat dello Studio: vignetta con dentro una stellina. */
export function ChatSparkIcon({ className }: { className?: string }) {
  return (
    <span className={cn('relative inline-flex size-[18px] items-center justify-center', className)} aria-hidden>
      <MessageSquare className="!size-full" />
      <Sparkles className="pointer-events-none absolute !size-[8px] -translate-y-[1px]" strokeWidth={2} />
    </span>
  )
}
