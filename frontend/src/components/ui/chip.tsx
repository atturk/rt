import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/utils'

const chipVariants = cva(
  'inline-flex items-center justify-center gap-1.5 rounded-full text-meta font-medium transition-colors cursor-pointer disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-ring',
  {
    variants: {
      active: {
        true: 'bg-primary text-primary-foreground font-semibold',
        false: 'bg-muted text-foreground hover:bg-muted/80',
      },
      size: {
        default: 'h-7 px-3',
        sm: 'h-6 px-2.5',
      },
    },
    defaultVariants: { active: false, size: 'default' },
  },
)

export type ChipProps = React.ComponentProps<'button'> &
  VariantProps<typeof chipVariants>

export function Chip({ className, active, size, type = 'button', ...props }: ChipProps) {
  return (
    <button
      type={type}
      className={cn(chipVariants({ active, size }), className)}
      {...props}
    />
  )
}
