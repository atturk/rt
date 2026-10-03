import { useEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router'
import { errorMessage } from '@/api/client'
import { useEnrichment, useEnrichmentActions, type Element } from '@/api/enrichment'
import { kindLabel, assetUrl } from '@/lib/enrichment'
import { JobProgress } from '@/components/JobProgress'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'



export function GeneratedElement({ element, lessonId }: { element: Element; lessonId: number }) {
  if (!element.asset_image) return null
  return element.asset_html && (element.asset_mode ?? element.mode) === 'interactive'
    ? <InteractiveElement title={element.title} url={assetUrl(lessonId, element.asset_html)} />
    : <img src={assetUrl(lessonId, element.asset_image)} alt={element.title} className="w-full rounded-lg" loading="lazy" />
}

function InteractiveElement({ title, url }: { title: string; url: string }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const [height, setHeight] = useState(600)
  useEffect(() => {
    function resize(event: MessageEvent) {
      if (!frame.current?.contentWindow || event.source !== frame.current.contentWindow) return
      const data: unknown = event.data
      if (typeof data !== 'object' || data === null || !('type' in data) || !('height' in data)) return
      if (data.type === 'rt-enrichment-resize' && typeof data.height === 'number' && Number.isFinite(data.height))
        setHeight(Math.max(240, Math.min(4000, Math.ceil(data.height))))
    }
    window.addEventListener('message', resize)
    return () => window.removeEventListener('message', resize)
  }, [])
  return <iframe ref={frame} title={title} src={url} sandbox="allow-scripts" referrerPolicy="no-referrer"
    style={{ height }} className="w-full rounded-lg border bg-white" loading="lazy" />
}

export function EnrichmentCard({ element: e, lessonId, manage = false }: { element: Element; lessonId: number; manage?: boolean }) {
  const { generate, action, refresh } = useEnrichmentActions(lessonId)
  const busy = e.status === 'queued' || e.status === 'generating'
  return <section className="not-prose my-4 flex flex-col gap-3 rounded-lg border bg-card p-4" data-enrichment-id={e.id}>
    <div className="flex items-start justify-between gap-2">
      <div><p className="text-xs text-muted-foreground">{kindLabel(e.kind)} · {e.unit_id}{e.status === 'dismissed' ? ' · Ignorata' : ''}</p>
        <h4 className="font-semibold">{e.title}</h4></div>
      {!e.asset_image && !busy && e.status !== 'dismissed' && <Button variant="ghost" size="sm" aria-label={`Ignora ${e.title}`} disabled={action.isPending}
        onClick={() => action.mutate({ element: e.id, action: 'dismiss' })}>×</Button>}
    </div>
    {!e.asset_image && <p className="text-sm text-muted-foreground">{e.description}</p>}
    {e.stale && <Alert tone="warning">Il testo dell’unità è cambiato da quando è stata preparata questa idea.</Alert>}
    {e.asset_image && <GeneratedElement element={e} lessonId={lessonId} />}
    {busy && <div role="status" aria-live="polite" className="flex min-h-52 animate-pulse items-center justify-center rounded-lg border bg-gradient-to-br from-muted via-background to-muted">
      {e.asset_image ? 'Rigenerazione in corso…' : 'Creo il tuo elemento grafico…'}
    </div>}
    {busy && e.job_id && <JobProgress jobId={e.job_id} label="Generazione" onFinished={refresh} />}
    {e.error && <Alert tone="danger">{e.error}</Alert>}
    {!busy && <div className="flex flex-wrap gap-2">
      {(!e.asset_image || manage) && <Button size="sm" disabled={generate.isPending} onClick={() => generate.mutate({ element_id: e.id })}>
        {e.asset_image ? 'Rigenera' : e.status === 'error' ? 'Riprova' : 'Aggiungi'}</Button>}
      <Link className="inline-flex items-center rounded border px-3 py-1 text-sm" to={`/lezioni/${lessonId}/arricchimento?edit=${e.id}#generazione`}>Modifica</Link>
      {manage && e.status === 'dismissed' && <Button size="sm" variant="outline" onClick={() => action.mutate({ element: e.id, action: 'restore' })}>Ripristina idea</Button>}
      {manage && e.asset_image && <Button size="sm" variant="outline" disabled={action.isPending} onClick={() => action.mutate({ element: e.id, action: 'delete' })}>Elimina</Button>}
    </div>}
    {(generate.isError || action.isError) && <Alert tone="danger">{errorMessage(generate.error ?? action.error)}</Alert>}
  </section>
}

/** Portals attach after the last text block of each existing unit, preserving audio markers. */
export function EnrichmentSlots({ root, lessonId, documentKey }: { root: RefObject<HTMLElement | null>; lessonId: number; documentKey: string }) {
  const [slots, setSlots] = useState<Record<string, HTMLElement>>({})
  useEffect(() => {
    const node = root.current
    if (!node) return
    const next: Record<string, HTMLElement> = {}
    node.querySelectorAll<HTMLElement>('[data-unit-id]').forEach(heading => {
      const unit = heading.dataset.unitId
      if (!unit) return
      let last: globalThis.Element = heading
      while (last.nextElementSibling && !/^H[1-3]$/.test(last.nextElementSibling.tagName)) last = last.nextElementSibling
      const slot = window.document.createElement('div')
      slot.className = 'rt-enrichment-slot'
      last.after(slot)
      next[unit] = slot
    })
    // Portal targets synchronize with the externally rendered document DOM.
    // oxlint-disable-next-line react/set-state-in-effect
    setSlots(next)
    return () => { Object.values(next).forEach(slot => slot.remove()) }
  }, [root, documentKey])
  return <EnrichmentPortals slots={slots} lessonId={lessonId} />
}

/** Schede dell'arricchimento nei riquadri delle unità (elementi DOM già al loro posto). */
export function EnrichmentPortals({ slots, lessonId }: { slots: Record<string, HTMLElement>; lessonId: number }) {
  const query = useEnrichment(lessonId)
  return <>{query.data?.elements.filter(e => e.asset_image || ['queued', 'generating', 'error'].includes(e.status) || e.status === 'suggestion' && !e.stale)
    .map(e => slots[e.unit_id] ? createPortal(<EnrichmentCard element={e} lessonId={lessonId} />, slots[e.unit_id], e.id) : null)}</>
}
