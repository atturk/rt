import { ChevronLeft } from 'lucide-react'
import type { ReactNode } from 'react'

import { IconButton, IconLink } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'

/**
 * Intestazione di pagina del design 4.2 (52 px): titolo o percorso a sinistra, azioni della
 * pagina come icone a destra, freccia per tornare indietro a sinistra del titolo. Sul telefono
 * il titolo è grande e le azioni vanno a capo se serve.
 */
export function PageHeader({ title, back, actions, muted = false, titleAs: Title = 'h1', className }: {
  title: ReactNode
  /** p quando l'h1 è il titolo del documento sotto (pagina della lezione). */
  titleAs?: 'h1' | 'p'
  /** Freccia indietro: una pagina (to) o un ritorno dentro la stessa schermata (onClick). */
  back?: { to: string; label: string; state?: unknown } | { onClick: () => void; label: string }
  actions?: ReactNode
  /** Titolo grigio (il percorso sopra il titolo del documento, schermata 03). */
  muted?: boolean
  className?: string
}) {
  return (
    <header
      className={cn(
        'sticky top-0 z-20 flex min-h-(--header-height) items-center gap-2 border-b bg-background px-5',
        'max-md:min-h-16 max-md:flex-wrap max-md:px-4 max-md:py-2',
        className,
      )}
    >
      {back && ('to' in back
        ? <IconLink to={back.to} state={back.state} label={back.label} icon={ChevronLeft} className="-ml-2" />
        : <IconButton onClick={back.onClick} label={back.label} icon={ChevronLeft} className="-ml-2" />)}
      <Title
        className={cn(
          'min-w-0 flex-1 truncate text-[15px] leading-snug',
          muted ? 'font-medium text-muted-foreground' : 'font-semibold max-md:text-heading',
        )}
      >
        {title}
      </Title>
      {actions}
    </header>
  )
}

/** Contenuto delle pagine che non hanno ancora il design 4.2: margini come prima. */
export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8', className)}>{children}</div>
}
