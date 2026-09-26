import * as React from 'react'

import { cn } from '@/lib/utils'

/** Select nativo con lo stile dei componenti shadcn: accessibile e testabile senza portali. */
export function Select({ className, ...props }: React.ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-9 w-full rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
        className,
      )}
      {...props}
    />
  )
}
