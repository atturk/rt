import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

export type SlideOption<T extends string> = { value: T; label: string; icon?: ReactNode }

/**
 * Selettore a slitta (due o più stati): una pista arrotondata con un cursore che scorre sotto
 * l'opzione scelta. È un radiogroup: Tab entra sull'opzione scelta, le frecce (e Home/Fine)
 * cambiano scelta. `description` è il testo sotto la pista, collegato con aria-describedby.
 */
export function SlideToggle<T extends string>({
  label,
  options,
  value,
  onChange,
  description,
  disabled = false,
  className,
  testId,
}: {
  label: string
  options: SlideOption<T>[]
  value: T
  onChange: (value: T) => void
  description?: ReactNode
  disabled?: boolean
  className?: string
  testId?: string
}) {
  const descriptionId = useId()
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const index = Math.max(0, options.findIndex((o) => o.value === value))

  function select(i: number) {
    const next = (i + options.length) % options.length
    onChange(options[next].value)
    refs.current[next]?.focus()
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const keys: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowDown: index + 1,
      ArrowLeft: index - 1,
      ArrowUp: index - 1,
      Home: 0,
      End: options.length - 1,
    }
    if (e.key in keys) {
      e.preventDefault()
      select(keys[e.key])
    }
  }

  return (
    <div className={cn('flex flex-col gap-1.5', className)} data-testid={testId} data-value={value}>
      <div
        role="radiogroup"
        aria-label={label}
        aria-describedby={description ? descriptionId : undefined}
        aria-disabled={disabled || undefined}
        className={cn(
          'relative grid rounded-full border border-input bg-muted p-1 shadow-inner',
          disabled && 'cursor-not-allowed opacity-50',
        )}
        style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
      >
        <span
          aria-hidden="true"
          data-slot="thumb"
          className="pointer-events-none absolute inset-y-1 left-1 rounded-full bg-primary shadow-md transition-transform duration-300 ease-[cubic-bezier(0.34,1.4,0.64,1)] motion-reduce:transition-none"
          style={{ width: `calc((100% - 0.5rem) / ${options.length})`, transform: `translateX(${index * 100}%)` }}
        />
        {options.map((option, i) => {
          const checked = i === index
          return (
            <button
              key={option.value}
              ref={(el) => {
                refs.current[i] = el
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              disabled={disabled}
              onClick={() => onChange(option.value)}
              onKeyDown={onKeyDown}
              className={cn(
                'relative z-10 inline-flex h-8 items-center justify-center gap-1.5 rounded-full px-3 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed [&_svg]:size-4 [&_svg]:shrink-0',
                checked ? 'text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {option.icon}
              {option.label}
            </button>
          )
        })}
      </div>
      {description && (
        <p id={descriptionId} className="text-xs text-muted-foreground" aria-live="polite">
          {description}
        </p>
      )}
    </div>
  )
}
