import { useEffect, useRef } from 'react'

import { cn } from '@/lib/utils'

/** Casella del design (16 px, accento quando spuntata) con l'area da toccare più grande. */
export function Checkbox({ label, checked, indeterminate = false, disabled, className, onChange }: { label: string; checked: boolean; indeterminate?: boolean; disabled?: boolean; className?: string; onChange: (checked: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={(event) => onChange(event.target.checked)}
      className={cn(
        'relative size-4 shrink-0 cursor-pointer disabled:cursor-default disabled:opacity-50 appearance-none rounded-[4px] border border-muted-foreground bg-background',
        'before:absolute before:-inset-2.5 before:content-[""] max-md:before:-inset-3.5',
        'checked:border-accent-foreground checked:bg-accent indeterminate:border-accent-foreground indeterminate:bg-accent',
        'after:absolute checked:after:left-[4px] checked:after:top-[1px] checked:after:h-[9px] checked:after:w-[5px] checked:after:rotate-45 checked:after:border-accent-foreground checked:after:border-b-2 checked:after:border-r-2 checked:after:content-[""]',
        'indeterminate:after:inset-x-[3px] indeterminate:after:top-[6px] indeterminate:after:h-0.5 indeterminate:after:bg-accent-foreground indeterminate:after:content-[""]',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        className,
      )}
    />
  )
}
