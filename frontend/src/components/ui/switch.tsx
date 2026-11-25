import { cn } from '@/lib/utils'

export function Switch({
  id,
  checked,
  onChange,
  disabled = false,
  label,
  className,
}: {
  id?: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  label?: string
  className?: string
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        'disabled:cursor-default disabled:opacity-50',
        checked ? 'bg-(--acc) dark:bg-(--success)' : 'border-border bg-muted',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none inline-block size-4 transform rounded-full shadow ring-0 transition duration-200 ease-in-out',
          checked ? 'translate-x-4 bg-white dark:bg-background' : 'translate-x-0 bg-white dark:bg-foreground/90',
        )}
      />
    </button>
  )
}
