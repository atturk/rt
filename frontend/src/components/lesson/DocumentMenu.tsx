import { BarChart3, Brain, Copy, Image, LayoutGrid, Play, SendHorizontal, ShieldCheck, Sparkles, X, type LucideIcon } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router'

import { errorMessage, type Schemas } from '@/api/client'
import { useEnrichmentActions } from '@/api/enrichment'
import { useRunJob } from '@/api/hooks'
import { useJob } from '@/api/jobs'
import { isActive } from '@/lib/jobs'
import { Card } from '@/components/ui/card'
import { IconButton } from '@/components/ui/icon-button'
import { Tooltip } from '@/components/ui/tooltip'
import { blockIndex, documentBlocks, partLabel, partOfRange } from '@/lib/documentParts'
import { OPEN_QUESTIONS_EVENT } from '@/lib/lessonPanel'
import { cn } from '@/lib/utils'

type Point = { x: number; y: number }
type Part = { text: string; units: string[]; at: Point; anchor: Point; range?: Range; reviewParts?: Schemas['ReviewPartSelection'][] }
/** La parte sotto il clic destro, per una superficie che non è l'<article> (l'editor). */
export type PartLocator = (event: MouseEvent) => Omit<Part, 'at'> | null
export type GenerateKind = 'visualization' | 'infographic' | 'image'

const NO_PART = "Seleziona il testo di un'unità"

/**
 * Menu contestuale della lezione (linee guida §3, schermata 02): sul testo selezionato o su un
 * titolo, Copia, Leggi da qui, Genera, Domande su questa parte, Verifica questa parte. "Questa
 * parte" sono le subunità toccate dalla selezione (lib/documentParts). Fuori dal testo e senza
 * selezione resta il menu del browser.
 */
export function DocumentMenu({ lessonId, unitIds, ready, locate, beforeReview, reviewUnavailable, children }: {
  lessonId: number
  unitIds: string[]
  /** Rielaborazione pronta per Genera e Domande; Verifica segue le unità della selezione. */
  ready: boolean
  /** Al posto della lettura dell'<article>: l'editor sa da sé testo e unità della selezione. */
  locate?: PartLocator
  beforeReview?: () => Promise<void>
  reviewUnavailable?: string | null
  children: ReactNode
}) {
  const [menu, setMenu] = useState<Part | null>(null)
  const [generate, setGenerate] = useState<Part | null>(null)
  const [queued, setQueued] = useState<string[] | null>(null)
  const run = useRunJob(lessonId)
  const [review, setReview] = useState<{ jobId?: string; unit: string; failure?: string } | null>(null)
  const [sending, setSending] = useState(false)
  const verify = async (part: Part) => {
    if (!part.reviewParts?.length || sending) return
    setSending(true)
    setReview({ unit: part.reviewParts[0].unit_id })
    try {
      await beforeReview?.()
      const accepted = await run.mutateAsync({ type: 'review_part', parts: part.reviewParts })
      setReview({ jobId: accepted.job_id, unit: part.reviewParts[0].unit_id })
    } catch (error) {
      setReview({ unit: part.reviewParts[0].unit_id, failure: errorMessage(error) })
    } finally { setSending(false) }
  }
  // Il documento (l'<article> del DocumentView) sta dentro questo contenitore.
  const root = useRef<HTMLDivElement>(null)
  const selectedBefore = useRef<Range | null | undefined>(undefined)

  const open = (event: MouseEvent) => {
    if (event.altKey) {
      setMenu(null)
      return
    }
    if (locate) {
      const part = locate(event)
      if (!part) return
      event.preventDefault()
      setMenu({ ...part, at: { x: event.clientX, y: event.clientY } })
      return
    }
    const article = root.current?.querySelector('article')
    if (!article) return
    const selection = window.getSelection()
    const range = selectedBefore.current === undefined
      ? selection && !selection.isCollapsed && selection.rangeCount ? selection.getRangeAt(0) : null
      : selectedBefore.current
    selectedBefore.current = undefined
    const inside = range && article.contains(range.commonAncestorContainer)
    const target = event.target as HTMLElement
    if (!article.contains(target)) return
    let block = target.closest('h1, h2, h3, h4, p, li, pre, blockquote, td')
    if (!block || !article.contains(block)) block = target === article ? article.firstElementChild : target
    const text = inside && range ? range.toString() : ''
    event.preventDefault()
    const blocks = documentBlocks(article, unitIds)
    const [from, to] = text.trim() && range
      ? [blockIndex(article, range.startContainer), blockIndex(article, range.endContainer)]
      : [blockIndex(article, block), blockIndex(article, block)]
    const units = from < 0 || to < 0 ? [] : partOfRange(blocks, from, to, unitIds)
    const rect = text.trim() && range ? range.getBoundingClientRect() : block!.getBoundingClientRect()
    setMenu({
      text: text.trim() ? text : (block?.textContent ?? '').trim(),
      units,
      at: { x: event.clientX, y: event.clientY },
      anchor: { x: rect.left, y: rect.bottom },
      range: text.trim() && range ? range.cloneRange() : undefined,
    })
  }

  const unavailable = (part: Part) => (!ready ? 'serve prima la rielaborazione della lezione' : part.units.length === 0 ? NO_PART : null)

  return (
    <div ref={root} onContextMenu={open} onMouseDownCapture={(event) => {
      if (event.altKey || !(event.button === 2 || (event.button === 0 && event.ctrlKey))) return
      const article = root.current?.querySelector('article')
      if (!article?.contains(event.target as Node)) return
      const selection = window.getSelection()
      selectedBefore.current = selection && !selection.isCollapsed && selection.rangeCount
        ? selection.getRangeAt(0).cloneRange() : null
    }} data-testid="document-surface">
      {queued && (
        <div role="status" className="mb-4 flex items-center gap-2 rounded-md border px-3 py-2 text-meta" data-testid="generate-queued">
          <Sparkles className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">
            Richiesta inviata{queued.length ? ` per ${partLabel(queued)}` : ''}: l'elemento si prepara in{' '}
            <Link to={`/lezioni/${lessonId}?panel=arricchimento`} className="font-semibold text-link underline-offset-2 hover:underline">Arricchimento</Link>.
          </span>
          <IconButton label="Chiudi" icon={X} onClick={() => setQueued(null)} className="-my-1.5 -mr-2" />
        </div>
      )}
      {children}
      {review && <PartReviewNotice lessonId={lessonId} {...review} onClose={() => setReview(null)} />}
      {menu && (
        <ContextMenu
          at={menu.at}
          onClose={() => setMenu(null)}
          items={[
            { label: 'Copia', icon: Copy, onSelect: () => void copy(menu.text) },
            { label: 'Leggi da qui', icon: Play, unavailable: 'In arrivo' },
            { label: 'Genera', icon: Sparkles, unavailable: unavailable(menu), onSelect: () => setGenerate(menu) },
            {
              label: menu.units.length > 1 ? `Domande sulle unità ${menu.units[0]}–${menu.units.at(-1)}` : `Domande sull'unità ${menu.units[0] ?? ''}`,
              icon: Brain,
              unavailable: unavailable(menu),
              onSelect: () => window.dispatchEvent(new CustomEvent(OPEN_QUESTIONS_EVENT, { detail: { units: menu.units, text: menu.text } })),
            },
            {
              label: 'Verifica questa parte',
              icon: ShieldCheck,
              unavailable: reviewUnavailable || (sending ? 'Invio in corso' : !menu.reviewParts?.length ? NO_PART : null),
              onSelect: () => void verify(menu),
            },
          ]}
        />
      )}
      {generate && <GeneratePopover lessonId={lessonId} part={generate} onClose={() => setGenerate(null)} onQueued={() => setQueued(generate.units)} />}
    </div>
  )
}

/** In basso resta visibile anche se la selezione è lontana dall'inizio del documento. */
function PartReviewNotice({ lessonId, jobId, unit, failure, onClose }: { lessonId: number; jobId?: string; unit: string; failure?: string; onClose: () => void }) {
  const job = useJob(jobId ?? '')
  const error = failure ?? (job.data?.state === 'failed' ? job.data.error : job.isError ? errorMessage(job.error) : null)
  const finished = !!job.data && !isActive(job.data.state)
  const count = typeof job.data?.result?.issues === 'number' ? job.data.result.issues : 0
  return <Card role={error ? 'alert' : 'status'} data-testid="part-review-notice" className="fixed inset-x-3 bottom-4 z-40 mx-auto flex max-w-xl items-center gap-2 px-3 py-2 text-meta shadow-panel">
    <ShieldCheck className="size-4 shrink-0" aria-hidden />
    <span className="flex-1">{error || (job.data?.state === 'cancelled' ? 'Verifica annullata' : finished ? `${count} issue trovate` : 'Verifica in corso…')}
      {!error && finished && job.data?.state === 'succeeded' && <> · <Link to={`/lezioni/${lessonId}?panel=verifica&review_unit=${encodeURIComponent(unit)}`} className="font-semibold text-link hover:underline">Apri Verifica</Link></>}
    </span>
    <IconButton label="Chiudi l’avviso di verifica" icon={X} onClick={onClose} />
  </Card>
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Senza permesso per gli appunti (http, iframe): la selezione c'è ancora, la copia il browser.
    document.execCommand('copy')
  }
}

type MenuItem = { label: string; icon: LucideIcon; onSelect?: () => void; unavailable?: string | null }

/** Menu posato dove si è fatto clic destro (schermata 02, .slash): frecce, Esc e clic fuori. */
function ContextMenu({ at, items, onClose }: { at: Point; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState(at)
  const returnFocus = useRef<Element | null>(null)
  useLayoutEffect(() => {
    returnFocus.current = document.activeElement
    const el = ref.current
    if (!el) return
    // Dentro la finestra anche vicino ai bordi.
    const { width, height } = el.getBoundingClientRect()
    setPos({ x: Math.max(8, Math.min(at.x, window.innerWidth - width - 8)), y: Math.max(8, Math.min(at.y, window.innerHeight - height - 8)) })
    el.querySelector<HTMLElement>('[role=menuitem]')?.focus({ preventScroll: true })
  }, [at])
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const onScroll = () => onClose()
    document.addEventListener('pointerdown', onPointer)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [onClose])
  const close = () => {
    onClose()
    if (returnFocus.current instanceof HTMLElement) returnFocus.current.focus({ preventScroll: true })
  }
  const onKeyDown = (event: KeyboardEvent) => {
    const all = Array.from(ref.current?.querySelectorAll<HTMLElement>('[role=menuitem]') ?? [])
    const index = all.indexOf(document.activeElement as HTMLElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      all[(index + (event.key === 'ArrowDown' ? 1 : -1) + all.length) % all.length]?.focus()
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      all[event.key === 'Home' ? 0 : all.length - 1]?.focus()
    } else if (event.key === 'Tab') onClose()
  }
  return createPortal(
    <div
      ref={ref}
      role="menu"
      aria-label="Azioni sul testo"
      data-testid="document-menu"
      onKeyDown={onKeyDown}
      style={{ left: pos.x, top: pos.y }}
      className="fixed z-50 w-[272px] max-w-[calc(100vw-24px)] rounded-lg border bg-card p-1.5 text-body shadow-panel"
    >
      {items.map(({ label, icon: Icon, onSelect, unavailable }) => (
        <Tooltip key={label} content={unavailable ? `${label}: ${unavailable}` : label} side="right" disabled={!unavailable}>
          {(trigger) => (
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              aria-disabled={unavailable ? true : undefined}
              className={cn(
                'flex min-h-10 w-full items-center gap-2.5 rounded-md px-2.5 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring max-md:min-h-11',
                '[&_svg]:size-[18px] [&_svg]:shrink-0 [&_svg]:stroke-[1.7]',
                unavailable && 'cursor-default text-muted-foreground hover:bg-transparent',
              )}
              onClick={() => {
                if (unavailable || !onSelect) return
                onClose()
                onSelect()
              }}
              {...trigger}
            >
              <Icon aria-hidden />
              {label}
              {unavailable === 'In arrivo' && <span className="ml-auto rounded-full border px-2 text-meta">In arrivo</span>}
            </button>
          )}
        </Tooltip>
      ))}
      <p className="border-t px-2.5 pt-1.5 text-[11px] text-muted-foreground">⌥ + clic destro: menu del browser</p>
    </div>,
    document.body,
  )
}

const KINDS: { kind: GenerateKind; label: string; icon: LucideIcon; placeholder: string }[] = [
  { kind: 'visualization', label: 'Grafico (visualizer)', icon: BarChart3, placeholder: 'Che tipo di elemento grafico vuoi vedere?' },
  { kind: 'infographic', label: 'Infografica', icon: LayoutGrid, placeholder: 'Quale infografica vuoi vedere?' },
  { kind: 'image', label: 'Immagine IA', icon: Image, placeholder: 'Quale immagine vuoi vedere?' },
]

/**
 * Popup Genera (schermata 02b) vicino alla selezione: tipo con le icone, "Cosa vuoi vedere?",
 * invio. Il regista (fase enrichment_writer) scrive il prompt dalla richiesta, dalla selezione e
 * dall'unità madre; l'elemento compare dopo l'ultima subunità toccata, con il suo avanzamento.
 */
function GeneratePopover({ lessonId, part, onClose, onQueued }: { lessonId: number; part: Part; onClose: () => void; onQueued: () => void }) {
  const [kind, setKind] = useState<GenerateKind>('visualization')
  const [request, setRequest] = useState('')
  const { generate } = useEnrichmentActions(lessonId)
  const ref = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  const [pos, setPos] = useState(part.anchor)
  const titleId = useId()
  const current = KINDS.find((k) => k.kind === kind)!
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const below = part.anchor.y + 8
    const y = below + height > window.innerHeight - 8 ? Math.max(8, part.anchor.y - height - 40) : below
    setPos({ x: Math.max(8, Math.min(part.anchor.x, window.innerWidth - width - 8)), y })
    field.current?.focus()
  }, [part.anchor])
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [onClose])
  // Il focus passa al campo e il browser toglie la selezione: la si ridisegna (CSS Custom Highlight).
  useEffect(() => {
    if (!part.range || typeof Highlight === 'undefined' || typeof CSS === 'undefined' || !CSS.highlights) return
    // HighlightRegistry è un Map (maplike), ma i tipi DOM di TypeScript non lo dicono.
    const registry = CSS.highlights as unknown as Map<string, Highlight>
    registry.set('rt-generate', new Highlight(part.range))
    return () => {
      registry.delete('rt-generate')
    }
  }, [part.range])
  const submit = () => {
    if (!request.trim() || generate.isPending) return
    generate.mutate({ kind, request: request.trim(), selection: part.text, unit_ids: part.units }, {
      onSuccess: () => {
        onQueued()
        onClose()
      },
    })
  }
  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-labelledby={titleId}
      data-testid="generate-popover"
      style={{ left: pos.x, top: pos.y }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          onClose()
        }
      }}
      className="fixed z-50 w-[380px] max-w-[calc(100vw-24px)] rounded-lg border bg-card p-2.5 shadow-panel"
    >
      <h2 id={titleId} className="sr-only">Genera</h2>
      <div className="flex items-center gap-0.5">
        <div role="group" aria-label="Tipo di elemento" className="flex rounded-md bg-muted p-0.5">
          {KINDS.map((k) => (
            <IconButton
              key={k.kind}
              label={k.label}
              icon={k.icon}
              aria-pressed={kind === k.kind}
              className={cn('hover:bg-card', kind === k.kind && 'bg-card shadow-[0_1px_3px_color-mix(in_oklch,var(--fg)_10%,transparent)]')}
              onClick={() => setKind(k.kind)}
            />
          ))}
        </div>
        <span className="flex-1" />
        <IconButton label="Chiudi" icon={X} onClick={onClose} />
      </div>
      <textarea
        ref={field}
        value={request}
        onChange={(event) => setRequest(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit()
        }}
        placeholder={current.placeholder}
        aria-label={current.placeholder}
        maxLength={2000}
        className="my-2 block min-h-16 w-full resize-y rounded-md border bg-card px-3 py-2.5 text-meta text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
      />
      {generate.isError && <p role="alert" className="mb-2 text-meta text-danger">{errorMessage(generate.error)}</p>}
      <div className="flex items-center justify-end gap-2">
        <span className="mr-auto text-meta text-muted-foreground">{partLabel(part.units)}</span>
        <IconButton label="Genera" icon={SendHorizontal} variant="solid" onClick={submit} unavailable={request.trim() ? null : 'scrivi cosa vuoi vedere'} />
      </div>
    </div>,
    document.body,
  )
}
