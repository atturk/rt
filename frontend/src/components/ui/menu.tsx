import { Check, type LucideIcon } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import { Tooltip } from '@/components/ui/tooltip'
import { IconButton } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'

export type MenuSection = { label: string; items: { label: string; checked: boolean; onSelect: () => void }[] }

/**
 * Pulsante a icona con un menu di scelte (Ordina; Raggruppa sul telefono). Frecce su e giù
 * fra le voci, Esc e clic fuori chiudono e il focus torna al pulsante.
 */
export function MenuButton({ label, icon, sections, className }: { label: string; icon: LucideIcon; sections: MenuSection[]; className?: string }) {
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const root = useRef<HTMLDivElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  const close = (refocus: boolean) => {
    setOpen(false)
    if (refocus) root.current?.querySelector<HTMLButtonElement>('button[aria-haspopup]')?.focus()
  }

  useEffect(() => {
    if (!open) return
    const items = menu.current?.querySelectorAll<HTMLElement>('[role=menuitemradio]')
    const checked = Array.from(items ?? []).find((item) => item.getAttribute('aria-checked') === 'true')
    ;(checked ?? items?.[0])?.focus()
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])

  const onKeyDown = (event: KeyboardEvent) => {
    const items = Array.from(menu.current?.querySelectorAll<HTMLElement>('[role=menuitemradio]') ?? [])
    const index = items.indexOf(document.activeElement as HTMLElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close(true)
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const next = (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
      items[next]?.focus()
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      items[event.key === 'Home' ? 0 : items.length - 1]?.focus()
    } else if (event.key === 'Tab') setOpen(false)
  }

  return (
    <div ref={root} className={cn('relative', className)}>
      <IconButton label={label} icon={icon} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} active={open} onClick={() => setOpen(!open)} />
      {open && (
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onKeyDown}
          className="absolute right-0 top-full z-30 mt-1.5 w-56 rounded-lg border bg-card p-1.5 text-body shadow-panel"
        >
          {sections.map((section) => (
            <div key={section.label} role="group" aria-label={section.label} className="py-0.5">
              {sections.length > 1 && <p className="px-2.5 pb-1 pt-1.5 text-meta font-semibold uppercase tracking-[.045em] text-muted-foreground" aria-hidden>{section.label}</p>}
              {section.items.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  role="menuitemradio"
                  aria-checked={item.checked}
                  tabIndex={-1}
                  onClick={() => {
                    item.onSelect()
                    close(true)
                  }}
                  className="flex min-h-10 w-full items-center gap-2.5 rounded-md px-2.5 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
                >
                  <Check className={cn('size-4 shrink-0', !item.checked && 'invisible')} aria-hidden />
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export type LinkMenuItem = { label: string; href?: string; download?: boolean; title?: string; unavailable?: string | null;
  checked?: boolean; onSelect?: () => void }

/**
 * Pulsante a icona con un menu di link (Esporta: Markdown, zip). Stessa tastiera di MenuButton;
 * una voce non disponibile resta nel menu con il motivo (aria-disabled).
 */
export function LinkMenuButton({ label, icon, items, className, side = 'bottom', unavailable }: {
  label: string; icon: LucideIcon; items: LinkMenuItem[]; className?: string; side?: 'top' | 'bottom'; unavailable?: string | null
}) {
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const root = useRef<HTMLDivElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const close = (refocus: boolean) => {
    setOpen(false)
    if (refocus) root.current?.querySelector<HTMLButtonElement>('button[aria-haspopup]')?.focus()
  }
  useEffect(() => {
    if (!open) return
    menu.current?.querySelector<HTMLElement>('[role^=menuitem]')?.focus()
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])
  const onKeyDown = (event: KeyboardEvent) => {
    const all = Array.from(menu.current?.querySelectorAll<HTMLElement>('[role^=menuitem]') ?? [])
    const index = all.indexOf(document.activeElement as HTMLElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close(true)
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      all[(index + (event.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length]?.focus()
    } else if (event.key === 'Tab') setOpen(false)
  }
  const itemClass = 'flex min-h-10 w-full items-center gap-2.5 rounded-md px-2.5 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring'
  return (
    <div ref={root} className={cn('relative', className)}>
      <IconButton label={label} icon={icon} side={side} unavailable={unavailable} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} active={open} onClick={() => setOpen(!open)} />
      {open && (
        <div ref={menu} id={menuId} role="menu" aria-label={label} onKeyDown={onKeyDown}
          className={cn('absolute right-0 z-30 w-60 rounded-lg border bg-card p-1.5 text-body shadow-panel',
            side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5')}>
          {items.map((item) =>
            item.unavailable ? (
              <Tooltip key={item.label} content={item.unavailable}>{(trigger) => <span {...trigger} role="menuitem" aria-disabled="true" tabIndex={-1} className={cn(itemClass, 'cursor-default opacity-50 hover:bg-transparent')}>
                {item.label}
                <span className="sr-only">: {item.unavailable}</span>
              </span>}</Tooltip>
            ) : item.onSelect ? (
              <button key={item.label} type="button" role={item.checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
                aria-checked={item.checked} tabIndex={-1} className={itemClass} onClick={() => {
                  item.onSelect?.()
                  if (item.checked === undefined) close(true)
                }}>
                {item.checked !== undefined && <Check aria-hidden className={cn('size-4 shrink-0', !item.checked && 'invisible')} />}
                {item.label}
              </button>
            ) : (
              <Tooltip key={item.label} content={item.title} disabled={!item.title}>{(trigger) => <a {...trigger} role="menuitem" tabIndex={-1} href={item.href} download={item.download} className={itemClass} onClick={() => close(false)}>
                {item.label}
              </a>}</Tooltip>
            ),
          )}
        </div>
      )}
    </div>
  )
}
