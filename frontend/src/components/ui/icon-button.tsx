import type { LucideIcon } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router'

import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * Pulsante a icona del design 4.2: 34 px su PC, 44 px sul telefono (--control-size), icona a
 * tratto da 18 px, suggerimento al passaggio e al focus. Il testo del suggerimento è anche il
 * nome accessibile. Se non è disponibile resta visibile e raggiungibile, con il motivo nel
 * suggerimento (aria-disabled, non disabled: il focus serve a leggerlo).
 */
export type IconVariant = 'ghost' | 'solid' | 'rail'

function iconButtonClass({ variant = 'ghost', active = false, className }: { variant?: IconVariant; active?: boolean; className?: string } = {}) {
  return cn(
    'relative inline-flex size-(--control-size) min-w-(--control-size) shrink-0 cursor-pointer items-center justify-center rounded-md text-foreground transition-[background-color,box-shadow] duration-150',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&_svg]:size-[18px] [&_svg]:shrink-0 [&_svg]:stroke-[1.7]',
    'aria-disabled:cursor-default aria-disabled:opacity-40 aria-disabled:hover:bg-transparent',
    variant === 'solid'
      ? 'bg-accent text-accent-foreground hover:shadow-[inset_0_0_0_1px_var(--acc)]'
      : active
        ? variant === 'rail'
          ? 'bg-accent text-accent-foreground'
          : 'bg-muted'
        : 'hover:bg-muted',
    className,
  )
}

type Common = {
  label: string
  icon: LucideIcon
  /** Dove compare il suggerimento. */
  side?: 'top' | 'right' | 'bottom'
  variant?: IconVariant
  active?: boolean
  /** Se c'è, il pulsante non è disponibile e il suggerimento dice perché. */
  unavailable?: string | null
  badge?: ReactNode
}

export function IconButton({ label, icon: Icon, side = 'bottom', variant, active, unavailable, badge, className, onClick, ...props }: Common & Omit<ComponentProps<'button'>, 'children'>) {
  return (
    <Tooltip content={unavailable ? `${label}: ${unavailable}` : label} side={side} describe={!!unavailable}>
      {(trigger) => (
        <button
          type="button"
          aria-label={label}
          aria-disabled={unavailable ? true : undefined}
          className={iconButtonClass({ variant, active, className })}
          {...props}
          {...trigger}
          onClick={unavailable ? (event) => event.preventDefault() : onClick}
        >
          <Icon aria-hidden />
          {badge}
        </button>
      )}
    </Tooltip>
  )
}

export function IconLink({ label, icon: Icon, side = 'bottom', variant, active, unavailable, badge, className, ...props }: Common & Omit<LinkProps, 'children'>) {
  if (unavailable) return <IconButton label={label} icon={Icon} side={side} variant={variant} unavailable={unavailable} className={className} />
  return (
    <Tooltip content={label} side={side} describe={false}>
      {(trigger) => (
        <Link aria-label={label} aria-current={active ? 'page' : undefined} className={iconButtonClass({ variant, active, className })} {...props} {...trigger}>
          <Icon aria-hidden />
          {badge}
        </Link>
      )}
    </Tooltip>
  )
}

/** Come IconLink, per i download (href all'API, attributo download). */
export function IconAnchor({ label, icon: Icon, side = 'bottom', variant, unavailable, className, ...props }: Omit<Common, 'active' | 'badge'> & Omit<ComponentProps<'a'>, 'children'>) {
  if (unavailable) return <IconButton label={label} icon={Icon} side={side} variant={variant} unavailable={unavailable} className={className} />
  return (
    <Tooltip content={label} side={side} describe={false}>
      {(trigger) => (
        <a aria-label={label} className={iconButtonClass({ variant, className })} {...props} {...trigger}>
          <Icon aria-hidden />
        </a>
      )}
    </Tooltip>
  )
}
