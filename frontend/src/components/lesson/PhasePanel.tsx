import { Play } from 'lucide-react'
import { useState } from 'react'

import { errorMessage, type Schemas } from '@/api/client'
import { isActiveJob, useLessonJobs, usePhases, useRunJob, useWorkers } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { PHASE_LABELS, phaseTone } from '@/lib/format'

type Phase = 'prepare' | 'outline' | 'rewrite' | 'review' | 'build'

const VALIDATION_LABELS: Record<string, string> = {
  macro_count: 'Macro-sezioni',
  units_count: 'Unità',
  total_segments: 'Segmenti',
  covered_segments: 'Segmenti coperti',
  coverage_percentage: 'Copertura (%)',
  omitted_count: 'Segmenti omessi',
  duplicate_count: 'Segmenti duplicati',
  draft_units_count: 'Unità rielaborate',
  expected_units_count: 'Unità attese',
  all_units_covered: 'Tutte le unità coperte',
  provenance_verified_units: 'Unità con provenienza verificata',
  total_source_segments_used: 'Segmenti usati',
}

function formatValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'sì' : 'no'
  if (Array.isArray(value)) return value.length ? value.map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', ') : '—'
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value ?? '—')
}

function Validation({ title, report }: { title: string; report: Record<string, unknown> | null | undefined }) {
  if (!report) return null
  const valid = report.valid === true
  const rows = Object.entries(report).filter(([k]) => k !== 'valid')
  return (
    <details className="rounded-lg border px-3 py-2 text-xs" open={!valid} data-testid={`validation-${title}`}>
      <summary className="flex cursor-pointer items-center gap-2 font-semibold">
        {title === 'outline' ? 'Validazione scaletta' : 'Validazione bozza'}
        <Badge tone={valid ? 'success' : 'danger'}>{valid ? 'valida' : 'non valida'}</Badge>
      </summary>
      <dl className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
        {rows.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">{VALIDATION_LABELS[key] ?? key}</dt>
            <dd className="text-right tabular-nums">{formatValue(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

/** Stato delle fasi con motivo e validazioni, e pulsanti per eseguirle come job. */
export function PhasePanel({ lessonId, units }: { lessonId: number; units: Schemas['DocumentSection'][] }) {
  const phases = usePhases(lessonId)
  const jobs = useLessonJobs(lessonId)
  const workers = useWorkers()
  const run = useRunJob(lessonId)
  const [force, setForce] = useState(false)
  const [unit, setUnit] = useState('')
  const busy = (jobs.data ?? []).some((j) => isActiveJob(j.state)) || run.isPending

  const start = (body: { type: 'run_pipeline' | 'run_phase'; phase?: Phase; unit?: string }) =>
    run.mutate({ ...body, force, mock: false, with_review: true, auto_accept: false, rename: true })

  return (
    <Card className="flex flex-col gap-3 p-4" data-testid="phase-panel">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold">Fasi</h2>
        <Button size="sm" disabled={busy} onClick={() => start({ type: 'run_pipeline' })}>
          <Play /> Pipeline completa
        </Button>
      </div>
      {phases.isError && <Alert tone="danger">{errorMessage(phases.error)}</Alert>}
      <ul className="flex flex-col divide-y">
        {phases.data?.phases.map((p) => (
          <li key={p.phase} className="flex flex-col gap-1.5 py-2.5" data-phase-row={p.phase} data-status={p.status}>
            <div className="flex items-center gap-2">
              <Badge tone={phaseTone(p.status)} className="min-w-28">
                <span className="size-1.5 rounded-full bg-current opacity-70" aria-hidden />
                {PHASE_LABELS[p.phase] ?? p.phase}
              </Badge>
              <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{p.status}</span>
              <Button
                variant="outline"
                size="sm"
                className="ml-auto"
                disabled={busy}
                aria-label={`Esegui ${PHASE_LABELS[p.phase] ?? p.phase}`}
                onClick={() => start({ type: 'run_phase', phase: p.phase as Phase, unit: p.phase === 'rewrite' && unit ? unit : undefined })}
              >
                Esegui
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{p.reason}</p>
            {p.phase === 'rewrite' && units.length > 0 && (
              <div className="flex items-center gap-2">
                <Label htmlFor="rewrite-unit" className="shrink-0">
                  Unità
                </Label>
                <Select id="rewrite-unit" value={unit} onChange={(e) => setUnit(e.target.value)} className="h-8 text-xs">
                  <option value="">Tutte</option>
                  {units.map((u) => (
                    <option key={u.unit_id} value={u.unit_id}>
                      {u.unit_id} {u.title}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </li>
        ))}
      </ul>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
        Forza (rifai anche le fasi già valide)
      </label>
      {run.isError && <Alert tone="danger">{errorMessage(run.error)}</Alert>}
      {run.data && !run.data.worker_available && (
        <Alert tone="warning">Nessun worker attivo: il job resta in coda finché non avvii rt worker (o rt web).</Alert>
      )}
      {workers.data?.length === 0 && !run.data && (
        <p className="text-xs text-muted-foreground">Nessun worker attivo: i job partiranno quando ne avvii uno.</p>
      )}
      {phases.data?.validation_error && <Alert tone="danger">{phases.data.validation_error}</Alert>}
      <Validation title="outline" report={phases.data?.outline_validation} />
      <Validation title="draft" report={phases.data?.draft_validation} />
    </Card>
  )
}
