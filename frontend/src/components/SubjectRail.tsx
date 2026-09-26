import { useEffect, useEffectEvent, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { NavLink, useLocation } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import { SubjectIcon } from '@/components/SubjectIcon'
import { Tooltip } from '@/components/ui/tooltip'
import { groupBySubject, lessonTitle, type Lesson } from '@/lib/format'
import { subjectIcons, subjectKey } from '@/lib/subjectIcon'
import { cn } from '@/lib/utils'

const PANEL_WIDTH = 288
const PANEL_MARGIN = 8

/**
 * Barra laterale ridotta: una icona per materia. Il nome completo compare al passaggio e al
 * focus; il clic (o Invio) apre accanto un pannello con le lezioni della materia, senza
 * espandere la barra. Frecce su/giù, Home e Fine passano fra le materie; Esc chiude il pannello.
 */
export function SubjectRail({ onNavigate }: { onNavigate?: () => void }) {
  const lessons = useLessons()
  const groups = useMemo(() => groupBySubject(lessons.data ?? []), [lessons.data])
  const icons = useMemo(() => subjectIcons(groups.map(([subject]) => subject)), [groups])
  // Materia con il pannello aperto e posizione del suo pulsante (per mettere il pannello accanto).
  const [open, setOpen] = useState<{ subject: string; top: number; right: number } | null>(null)
  const nav = useRef<HTMLElement>(null)
  const button = (subject: string) =>
    nav.current?.querySelector<HTMLButtonElement>(`button[data-subject="${CSS.escape(subject)}"]`)
  const activeId = Number(/^\/lezioni\/(\d+)/.exec(useLocation().pathname)?.[1] ?? NaN)

  function focusAt(index: number) {
    const subject = groups[(index + groups.length) % groups.length]?.[0]
    if (subject) button(subject)?.focus()
  }

  function onKey(e: KeyboardEvent, index: number) {
    const moves: Record<string, number> = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: groups.length - 1 }
    if (e.key in moves) {
      e.preventDefault()
      focusAt(moves[e.key])
    }
  }

  function close(subject: string, refocus: boolean) {
    setOpen((current) => (current?.subject === subject ? null : current))
    if (refocus) button(subject)?.focus()
  }

  return (
    <nav ref={nav} aria-label="Materie" className="flex flex-col items-center gap-2">
      {lessons.isPending && <p className="sr-only">Carico le lezioni…</p>}
      {lessons.isError && (
        <p className="text-center text-[10px] text-danger" title={errorMessage(lessons.error)}>
          Errore
        </p>
      )}
      <ul className="flex flex-col items-center gap-2">
        {groups.map(([subject, items], index) => {
          const icon = icons.get(subjectKey(subject))
          if (!icon) return null
          const current = items.some((l) => l.id === activeId)
          const isOpen = open?.subject === subject
          return (
            <li key={subject}>
              <Tooltip content={subject} side="right" describe={false} disabled={isOpen}>
                {(props) => (
                  <button
                    type="button"
                    {...props}
                    aria-label={`${subject}: ${items.length} ${items.length === 1 ? 'lezione' : 'lezioni'}${current ? ', lezione aperta' : ''}`}
                    aria-expanded={isOpen}
                    aria-haspopup="dialog"
                    data-subject={subject}
                    onClick={(e) => {
                      const r = e.currentTarget.getBoundingClientRect()
                      setOpen(isOpen ? null : { subject, top: r.top, right: r.right })
                    }}
                    onKeyDown={(e) => {
                      props.onKeyDown(e)
                      onKey(e, index)
                    }}
                    className={cn(
                      'rounded-xl p-0.5 outline-offset-2 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring',
                      (current || isOpen) && 'bg-muted ring-2 ring-accent-foreground',
                    )}
                  >
                    <SubjectIcon icon={icon} />
                  </button>
                )}
              </Tooltip>
              {open && isOpen && (
                <SubjectPanel
                  subject={subject}
                  lessons={items}
                  anchor={open}
                  onClose={(refocus) => close(subject, refocus)}
                  onNavigate={() => {
                    setOpen(null)
                    onNavigate?.()
                  }}
                />
              )}
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function SubjectPanel({
  subject,
  lessons,
  anchor,
  onClose,
  onNavigate,
}: {
  subject: string
  lessons: Lesson[]
  anchor: { top: number; right: number }
  onClose: (refocus: boolean) => void
  onNavigate: () => void
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const maxTop = Math.max(PANEL_MARGIN, window.innerHeight - 360)
  const pos = { top: Math.min(Math.max(PANEL_MARGIN, anchor.top), maxTop), left: anchor.right + 12 }
  const isOwnButton = (node: Node | null) =>
    node instanceof Element && node.closest('[data-subject]')?.getAttribute('data-subject') === subject

  const onOutside = useEffectEvent((e: PointerEvent) => {
    const target = e.target as Node
    // Il pulsante della materia chiude da sé (toggle); ogni altro clic fuori chiude il pannello.
    if (!panel.current?.contains(target) && !isOwnButton(target)) onClose(false)
  })
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>('a')?.focus()
    document.addEventListener('pointerdown', onOutside)
    return () => document.removeEventListener('pointerdown', onOutside)
  }, [])

  return (
    <div
      ref={panel}
      role="dialog"
      aria-labelledby={titleId}
      data-testid="subject-panel"
      className="fixed z-50 flex flex-col overflow-hidden rounded-xl border bg-card text-foreground shadow-xl"
      style={{ top: pos.top, left: pos.left, width: PANEL_WIDTH, maxHeight: `calc(100dvh - ${pos.top + PANEL_MARGIN}px)` }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          onClose(true)
        }
      }}
      onBlur={(e) => {
        const next = e.relatedTarget as Node | null
        if (next && !panel.current?.contains(next) && !isOwnButton(next)) onClose(false)
      }}
    >
      <h2 id={titleId} className="border-b px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
        {subject}
      </h2>
      <ul className="flex flex-col overflow-y-auto p-1.5 text-sm">
        {lessons.map((lesson) => (
          <li key={lesson.id}>
            <NavLink
              to={`/lezioni/${lesson.id}`}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex flex-col gap-0.5 rounded-lg px-2.5 py-2 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring',
                  isActive && 'bg-accent text-accent-foreground',
                )
              }
            >
              <span className="text-[11px] text-muted-foreground">{lesson.data || 'Senza data'}</span>
              <span className="text-xs font-semibold leading-snug">{lessonTitle(lesson)}</span>
              {lesson.pending_issues > 0 && <span className="text-[11px] text-accent-foreground">{lesson.pending_issues} da rivedere</span>}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  )
}
