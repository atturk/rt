import { BuildConfirmDialog } from '../BuildConfirmDialog'
import { ChevronDown, ChevronUp, Download, MoreHorizontal, Play, RotateCcw, Trash2, Tags, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useClassifier } from '@/api/classifier'
import { useNavigate } from 'react-router'

import { errorMessage, type Schemas } from '@/api/client'
import { useOutline } from '@/api/jobs'
import {
  isActiveJob,
  useDeleteLesson,
  useLessonJobs,
  useLessons,
  usePhases,
  usePipelineVersion,
  useRestorePipeline,
  useRunJob,
  useUpdateLessonMetadata,
  useValidatePhase,
} from '@/api/hooks'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { PHASE_LABELS, PHASE_ORDER, STATE_LABELS, formatCost, formatDateTime, phaseTone } from '@/lib/format'
import { formatDuration } from '@/lib/lessonsPage'
import { CostPanel } from '../CostPanel'
import { JobsPanel } from '../JobsPanel'

type Section = Schemas['DocumentSection']
type Phase = 'prepare' | 'outline' | 'rewrite' | 'review' | 'build'

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
    <details className="rounded-lg border px-3 py-2 text-meta" open={!valid} data-testid={`validation-${title}`}>
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

function formatDataOra(data: string, ora: string): string {
  if (!data) return ora ? `· ${ora}` : ''
  const parts = data.split('-')
  const dateFormatted = parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : data
  return ora ? `${dateFormatted} · ${ora}` : dateFormatted
}

function parseDataOra(input: string): { data?: string; ora?: string } {
  const trimmed = input.trim()
  if (!trimmed) return {}
  const match = trimmed.match(/^(\d{1,2}\/\d{1,2}\/\d{4}|\d{4}-\d{2}-\d{2})(?:\s*[·\s]\s*(\d{1,2}:\d{2}))?$/)
  if (!match) return {}
  const rawDate = match[1]
  const rawTime = match[2]
  let data: string | undefined
  if (rawDate.includes('/')) {
    const [d, m, y] = rawDate.split('/')
    data = `${y.padStart(4, '20')}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`
  } else {
    data = rawDate
  }
  let ora: string | undefined
  if (rawTime) {
    const [h, m] = rawTime.split(':')
    ora = `${h.padStart(2, '0')}:${m.padStart(2, '0')}`
  } else {
    ora = ''
  }
  return { data, ora }
}

export function DetailsPanel({
  lesson: l,
  sections,
  editingDocument = false,
}: {
  lesson: Schemas['LessonDetail']
  sections: Section[]
  editingDocument: boolean
}) {
  const navigate = useNavigate()
  const deleteInputId = useId()

  // Metadati modificabili
  const [prevId, setPrevId] = useState(l.id)
  const [title, setTitle] = useState(l.titolo || '')
  const [materia, setMateria] = useState(l.materia || '')
  const [dataOra, setDataOra] = useState(formatDataOra(l.data, l.ora))
  const [docente, setDocente] = useState(l.docente || '')

  if (prevId !== l.id) {
    setPrevId(l.id)
    setTitle(l.titolo || '')
    setMateria(l.materia || '')
    setDataOra(formatDataOra(l.data, l.ora))
    setDocente(l.docente || '')
  }

  const allLessons = useLessons()
  const subjectOptions = Array.from(
    new Set([l.materia, ...(allLessons.data ?? []).map((les) => les.materia)].filter(Boolean) as string[]),
  ).sort()

  const updateMetadata = useUpdateLessonMetadata(l.id)

  const saveMetadata = (overrides?: Partial<Schemas['LessonMetadataUpdate']>) => {
    const parsed = parseDataOra(dataOra)
    const payload: Schemas['LessonMetadataUpdate'] = {
      titolo: title.trim() || l.titolo,
      materia: materia.trim() || l.materia,
      data: parsed.data ?? l.data,
      ora: parsed.ora !== undefined ? parsed.ora : l.ora,
      docente: docente.trim(),
      ...overrides,
    }
    // Salva solo se cambiato
    if (
      payload.titolo !== l.titolo ||
      payload.materia !== l.materia ||
      payload.data !== l.data ||
      payload.ora !== l.ora ||
      payload.docente !== l.docente
    ) {
      updateMetadata.mutate(payload)
    }
  }

  // Fasi e Job
  const phases = usePhases(l.id)
  const outline = useOutline(l.id)
  const draftUnits = sections.map((unit) => ({ id: unit.unit_id, title: unit.title }))
  const outlineUnits = outline.data?.macro_sections.flatMap((section) => section.units) ?? draftUnits
  const unitsFor = (phase: string) => (phase === 'review' ? draftUnits : outlineUnits)

  const classifier = useClassifier(l.id)
  const jobs = useLessonJobs(l.id)
  const run = useRunJob(l.id)
  const validate = useValidatePhase(l.id)

  const [withReview, setWithReview] = useState(false)
  const [openOptionsPhase, setOpenOptionsPhase] = useState<Phase | null>(null)
  const [selectedUnits, setSelectedUnits] = useState<Record<string, string[]>>({})
  const [extraPrompts, setExtraPrompts] = useState<Record<string, string>>({})
  const [forcePhase, setForcePhase] = useState<Record<string, boolean>>({})
  const [confirmBuild, setConfirmBuild] = useState(false)
  const [confirmValidate, setConfirmValidate] = useState<Phase | null>(null)

  const [openPhaseMenu, setOpenPhaseMenu] = useState<Phase | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!openPhaseMenu) return
    const onPointer = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) {
        setOpenPhaseMenu(null)
      }
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [openPhaseMenu])

  const busy = editingDocument || (jobs.data ?? []).some((j) => isActiveJob(j.state)) || run.isPending || validate.isPending
  const buildWarnings = phases.data?.phases.find((p) => p.phase === 'build')?.warnings ?? []
  const buildPhase = phases.data?.phases.find((p) => p.phase === 'build')
  const isBuildStale = buildPhase?.status === 'STALE' || l.phases.build === 'STALE'

  const start = (
    body: { type: 'run_pipeline' | 'run_phase'; phase?: Phase; units?: string[]; extra_prompt?: string; force?: boolean },
    onQueued?: () => void,
  ) =>
    run.mutate(
      {
        ...body,
        force: body.force ?? false,
        mock: false,
        with_review: body.type === 'run_pipeline' && withReview,
        auto_accept: false,
        rename: true,
      },
      { onSuccess: onQueued },
    )

  const runPhase = (phase: Phase, force = false) => {
    if (phase === 'build' && buildWarnings.length > 0) {
      setConfirmBuild(true)
      return
    }
    const chosen = selectedUnits[phase] ?? []
    start(
      {
        type: 'run_phase',
        phase,
        units: (phase === 'rewrite' || phase === 'review') && chosen.length ? chosen : undefined,
        extra_prompt: phase in extraPrompts ? extraPrompts[phase] : undefined,
        force,
      },
      () => {
        setExtraPrompts((old) => {
          const { [phase]: _used, ...rest } = old
          return rest
        })
        setOpenOptionsPhase(null)
      },
    )
  }

  // Costi e Job expand
  const [showCostDetail, setShowCostDetail] = useState(false)
  const [showJobsDetail, setShowJobsDetail] = useState(false)

  // Pipeline Version Restore
  const pipelineVersion = usePipelineVersion(l.id)
  const restorePipeline = useRestorePipeline(l.id)
  const [showRestorePrompt, setShowRestorePrompt] = useState(false)

  // Scarica la bozza attuale prima del ripristino: il file deve arrivare prima che cambi
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const downloadAndRestore = async () => {
    setDownloadError(null)
    try {
      const url = `/api/v1/lesson-exports?${new URLSearchParams([
        ['ids', String(l.id)],
        ['format', 'markdown'],
        ['name', l.titolo || l.folder_name],
      ])}`
      const response = await fetch(url, { credentials: 'same-origin' })
      if (!response.ok) throw new Error(`Download non riuscito (${response.status})`)
      const name = /filename="?([^";]+)"?/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? `${l.folder_name}.md`
      const link = document.createElement('a')
      link.href = URL.createObjectURL(await response.blob())
      link.download = name
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (error) {
      setDownloadError(errorMessage(error))
      return
    }
    restorePipeline.mutate(null, { onSuccess: () => setShowRestorePrompt(false) })
  }

  // Eliminazione lezione
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteTyped, setDeleteTyped] = useState('')
  const deleteLesson = useDeleteLesson(l.id)

  const handleDeleteSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (deleteTyped === 'confermo') {
      deleteLesson.mutate(undefined, {
        onSuccess: () => {
          navigate('/')
        },
      })
    }
  }

  // Riepilogo job status
  const runningJob = (jobs.data ?? []).find((j) => isActiveJob(j.state))
  const lastFinishedJob = (jobs.data ?? []).find((j) => !isActiveJob(j.state))
  const jobSummary = runningJob
    ? `In corso: ${PHASE_LABELS[runningJob.payload?.phase as string] ?? runningJob.type}`
    : lastFinishedJob
      ? `Nessun job in corso. L'ultimo: ${PHASE_LABELS[lastFinishedJob.payload?.phase as string] ?? lastFinishedJob.type} (${lastFinishedJob.state})`
      : 'Nessun job registrato.'

  return (
    <div className="flex flex-col gap-4 text-body" data-testid="details-panel">
      {/* Campi metadati */}
      <div className="grid grid-cols-2 gap-2.5">
        <div className="col-span-2 flex flex-col gap-1">
          <label htmlFor="details-title" className="text-meta text-muted-foreground">
            Titolo
          </label>
          <Input
            id="details-title"
            value={title}
            disabled={busy}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => saveMetadata()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveMetadata()
            }}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="details-subject" className="text-meta text-muted-foreground">
            Materia
          </label>
          <Select
            id="details-subject"
            value={materia}
            disabled={busy}
            onChange={(e) => {
              setMateria(e.target.value)
              saveMetadata({ materia: e.target.value })
            }}
          >
            {subjectOptions.map((subj) => (
              <option key={subj} value={subj}>
                {subj}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="details-datetime" className="text-meta text-muted-foreground">
            Data e ora
          </label>
          <Input
            id="details-datetime"
            value={dataOra}
            disabled={busy}
            onChange={(e) => setDataOra(e.target.value)}
            onBlur={() => saveMetadata()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveMetadata()
            }}
          />
        </div>
        <div className="col-span-2 flex flex-col gap-1">
          <label htmlFor="details-teacher" className="text-meta text-muted-foreground">
            Docente
          </label>
          <Input
            id="details-teacher"
            value={docente}
            disabled={busy}
            onChange={(e) => setDocente(e.target.value)}
            onBlur={() => saveMetadata()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveMetadata()
            }}
          />
        </div>
      </div>

      <p className="text-meta text-muted-foreground">
        Cartella: <span className="font-mono text-foreground">{l.folder_name}</span>
      </p>

      {updateMetadata.isError && <Alert tone="danger">{errorMessage(updateMetadata.error)}</Alert>}

      {/* Avviso "Documento da ricreare › Ricrea" */}
      {isBuildStale && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning-soft p-3">
          <p className="min-w-0 flex-1 text-meta font-medium text-warning">
            Il documento finale non è aggiornato: il testo è cambiato.
          </p>
          <Button size="sm" variant="default" disabled={busy} onClick={() => runPhase('build')}>
            Ricrea
          </Button>
        </div>
      )}

      {/* Riepilogo */}
      <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-body" data-testid="lesson-details">
        <dt className="self-center text-meta text-muted-foreground">Stato</dt>
        <dd>{l.state ? STATE_LABELS[l.state] ?? l.state : '—'}</dd>

        <dt className="self-center text-meta text-muted-foreground">Durata</dt>
        <dd>
          {l.duration_seconds ? `${formatDuration(l.duration_seconds)} · ` : ''}
          {sections.length} unità
        </dd>

        <dt className="self-center text-meta text-muted-foreground">Costo</dt>
        <dd className="flex items-center gap-2">
          <span className="tabular-nums">{formatCost(l.cost_usd)}</span>
          <button
            type="button"
            className="flex items-center gap-0.5 text-meta text-link hover:underline"
            onClick={() => setShowCostDetail(!showCostDetail)}
          >
            dettaglio {showCostDetail ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
          </button>
        </dd>
      </dl>

      <Button variant="outline" className="h-auto w-full justify-start gap-3 py-4" onClick={() => navigate(`/lezioni/${l.id}?panel=classificatore`)}>
        <Tags size={18} aria-hidden /><span className="flex flex-col items-start"><span className="text-body">Classificatore</span><span className="text-meta text-muted-foreground">{classifier.data ? `${classifier.data.pending} unità da rivedere` : '\u00a0'}</span></span>
      </Button>
      {showCostDetail && <CostPanel lesson={l} />}

      <hr className="border-border" />

      {/* Fasi */}
      <div className="flex flex-col gap-2" data-testid="phase-panel">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">Fasi</h3>
          <div className="flex items-center gap-2.5">
            <label className="flex items-center gap-1.5 text-meta">
              <input
                type="checkbox"
                checked={withReview}
                onChange={(e) => setWithReview(e.target.checked)}
                className="size-3.5 rounded border"
              />
              con la revisione
            </label>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => start({ type: 'run_pipeline' })}>
              <Play className="size-3.5" /> Pipeline completa
            </Button>
          </div>
        </div>

        {editingDocument && (
          <p className="text-meta text-muted-foreground">
            Termina la modifica del documento prima di avviare una fase.
          </p>
        )}
        {phases.isError && <Alert tone="danger">{errorMessage(phases.error)}</Alert>}
        {run.isError && <Alert tone="danger">{errorMessage(run.error)}</Alert>}

        <ul className="flex flex-col divide-y divide-border/60">
          {PHASE_ORDER.map((phaseKey) => {
            const p = phases.data?.phases.find((item) => item.phase === phaseKey) ?? {
              phase: phaseKey,
              status: 'MISSING',
              reason: '',
            }
            const phase = p.phase as Phase
            const tone = phaseTone(p.status)
            const dotClass =
              tone === 'success'
                ? 'bg-success'
                : tone === 'warning'
                  ? 'bg-warning'
                  : tone === 'danger'
                    ? 'bg-danger'
                    : 'bg-muted-foreground/50'

            let statusLabel = p.reason || p.status.toLowerCase()
            if (p.phase === 'prepare' && p.status === 'VALID') statusLabel = 'aggiornata'
            if (p.phase === 'outline' && p.status === 'VALID') statusLabel = 'approvata'
            if (p.phase === 'rewrite' && p.status === 'VALID') statusLabel = `${sections.length} unità`
            if (p.phase === 'review') {
              if (l.pending_issues > 0) statusLabel = `${l.pending_issues} issue da decidere`
              else if (p.status === 'VALID') statusLabel = 'completata'
            }
            if (p.phase === 'build') {
              if (p.status === 'STALE') statusLabel = 'da ricreare: il testo è cambiato'
              else if (p.status === 'VALID') statusLabel = 'valido'
            }

            const isMenuOpen = openPhaseMenu === phase
            const isOptionsOpen = openOptionsPhase === phase

            return (
              <li key={phase} className="flex flex-col py-1.5" data-phase-row={phase} data-status={p.status}>
                <div className="flex items-center gap-2.5">
                  <span className={`size-2 shrink-0 rounded-full ${dotClass}`} aria-hidden />
                  <span className="w-28 shrink-0 text-body font-medium">{PHASE_LABELS[phase] ?? phase}</span>
                  <span className="min-w-0 flex-1 truncate text-meta text-muted-foreground" title={statusLabel}>
                    {statusLabel}
                  </span>
                  <div className="relative">
                    <IconButton
                      label={`Azioni su ${PHASE_LABELS[phase] ?? phase}`}
                      icon={MoreHorizontal}
                      className="size-7"
                      active={isMenuOpen}
                      disabled={busy}
                      onClick={() => setOpenPhaseMenu(isMenuOpen ? null : phase)}
                    />
                    {isMenuOpen && (
                      <div
                        ref={menuRef}
                        role="menu"
                        aria-label={`Azioni su ${PHASE_LABELS[phase] ?? phase}`}
                        className="absolute right-0 top-full z-20 mt-1 w-48 rounded-lg border bg-card p-1 text-body shadow-panel"
                      >
                        <button
                          type="button"
                          role="menuitem"
                          className="flex min-h-8 w-full items-center rounded-md px-2.5 text-left hover:bg-muted"
                          onClick={() => {
                            setOpenPhaseMenu(null)
                            runPhase(phase)
                          }}
                        >
                          Riesegui
                        </button>
                        {(phase === 'outline' || phase === 'rewrite' || phase === 'review') && (
                          <button
                            type="button"
                            role="menuitem"
                            className="flex min-h-8 w-full items-center rounded-md px-2.5 text-left hover:bg-muted"
                            onClick={() => {
                              setOpenPhaseMenu(null)
                              setOpenOptionsPhase(phase)
                            }}
                          >
                            Riesegui con opzioni…
                          </button>
                        )}
                        <button
                          type="button"
                          role="menuitem"
                          disabled={!VALIDATABLE_STATUSES.has(p.status)}
                          className="flex min-h-8 w-full items-center rounded-md px-2.5 text-left hover:bg-muted disabled:opacity-50"
                          onClick={() => {
                            setOpenPhaseMenu(null)
                            setConfirmValidate(phase)
                          }}
                        >
                          Segna come valida
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {/* Scheda opzioni avanzate in linea */}
                {isOptionsOpen && (
                  <Card className="my-2 flex flex-col gap-2.5 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-body font-semibold">
                        Riesegui {PHASE_LABELS[phase].toLowerCase()}
                      </span>
                      <IconButton
                        label="Chiudi opzioni"
                        icon={X}
                        className="size-6"
                        onClick={() => setOpenOptionsPhase(null)}
                      />
                    </div>

                    {(phase === 'rewrite' || phase === 'review') && unitsFor(phase).length > 0 && (
                      <fieldset className="max-h-40 overflow-y-auto rounded-md border p-2 text-meta">
                        <legend className="px-1 text-muted-foreground">Unità (nessuna = tutte)</legend>
                        {unitsFor(phase).map((u) => {
                          const isChecked = (selectedUnits[phase] ?? []).includes(u.id)
                          return (
                            <label key={u.id} className="flex items-center gap-2 py-0.5">
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={(e) =>
                                  setSelectedUnits((old) => {
                                    const current = old[phase] ?? []
                                    return {
                                      ...old,
                                      [phase]: e.target.checked
                                        ? [...current, u.id]
                                        : current.filter((id) => id !== u.id),
                                    }
                                  })
                                }
                              />
                              <span className="truncate">
                                {u.id} {u.title}
                              </span>
                            </label>
                          )
                        })}
                      </fieldset>
                    )}

                    <div className="flex flex-col gap-1">
                      <label htmlFor={`extra-${phase}`} className="text-meta text-muted-foreground">
                        Istruzioni aggiuntive
                      </label>
                      <Textarea
                        id={`extra-${phase}`}
                        rows={3}
                        className="p-2 text-meta"
                        value={extraPrompts[phase] ?? ''}
                        onChange={(e) => setExtraPrompts((old) => ({ ...old, [phase]: e.target.value }))}
                        placeholder="Facoltativo"
                      />
                    </div>

                    <div className="flex items-center justify-between gap-2 pt-1">
                      <label className="flex items-center gap-1.5 text-meta text-muted-foreground">
                        <input
                          type="checkbox"
                          checked={forcePhase[phase] ?? false}
                          onChange={(e) => setForcePhase((old) => ({ ...old, [phase]: e.target.checked }))}
                        />
                        anche se è già valida
                      </label>
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => runPhase(phase, forcePhase[phase] ?? false)}
                      >
                        <Play className="size-3" />
                        Riesegui
                        {(selectedUnits[phase] ?? []).length > 0
                          ? ` ${(selectedUnits[phase] ?? []).length} unità`
                          : ''}
                      </Button>
                    </div>
                  </Card>
                )}

                {p.manual_validation && (
                  <p className="mt-0.5 text-meta text-muted-foreground" data-testid={`manual-validation-${phase}`}>
                    Validata a mano {formatDateTime(p.manual_validation.at) || ''} (era{' '}
                    {p.manual_validation.previous_status}).
                  </p>
                )}

                {phase === 'build' && buildWarnings.length > 0 && (
                  <ul className="mt-1 flex flex-col gap-0.5 text-meta text-warning" data-testid="build-warnings">
                    {buildWarnings.map((w) => (
                      <li key={w.code}>⚠ {w.message}</li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>

        {phases.data?.validation_error && <Alert tone="danger">{phases.data.validation_error}</Alert>}
        <Validation title="outline" report={phases.data?.outline_validation} />
        <Validation title="draft" report={phases.data?.draft_validation} />
      </div>

      <hr className="border-border" />

      {/* Job */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <h3 className="text-meta font-semibold uppercase tracking-wider text-muted-foreground">Job</h3>
          <button
            type="button"
            className="flex items-center gap-0.5 text-meta text-link hover:underline"
            onClick={() => setShowJobsDetail(!showJobsDetail)}
          >
            ultimi 5 {showJobsDetail ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
          </button>
        </div>
        <p className="text-meta text-muted-foreground">{jobSummary}</p>
        {showJobsDetail && <JobsPanel lessonId={l.id} />}
      </div>

      <hr className="border-border" />

      {/* In fondo: Ripristina la versione della pipeline ed Elimina la lezione */}
      <div className="flex flex-col gap-3 pt-1">
        {pipelineVersion.data?.available && !showRestorePrompt && (
          <button
            type="button"
            className="flex items-center gap-1.5 self-start text-meta text-foreground hover:underline"
            onClick={() => setShowRestorePrompt(true)}
          >
            <RotateCcw className="size-3.5" /> Ripristina la versione della pipeline…
          </button>
        )}

        {showRestorePrompt && (
          <Card className="flex flex-col gap-2.5 p-3">
            <p className="text-body font-semibold">Ripristinare la versione della pipeline?</p>
            <p className="text-meta text-muted-foreground">
              Testo, titoli, timecode e immagini tornano come li ha scritti la pipeline; le decisioni della revisione
              restano.
            </p>
            <div className="rounded-md bg-muted p-2 text-meta">
              <p className="font-semibold">Modificate a mano: {pipelineVersion.data?.modified_units ?? 0} unità</p>
            </div>
            {restorePipeline.isError && <Alert tone="danger">{errorMessage(restorePipeline.error)}</Alert>}
            {downloadError && <Alert tone="danger">{downloadError}</Alert>}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button
                size="sm"
                variant="default"
                disabled={restorePipeline.isPending}
                onClick={() => void downloadAndRestore()}
              >
                <Download className="size-3" /> Scarica e ripristina
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={restorePipeline.isPending}
                onClick={() => restorePipeline.mutate(null, { onSuccess: () => setShowRestorePrompt(false) })}
              >
                Ripristina
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setShowRestorePrompt(false)}>
                Annulla
              </Button>
            </div>
          </Card>
        )}

        {!confirmDelete ? (
          <button
            type="button"
            className="flex items-center gap-1.5 self-start text-meta text-danger hover:underline"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="size-3.5" /> Elimina la lezione…
          </button>
        ) : (
          <form onSubmit={handleDeleteSubmit} className="flex flex-col gap-2 rounded-lg border border-danger/30 p-3">
            <label htmlFor={deleteInputId} className="text-meta text-danger">
              Eliminare definitivamente la lezione e tutti i suoi file? Scrivi confermo
            </label>
            <Input
              id={deleteInputId}
              value={deleteTyped}
              autoFocus
              disabled={deleteLesson.isPending}
              onChange={(e) => setDeleteTyped(e.target.value)}
            />
            {deleteLesson.isError && <Alert tone="danger">{errorMessage(deleteLesson.error)}</Alert>}
            <div className="flex justify-end gap-2 pt-1">
              <Button size="sm" variant="outline" type="button" onClick={() => setConfirmDelete(false)}>
                Annulla
              </Button>
              <Button
                size="sm"
                variant="destructive"
                type="submit"
                disabled={deleteTyped !== 'confermo' || deleteLesson.isPending}
              >
                Elimina
              </Button>
            </div>
          </form>
        )}
      </div>

      {/* Dialogo conferma validazione */}
      <ConfirmDialog
        open={confirmValidate !== null}
        title={`Validare ${confirmValidate ? PHASE_LABELS[confirmValidate] ?? confirmValidate : ''} senza rieseguirla?`}
        confirmLabel="Valida"
        confirmDisabled={validate.isPending}
        onCancel={() => setConfirmValidate(null)}
        onConfirm={() => {
          if (!confirmValidate) return
          validate.mutate(confirmValidate, { onSuccess: () => setConfirmValidate(null) })
        }}
      >
        <p>
          La fase viene segnata come valida con i file attuali, così come sono, senza eseguirla di nuovo. Usalo quando
          la differenza è voluta (per esempio un file modificato a mano).
        </p>
        <p className="mt-2 text-muted-foreground">Le fasi successive costruite su file diversi restano da rifare.</p>
        {validate.isError && <Alert tone="danger" className="mt-3">{errorMessage(validate.error)}</Alert>}
      </ConfirmDialog>

      <BuildConfirmDialog open={confirmBuild} warnings={buildWarnings} onCancel={() => setConfirmBuild(false)} onConfirm={() => {
        setConfirmBuild(false)
        start({ type: 'run_phase', phase: 'build' })
      }} />
    </div>
  )
}
