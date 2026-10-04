import { Check, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { errorMessage, type Schemas } from '@/api/client'
import { invalidateAfterJob, useApproveOutline, useJob, useReviseOutline, useSuspendOutline } from '@/api/jobs'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { isActive, isTerminal } from '@/lib/jobs'
import { useIsPhone } from '@/lib/phone'

/** Il timer del server resta l'unica autorità: allo zero rileggiamo, senza approvare dal browser. */
export function LessonOutline({ lessonId, outline, busy, mock = false, refresh }: {
  lessonId: number; outline: Schemas['Outline']; busy: boolean; mock?: boolean; refresh: () => Promise<unknown>
}) {
  const approve = useApproveOutline(lessonId)
  const revise = useReviseOutline(lessonId)
  const suspend = useSuspendOutline(lessonId)
  const revision = useJob(revise.data?.job_id ?? '')
  const client = useQueryClient()
  const phone = useIsPhone()
  const [feedback, setFeedback] = useState('')
  const [showFeedback, setShowFeedback] = useState(false)
  const [paused, setPaused] = useState(false)
  const pause = useRef<Promise<unknown> | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [expiryError, setExpiryError] = useState<string | null>(null)
  const expires = outline.expires_at ? Date.parse(outline.expires_at) : NaN
  const suspended = outline.timer_suspended || paused
  const revising = revise.isPending || !!revise.data && (!revision.data || isActive(revision.data.state))

  useEffect(() => {
    if (!Number.isFinite(expires) || suspended || revising) return
    let expired = false
    const tick = () => {
      setNow(Date.now())
      if (Date.now() >= expires && !expired) {
        expired = true
        void refresh().then(() => invalidateAfterJob(client, lessonId)).catch((e) => setExpiryError(errorMessage(e)))
      }
    }
    tick()
    const interval = setInterval(tick, 250)
    return () => clearInterval(interval)
  }, [expires, suspended, revising, refresh, client, lessonId])
  useEffect(() => {
    if (isTerminal(revision.data?.state)) invalidateAfterJob(client, lessonId)
  }, [revision.data?.state, client, lessonId])

  const pauseTimer = () => {
    if (outline.timer_suspended || !Number.isFinite(expires)) return Promise.resolve()
    if (pause.current) return pause.current
    setPaused(true)
    const request = suspend.mutateAsync()
    pause.current = request
    void request.catch(() => { pause.current = null; setPaused(false) })
    return request
  }
  const changeFeedback = (text: string) => {
    setFeedback(text)
    if (text.trim()) void pauseTimer()
  }
  const regenerate = async () => {
    try {
      await pauseTimer()
      await revise.mutateAsync({ feedback: feedback.trim(), mock })
    } catch { /* Gli errori delle mutazioni restano visibili nel riquadro. */ }
  }
  const disabled = busy || revising || approve.isPending
  const seconds = !suspended && Number.isFinite(expires) ? Math.max(0, Math.ceil((expires - now) / 1000)) : null
  const error = approve.error ?? revise.error ?? suspend.error
  return <>
    <Card className="mt-5 flex flex-col gap-3 border-warning/35 bg-warning-soft p-4 text-body" data-testid="outline-approval">
      <p className="font-semibold">Scaletta da approvare</p>
      <div className="flex flex-wrap gap-2 max-md:flex-col-reverse">
        <Button disabled={disabled} onClick={() => approve.mutate()} className="self-start max-md:h-12 max-md:w-full">
          <Check size={16} aria-hidden />{seconds == null ? 'Approva' : `Approva (${seconds})`}
        </Button>
        {phone && <Button variant="outline" className="h-12" disabled={disabled} aria-expanded={showFeedback} aria-controls="outline-feedback-form" onClick={() => setShowFeedback((v) => !v)}>Chiedi modifiche</Button>}
      </div>
      {(!phone || showFeedback) && <form id="outline-feedback-form" className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); void regenerate() }}>
        <Label htmlFor="outline-feedback" className="text-meta">Oppure chiedi modifiche</Label>
        <Textarea id="outline-feedback" rows={3} value={feedback} onChange={(e) => changeFeedback(e.target.value)} disabled={disabled} />
        <Button type="submit" variant="outline" className="self-start max-md:h-12 max-md:w-full" disabled={disabled || !feedback.trim()}>Rigenera con queste modifiche</Button>
      </form>}
      {revising && <p role="status" className="flex items-center gap-2 text-meta"><LoaderCircle size={16} aria-hidden className="animate-spin" />Revisione della scaletta…</p>}
      {revision.data?.state === 'failed' && <Alert tone="danger">{revision.data.error ?? 'Revisione fallita'}</Alert>}
      {error && <Alert tone="danger">{errorMessage(error)}</Alert>}
      {expiryError && <Alert tone="danger">{expiryError}<Button variant="outline" size="sm" onClick={() => { setExpiryError(null); void refresh() }}>Riprova</Button></Alert>}
    </Card>
    <section className="mt-6" aria-label="Scaletta della lezione">
      {outline.macro_sections.map((macro) => <section key={macro.id} className="mb-5">
        <h2 className="mb-2 text-body font-semibold">{macro.id}. {macro.title}</h2>
        {macro.units.map((unit) => <div key={unit.id} className="border-l-2 py-2 pl-4">
          <h3 className="text-body font-medium">{unit.id} {unit.title}</h3>
          {unit.key_concepts.length > 0 && <p className="mt-1 text-meta text-muted-foreground">{unit.key_concepts.join(' · ')}</p>}
        </div>)}
      </section>)}
    </section>
  </>
}
