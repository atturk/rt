import { ReturnAddressContext, rememberReturnAddress, useReturnAddress } from '@/lib/returnAddress'
import { Activity, Calendar, Plus, Settings, type LucideIcon } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useMatches } from 'react-router'

import { ApiError } from '@/api/client'
import { useMe } from '@/api/hooks'
import { useLiveUpdates } from '@/api/liveUpdates'
import { JobsNavBadge } from '@/components/jobs/JobsIndicator'
import { PageBody } from '@/components/shell/PageHeader'
import { NewLessonContext } from '@/components/shell/newLesson'
import { IconButton, IconLink } from '@/components/ui/icon-button'
import { useIsPhone } from '@/lib/phone'
import { StudyZenContext, ZenContext, RsvpLayoutContext, IRLEN_COLORS, type RsvpLayoutState } from '@/lib/zen'
import { cn } from '@/lib/utils'

// Il popup si scarica quando lo si apre: non serve per mostrare la prima pagina.
const NewLessonDialog = lazy(() => import('@/components/lessons/NewLessonDialog').then((m) => ({ default: m.NewLessonDialog })))

type Section = { to: string; label: string; icon: LucideIcon; match: (path: string) => boolean; badge?: boolean }

/** Le tre voci del design 4.2 (linee guida §2); le pagine di prima restano raggiungibili dai link. */
const LESSONS: Section = {
  to: '/',
  label: 'Lezioni',
  icon: Calendar,
  match: (path) => path === '/' || /^\/(lezioni|studio|recall|review|immagini|arricchimento)(\/|$)/.test(path),
}
const JOBS: Section = { to: '/job', label: 'Job in corso', icon: Activity, match: (path) => /^\/(job|importa)(\/|$)/.test(path), badge: true }
const SETTINGS: Section = { to: '/impostazioni', label: 'Impostazioni', icon: Settings, match: (path) => /^\/(impostazioni|bot)(\/|$)/.test(path) }

function Badge() {
  return (
    <span className="pointer-events-none absolute -right-1 -top-1">
      <JobsNavBadge />
    </span>
  )
}

function NavItem({ section, path, side, variant }: { section: Section; path: string; side: 'right' | 'top'; variant: 'rail' | 'ghost' }) {
  const active = section.match(path)
  const returnAddress = useReturnAddress()
  return (
    <IconLink
      to={active && section !== LESSONS ? returnAddress : section.to}
      label={section.label}
      icon={section.icon}
      side={side}
      variant={variant}
      active={active}
      badge={section.badge ? <Badge /> : undefined}
    />
  )
}

export function Layout() {
  const studyZen = useState(false)
  const [rsvp, setRsvp] = useState<RsvpLayoutState>({ active: false, tint: null })
  const [zen, setZen] = useState<RsvpLayoutState>({ active: false, tint: null })
  const layout = rsvp.active ? rsvp : zen
  useEffect(() => {
    if (!layout.active || !layout.tint) return
    const existing = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    const meta = existing ?? document.createElement('meta')
    const previous = meta.getAttribute('content')
    meta.name = 'theme-color'
    meta.content = IRLEN_COLORS[layout.tint]
    if (!existing) document.head.append(meta)
    return () => {
      if (!existing) meta.remove()
      else if (previous === null) meta.removeAttribute('content')
      else meta.content = previous
    }
  }, [layout.active, layout.tint])
  const me = useMe()
  const location = useLocation()
  const matches = useMatches()
  const [returnAddress, setReturnAddress] = useState('/')
  useEffect(() => {
    // L'indirizzo vive solo nella sessione di navigazione: una ricarica usa Lezioni.
    // oxlint-disable-next-line react/set-state-in-effect
    setReturnAddress(previous => rememberReturnAddress(previous, location))
  }, [location])
  const [newLesson, setNewLesson] = useState(false)
  const openNewLesson = useCallback(() => setNewLesson(true), [])
  const closeNewLesson = useCallback(() => setNewLesson(false), [])
  const phone = useIsPhone()
  // Un solo canale live per tutta la pagina, aperto dopo l'accesso.
  useLiveUpdates(me.isSuccess)

  if (me.isError && me.error instanceof ApiError && me.error.status === 401) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (me.isPending) {
    return <p className="p-8 text-sm text-muted-foreground">Carico…</p>
  }
  if (me.isError) {
    return (
      <p role="alert" className="p-8 text-sm text-danger">
        {me.error.message}
      </p>
    )
  }

  // Le pagine del design 4.2 hanno la loro intestazione e vanno a tutta larghezza (handle.bare);
  // le altre restano nei margini di prima.
  const bare = matches.some((m) => (m.handle as { bare?: boolean } | undefined)?.bare)
  const path = location.pathname
  return (
    <ReturnAddressContext value={returnAddress}><StudyZenContext value={studyZen}><RsvpLayoutContext value={setRsvp}><ZenContext value={setZen}><NewLessonContext value={openNewLesson}>
      <div className="rt-layout flex min-h-dvh bg-background" data-rsvp={rsvp.active || undefined} data-zen={zen.active || undefined} data-tint={layout.active ? layout.tint ?? undefined : undefined}>
        {!phone && <nav
          aria-label="Navigazione" aria-hidden={layout.active || undefined} inert={layout.active || undefined}
          className="sticky top-0 hidden h-dvh w-(--rail-width) shrink-0 flex-col items-center gap-1.5 border-r bg-background py-3 md:flex"
        >
          <IconButton label="Nuova lezione" icon={Plus} side="right" variant="solid" onClick={openNewLesson} aria-haspopup="dialog" />
          <div className="h-2" aria-hidden />
          <NavItem section={LESSONS} path={path} side="right" variant="rail" />
          <div className="flex-1" aria-hidden />
          <NavItem section={JOBS} path={path} side="right" variant="rail" />
          <NavItem section={SETTINGS} path={path} side="right" variant="rail" />
        </nav>}

        <div className={cn('flex min-w-0 flex-1 flex-col', 'max-md:pb-[calc(64px+env(safe-area-inset-bottom))]')}>
          <main className="flex min-w-0 flex-1 flex-col">
            {/* Le pagine arrivano in chunk separati (routes/index.tsx): mentre si scarica il
                primo si vede questo; cambiando pagina resta quella vecchia finché la nuova è pronta. */}
            <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Carico…</p>}>
              {bare ? <Outlet /> : <PageBody><Outlet /></PageBody>}
            </Suspense>
          </main>
        </div>

        {/* Telefono: tre schede in basso (linee guida §2). */}
        {phone && <nav
          aria-label="Navigazione" aria-hidden={layout.active || undefined} inert={layout.active || undefined}
          className="fixed inset-x-0 bottom-0 z-50 flex min-h-16 items-center justify-around border-t bg-background pb-[max(8px,env(safe-area-inset-bottom))] pt-2 md:hidden"
        >
          {[LESSONS, JOBS, SETTINGS].map((section) => (
            <NavItem key={section.to} section={section} path={path} side="top" variant="ghost" />
          ))}
        </nav>}
      </div>
      {newLesson && (
        <Suspense fallback={null}>
          <NewLessonDialog open onClose={closeNewLesson} />
        </Suspense>
      )}
    </NewLessonContext></ZenContext></RsvpLayoutContext></StudyZenContext></ReturnAddressContext>
  )
}
