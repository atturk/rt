import { Play } from 'lucide-react'
import { useState } from 'react'

import { errorMessage, type Schemas } from '@/api/client'
import { useOutline } from '@/api/jobs'
import { isActiveJob, useLessonJobs, usePhases, useRunJob, useValidatePhase, useWorkers } from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { PHASE_LABELS, formatDateTime, phaseTone } from '@/lib/format'
import { useOptionKey } from '@/lib/optionKey'

type Phase = 'prepare' | 'outline' | 'rewrite' | 'review' | 'build'

// Con Option si può validare a mano solo una fase che esiste ed è leggibile ma non è VALID.
const VALIDATABLE_STATUSES = new Set(['STALE', 'PARTIAL'])

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
export function PhasePanel({ lessonId, units, editingDocument = false }: { lessonId: number; units: Schemas['DocumentSection'][]; editingDocument?: boolean }) {
  const phases = usePhases(lessonId)
  const outline = useOutline(lessonId)
  const draftUnits = units.map((unit) => ({ id: unit.unit_id, title: unit.title }))
  const outlineUnits = outline.data?.macro_sections.flatMap((section) => section.units) ?? draftUnits
  // Si riscrive ciò che c'è nella scaletta, si rivede solo ciò che è già nella bozza.
  const unitsFor = (phase: string) => (phase === 'review' ? draftUnits : outlineUnits)
  const jobs = useLessonJobs(lessonId)
  const workers = useWorkers()
  const run = useRunJob(lessonId)
  const [force, setForce] = useState(false)
  const [withReview, setWithReview] = useState(false)
  // Selezione separata per fase: le unità scelte per la riscrittura non finiscono nella revisione.
  const [selectedUnits, setSelectedUnits] = useState<Record<string, string[]>>({})
  const [extraPrompts, setExtraPrompts] = useState<Record<string, string>>({})
  const [confirmBuild, setConfirmBuild] = useState(false)
  // Option (Alt) premuto: "Esegui" diventa "Valida" (come il cestino delle lezioni).
  const optionDown = useOptionKey()
  const validate = useValidatePhase(lessonId)
  const [confirmValidate, setConfirmValidate] = useState<Phase | null>(null)
  const busy = editingDocument || (jobs.data ?? []).some((j) => isActiveJob(j.state)) || run.isPending || validate.isPending
  // Avvisi di integrità della revisione calcolati dall'API: non bloccano il documento finale,
  // ma l'utente li vede prima di confermarlo.
  const buildWarnings = phases.data?.phases.find((p) => p.phase === 'build')?.warnings ?? []

  const start = (body: { type: 'run_pipeline' | 'run_phase'; phase?: Phase; units?: string[]; extra_prompt?: string }, onQueued?: () => void) =>
    run.mutate({ ...body, force, mock: false, with_review: body.type === 'run_pipeline' && withReview, auto_accept: false, rename: true },
      { onSuccess: onQueued })

  const runPhase = (phase: Phase) => {
    if (phase === 'build' && buildWarnings.length > 0) {
      setConfirmBuild(true)
      return
    }
    const chosen = selectedUnits[phase] ?? []
    start({ type: 'run_phase', phase, units: (phase === 'rewrite' || phase === 'review') && chosen.length ? chosen : undefined,
      extra_prompt: phase in extraPrompts ? extraPrompts[phase] : undefined },
      // Le istruzioni aggiuntive valgono per un'esecuzione sola: accodato il job, il campo si svuota.
      () => setExtraPrompts((old) => { const { [phase]: _used, ...rest } = old; return rest }))
  }

  return (
    <Card className="flex flex-col gap-3 p-4" data-testid="phase-panel">
      {editingDocument && <p className="text-xs text-muted-foreground">Termina la modifica del documento prima di avviare una fase.</p>}
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold">Fasi</h2>
        <Button size="sm" disabled={busy} onClick={() => start({ type: 'run_pipeline' })}>
          <Play /> Pipeline completa
        </Button>
      </div>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={withReview} onChange={(e) => setWithReview(e.target.checked)} />Includi la review nella pipeline</label>
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
              {optionDown ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                  disabled={busy || !VALIDATABLE_STATUSES.has(p.status)}
                  title={VALIDATABLE_STATUSES.has(p.status) ? 'Segna la fase come valida senza rieseguirla'
                    : p.status === 'VALID' ? 'La fase è già valida' : 'Una fase mancante o non valida va eseguita'}
                  aria-label={`Valida ${PHASE_LABELS[p.phase] ?? p.phase}`}
                  onClick={() => { validate.reset(); setConfirmValidate(p.phase as Phase) }}
                >
                  Valida
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                  disabled={busy}
                  aria-label={`Esegui ${PHASE_LABELS[p.phase] ?? p.phase}`}
                  onClick={() => runPhase(p.phase as Phase)}
                >
                  Esegui
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{p.reason}</p>
            {p.manual_validation && (
              <p className="text-xs text-muted-foreground" data-testid={`manual-validation-${p.phase}`}>
                Validata a mano {formatDateTime(p.manual_validation.at) || ''} (era {p.manual_validation.previous_status}), senza rieseguirla.
              </p>
            )}
            {p.phase === 'build' && (p.warnings ?? []).length > 0 && (
              <ul className="flex flex-col gap-0.5 text-xs text-warning" data-testid="build-warnings" aria-label="Avvisi per il documento">
                {(p.warnings ?? []).map((w) => (
                  <li key={w.code}>⚠ {w.message}</li>
                ))}
              </ul>
            )}
            {(['outline', 'rewrite', 'review'] as string[]).includes(p.phase) && (
              <details className="text-xs" data-testid={`advanced-${p.phase}`}>
                <summary className="cursor-pointer">Opzioni avanzate</summary>
                {(p.phase === 'rewrite' || p.phase === 'review') && unitsFor(p.phase).length > 0 && <fieldset className="mt-2 max-h-48 overflow-auto rounded border p-2">
                  <legend className="px-1">Unità (nessuna selezione = tutte)</legend>
                  {unitsFor(p.phase).map((u) => <label key={u.id} className="flex items-center gap-2 py-0.5">
                    <input type="checkbox" checked={(selectedUnits[p.phase] ?? []).includes(u.id)} onChange={(e) => setSelectedUnits((old) => {
                      const current = old[p.phase] ?? []
                      return { ...old, [p.phase]: e.target.checked ? [...current, u.id] : current.filter((id) => id !== u.id) }
                    })} />
                    {u.id} {u.title}
                  </label>)}
                </fieldset>}
                <Label htmlFor={`extra-${p.phase}`}>Istruzioni per {PHASE_LABELS[p.phase] ?? p.phase}</Label>
                <textarea id={`extra-${p.phase}`} className="mt-1 w-full rounded-md border bg-background p-2 text-sm" rows={3}
                  maxLength={10000} value={extraPrompts[p.phase] ?? ''} onChange={(e) => setExtraPrompts((old) => ({ ...old, [p.phase]: e.target.value }))}
                  placeholder="Facoltativo; una scaletta esistente viene revisionata con queste istruzioni." />
              </details>
            )}
          </li>
        ))}
      </ul>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
        Forza (rifai anche le fasi già valide)
      </label>
      {run.isError && <Alert tone="danger">{errorMessage(run.error)}</Alert>}
      {validate.isError && !confirmValidate && <Alert tone="danger">{errorMessage(validate.error)}</Alert>}
      {run.data && !run.data.worker_available && (
        <Alert tone="warning">Nessun worker attivo: il job resta in coda finché RT non viene riavviato con la web.</Alert>
      )}
      {workers.data?.length === 0 && !run.data && (
        <p className="text-xs text-muted-foreground">Nessun worker attivo: i job partiranno quando ne avvii uno.</p>
      )}
      {phases.data?.validation_error && <Alert tone="danger">{phases.data.validation_error}</Alert>}
      <Validation title="outline" report={phases.data?.outline_validation} />
      <Validation title="draft" report={phases.data?.draft_validation} />
      <ConfirmDialog
        open={confirmValidate !== null}
        title={`Validare ${confirmValidate ? (PHASE_LABELS[confirmValidate] ?? confirmValidate) : ''} senza rieseguirla?`}
        confirmLabel="Valida"
        confirmDisabled={validate.isPending}
        onCancel={() => setConfirmValidate(null)}
        onConfirm={() => {
          if (!confirmValidate) return
          validate.mutate(confirmValidate, { onSuccess: () => setConfirmValidate(null) })
        }}
      >
        <p>
          La fase viene segnata come valida con i file attuali, così come sono, senza eseguirla di nuovo. Usalo
          quando la differenza è voluta (per esempio un file modificato a mano).
        </p>
        <p className="mt-2 text-muted-foreground">
          Le fasi successive costruite su file diversi restano da rifare.
        </p>
        {validate.isError && <Alert tone="danger" className="mt-3">{errorMessage(validate.error)}</Alert>}
      </ConfirmDialog>
      <ConfirmDialog
        open={confirmBuild}
        title="Creare il documento finale?"
        confirmLabel="Crea il documento comunque"
        onCancel={() => setConfirmBuild(false)}
        onConfirm={() => {
          setConfirmBuild(false)
          start({ type: 'run_phase', phase: 'build' })
        }}
      >
        <p>Il documento finale sarà uguale all'anteprima che vedi ora. Prima di confermarlo, controlla:</p>
        <ul className="mt-2 list-disc pl-5" data-testid="build-confirm-warnings">
          {buildWarnings.map((w) => (
            <li key={w.code}>{w.message}</li>
          ))}
        </ul>
      </ConfirmDialog>
    </Card>
  )
}
