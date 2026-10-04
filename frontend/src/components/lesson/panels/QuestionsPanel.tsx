import { Brain, ChevronDown, MoreHorizontal, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'

import { errorMessage } from '@/api/client'
import { useJobs } from '@/api/jobs'
import { useRelevance } from '@/api/relevance'
import {
  useDeleteQuestions,
  useGenerateRecall,
  useRecallHistory,
  useRecallQuestions,
  useRecallUnits,
  useSelectRecallUnits,
  type RecallQuestionDetail,
  type RecallType,
} from '@/api/recall'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Chip } from '@/components/ui/chip'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { Select } from '@/components/ui/select'
import { isActive } from '@/lib/jobs'
import { cn } from '@/lib/utils'

const TYPES: { id: RecallType; label: string; plural: string }[] = [
  { id: 'quiz', label: 'Quiz', plural: 'quiz' },
  { id: 'mirata', label: 'Mirata', plural: 'mirate' },
  { id: 'vasta', label: 'Vasta', plural: 'vaste' },
  { id: 'caso', label: 'Caso', plural: 'casi' },
  { id: 'esercizio', label: 'Esercizio', plural: 'esercizi' },
]

const SELECTION_TYPES: RecallType[] = ['quiz', 'mirata', 'caso', 'esercizio']

function formatUnits(units: string[]): string {
  if (units.length === 0) return ''
  if (units.length === 1) return units[0]
  if (units.length === 2) return `${units[0]} e ${units[1]}`
  return `${units.slice(0, -1).join(', ')} e ${units[units.length - 1]}`
}

function formatRecallDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const thatDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diffDays = Math.round((today.getTime() - thatDay.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return 'oggi'
  if (diffDays === 1) return 'ieri'
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

function questionMeta(q: RecallQuestionDetail, hideUnit: boolean): string {
  const typeObj = TYPES.find((t) => t.id === q.type)
  const typeLabel = typeObj ? typeObj.label : q.type
  const parts: string[] = [typeLabel]
  if (!hideUnit && q.unit_ids.length > 0) {
    parts.push(`unità ${q.unit_ids.join(', ')}`)
  }
  if (q.outcome === 'corretta') {
    parts.push('risposta corretta')
  } else if (q.outcome === 'parziale') {
    parts.push('risposta parziale')
  } else if (q.outcome === 'sbagliata') {
    parts.push(q.status === 'asked' ? 'posta, sbagliata' : 'risposta sbagliata')
  } else if (q.status === 'pending') {
    parts.push('da porre')
  } else if (q.status === 'asked') {
    parts.push('posta')
  } else if (q.status === 'answered') {
    parts.push('risposta')
  } else if (q.status === 'discarded') {
    parts.push('scartata')
  }
  return parts.join(' · ')
}

function QuestionRowMenu({ onDelete }: { onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])

  return (
    <div ref={root} className="relative shrink-0">
      <IconButton
        label="Azioni sulla domanda"
        icon={MoreHorizontal}
        className="size-7 min-w-7"
        active={open}
        onClick={() => setOpen(!open)}
      />
      {open && (
        <div
          role="menu"
          aria-label="Azioni sulla domanda"
          className="absolute right-0 top-full z-20 mt-1 min-w-32 rounded-lg border bg-card p-1 shadow-panel"
        >
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-meta text-danger hover:bg-muted focus-visible:bg-muted"
            onClick={() => {
              setOpen(false)
              onDelete()
            }}
          >
            <Trash2 className="size-3.5 shrink-0" aria-hidden />
            Elimina
          </button>
        </div>
      )}
    </div>
  )
}

export function QuestionsPanel({
  lessonId,
  selectedUnits,
  selectedText,
  onSwitchToClassifier,
  onClearSelection,
}: {
  lessonId?: number
  selectedUnits?: string[]
  selectedText?: string
  onSwitchToClassifier?: () => void
  onClearSelection?: () => void
}) {
  const id = lessonId ?? 0
  const questionsQuery = useRecallQuestions(id, false)
  const history = useRecallHistory(id)
  const recallUnits = useRecallUnits(id)
  const selectUnits = useSelectRecallUnits(id)
  const generate = useGenerateRecall(id)
  const deleteQuestions = useDeleteQuestions(id)
  const jobs = useJobs({ lesson_id: id, limit: 10 })
  const relevance = useRelevance(id)

  const [unitModalOpen, setUnitModalOpen] = useState(false)

  // Filtro tipo (solo vista normale)
  const [activeFilter, setActiveFilter] = useState<RecallType | null>(null)

  // Form generazione globale
  const [globalType, setGlobalType] = useState<RecallType>('quiz')
  const [globalCount, setGlobalCount] = useState<string>('10')
  const [globalInstructions, setGlobalInstructions] = useState<string>('')

  // Form generazione su parte
  const [partType, setPartType] = useState<RecallType>('mirata')
  const [partCount, setPartCount] = useState<string>('3')
  const [partInstructions, setPartInstructions] = useState<string>('')

  const isSelectionMode = Boolean(selectedUnits && selectedUnits.length > 0)
  const questionsList = questionsQuery.data?.questions

  const isGenerating =
    generate.isPending ||
    (jobs.data ?? []).some(
      (j) => isActive(j.state) && (j.type === 'recall_generate' || j.type === 'recall_batch') && j.lesson_id === id,
    )

  // Conteggio da porre e conteggio per tipo
  const counts = useMemo(() => {
    const byType: Record<RecallType, number> = {
      quiz: 0,
      mirata: 0,
      vasta: 0,
      caso: 0,
      esercizio: 0,
    }
    let daPorre = 0
    for (const q of questionsList ?? []) {
      if (q.status !== 'discarded') {
        if (q.type in byType) byType[q.type as RecallType]++
        if (q.status === 'pending') daPorre++
      }
    }
    return { byType, daPorre }
  }, [questionsList])

  // Domande filtrate
  const filteredQuestions = useMemo(() => {
    return (questionsList ?? []).filter((q) => {
      if (q.status === 'discarded') return false
      if (isSelectionMode) {
        return q.unit_ids.some((u) => selectedUnits!.includes(u))
      }
      if (activeFilter && q.type !== activeFilter) return false
      return true
    })
  }, [questionsList, isSelectionMode, selectedUnits, activeFilter])

  // Ultimo ripasso
  const lastRecallText = useMemo(() => {
    const answers = history.data?.answers ?? []
    if (answers.length === 0) return 'Nessun ripasso recente'
    const last = answers[answers.length - 1]
    const q = questionsList?.find((item) => item.id === last.question_id)
    const typeLabel = q ? (TYPES.find((t) => t.id === q.type)?.label ?? q.type) : 'Quiz'
    const dateText = last.answered_at ? formatRecallDate(last.answered_at) : ''
    return dateText ? `Ultimo ripasso: ${dateText} · ${typeLabel}` : `Ultimo ripasso · ${typeLabel}`
  }, [history.data, questionsList])

  const handleGlobalGenerate = (e: React.FormEvent) => {
    e.preventDefault()
    const count = parseInt(globalCount, 10) || 10
    generate.mutate(
      {
        qtype: globalType,
        count,
        instructions: globalInstructions.trim() || null,
      },
      {
        onSuccess: () => {
          setGlobalInstructions('')
        },
      },
    )
  }

  const handlePartGenerate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedUnits?.length) return
    const count = parseInt(partCount, 10) || 3
    generate.mutate(
      {
        unit_ids: selectedUnits,
        selection: selectedText || null,
        qtype: partType,
        count,
        instructions: partInstructions.trim() || null,
      },
      {
        onSuccess: () => {
          setPartInstructions('')
        },
      },
    )
  }

  const handleDelete = (questionId: string) => {
    deleteQuestions.mutate([questionId])
  }

  const summary = relevance.data?.summary
  const classifierStatus = !summary
    ? null
    : summary.errors > 0
      ? `${summary.errors} errori`
      : summary.missing + summary.stale > 0
        ? `${summary.missing + summary.stale} unità da classificare`
        : 'aggiornato'
  const unitsData = recallUnits.data
  const totalUnits = unitsData?.units?.length ?? 0
  const selectedUnitsCount = unitsData?.selected ?? unitsData?.units?.filter((u) => u.selected).length ?? 0

  return (
    <div className="flex flex-col gap-3.5" data-testid="questions-panel">
      {generate.isError && <Alert tone="danger">{errorMessage(generate.error)}</Alert>}
      {deleteQuestions.isError && <Alert tone="danger">{errorMessage(deleteQuestions.error)}</Alert>}

      {/* Vista normale: scheda ripassa, filtri per tipo, form genera */}
      {!isSelectionMode && (
        <>
          <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 p-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-body font-semibold">{counts.daPorre} domande da porre</p>
              <p className="text-meta text-muted-foreground">{lastRecallText}</p>
            </div>
            <Link to={`/lezioni/${id}/sessione`} className={cn(buttonVariants({ size: 'sm' }), 'shrink-0')}>
              <Brain aria-hidden />
              Ripassa
            </Link>
          </div>

          <div
            role="group"
            aria-label="Filtra per tipo di domanda"
            className="grid grid-cols-5 gap-1"
          >
            {TYPES.map(({ id: typeId, plural }) => {
              const active = activeFilter === typeId
              const count = counts.byType[typeId]
              return (
                <button
                  key={typeId}
                  type="button"
                  aria-pressed={active}
                  aria-label={`Mostra solo ${plural}`}
                  onClick={() => setActiveFilter(active ? null : typeId)}
                  className={cn(
                    'flex flex-col items-center rounded-lg border p-1.5 text-center transition-colors',
                    active
                      ? 'border-primary bg-primary text-primary-foreground font-semibold'
                      : 'border-border bg-card text-foreground hover:bg-muted/50',
                  )}
                >
                  <span className="text-heading font-semibold leading-tight">{count}</span>
                  <span className="text-meta text-muted-foreground">{plural}</span>
                </button>
              )
            })}
          </div>

          <details className="group rounded-lg border bg-card p-3">
            <summary className="flex cursor-pointer items-center justify-between text-body font-semibold">
              <span>Genera altre domande</span>
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
            </summary>
            <form onSubmit={handleGlobalGenerate} className="mt-3 flex flex-col gap-2.5">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label htmlFor="q-type" className="mb-1 block text-meta text-muted-foreground">
                    Tipo
                  </label>
                  <Select
                    id="q-type"
                    value={globalType}
                    onChange={(e) => setGlobalType(e.target.value as RecallType)}
                  >
                    {TYPES.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.label}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="w-20">
                  <label htmlFor="q-count" className="mb-1 block text-meta text-muted-foreground">
                    Quante
                  </label>
                  <Input
                    id="q-count"
                    type="number"
                    min="1"
                    max="50"
                    value={globalCount}
                    onChange={(e) => setGlobalCount(e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="q-instructions" className="mb-1 block text-meta text-muted-foreground">
                  Direttive (facoltative)
                </label>
                <textarea
                  id="q-instructions"
                  value={globalInstructions}
                  onChange={(e) => setGlobalInstructions(e.target.value)}
                  placeholder="Per esempio: più domande sui valori di riferimento"
                  rows={2}
                  className="block w-full resize-none rounded-md border bg-card px-2.5 py-1.5 text-meta placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
                />
              </div>
              <Button type="submit" variant="default" size="sm" disabled={isGenerating} className="self-start">
                <Sparkles className="mr-1.5 size-3.5" aria-hidden />
                {isGenerating ? 'Generazione in corso…' : 'Genera'}
              </Button>
            </form>
          </details>
        </>
      )}

      {/* Vista selezione parte: scheda e form dedicato */}
      {isSelectionMode && selectedUnits && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-meta text-muted-foreground">
              Filtro su: {formatUnits(selectedUnits)}
            </span>
            {onClearSelection && (
              <button
                type="button"
                onClick={onClearSelection}
                className="text-meta font-medium text-primary hover:underline"
              >
                Mostra tutte le domande
              </button>
            )}
          </div>

          <div className="flex flex-col gap-2.5 rounded-lg border bg-card p-3">
            <p className="text-body font-semibold">
              Nuove domande su {formatUnits(selectedUnits)}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-meta text-muted-foreground">Tipo</span>
              <div role="group" aria-label="Tipo di domanda" className="flex flex-wrap gap-1">
                {SELECTION_TYPES.map((t) => (
                  <Chip
                    key={t}
                    size="sm"
                    active={partType === t}
                    aria-pressed={partType === t}
                    onClick={() => setPartType(t)}
                  >
                    {TYPES.find((x) => x.id === t)?.label ?? t}
                  </Chip>
                ))}
              </div>
              <div className="ml-auto flex items-center gap-1.5">
                <label htmlFor="p-count" className="text-meta text-muted-foreground">
                  Quante
                </label>
                <Input
                  id="p-count"
                  type="number"
                  min="1"
                  max="20"
                  value={partCount}
                  onChange={(e) => setPartCount(e.target.value)}
                  className="h-7 w-14 px-2 py-0 text-center"
                />
              </div>
            </div>

            <details className="text-meta text-muted-foreground">
              <summary className="cursor-pointer font-medium hover:text-foreground">
                Istruzioni aggiuntive (facoltative)
              </summary>
              <textarea
                value={partInstructions}
                onChange={(e) => setPartInstructions(e.target.value)}
                placeholder="Per esempio: concentrati sui valori soglia"
                rows={2}
                aria-label="Istruzioni aggiuntive"
                className="mt-1.5 block w-full resize-none rounded-md border bg-card px-2.5 py-1.5 text-meta text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
              />
            </details>

            <Button
              type="button"
              variant="default"
              size="sm"
              disabled={isGenerating}
              onClick={handlePartGenerate}
              className="self-start"
            >
              <Sparkles className="mr-1.5 size-3.5" aria-hidden />
              {isGenerating ? 'Generazione…' : 'Genera'}
            </Button>
          </div>

          {isGenerating && (
            <div className="flex items-center gap-2.5 rounded-lg border bg-muted/30 p-2.5 text-meta" data-testid="part-generating-banner">
              <div className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-primary border-r-transparent" />
              <span className="flex-1">
                Genero {partCount} domande su {formatUnits(selectedUnits)}…
              </span>
            </div>
          )}
        </div>
      )}

      {/* Intestazione elenco */}
      <div className="mt-1 flex items-center justify-between">
        <h3 className="text-meta font-semibold uppercase tracking-[.05em] text-muted-foreground">
          {isSelectionMode ? `Domande della parte (${filteredQuestions.length})` : 'Domande della lezione'}
        </h3>
        {activeFilter && !isSelectionMode && (
          <button
            type="button"
            onClick={() => setActiveFilter(null)}
            className="text-meta text-primary hover:underline"
          >
            Azzera filtro
          </button>
        )}
      </div>

      {/* Elenco domande */}
      {questionsQuery.isPending && (
        <div className="flex flex-col gap-2 py-2">
          <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-full animate-pulse rounded bg-muted" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
        </div>
      )}

      {questionsQuery.isError && (
        <Alert tone="danger">{errorMessage(questionsQuery.error)}</Alert>
      )}

      {!questionsQuery.isPending && filteredQuestions.length === 0 && (
        <p className="py-4 text-center text-meta text-muted-foreground" data-testid="questions-empty">
          {isSelectionMode
            ? 'Nessuna domanda per questa parte.'
            : activeFilter
              ? 'Nessuna domanda di questo tipo.'
              : 'Nessuna domanda presente.'}
        </p>
      )}

      {filteredQuestions.length > 0 && (
        <ul className="divide-y divide-border" data-testid="questions-list">
          {filteredQuestions.map((q) => {
            const hideUnit = Boolean(isSelectionMode && selectedUnits?.length === 1)
            const meta = questionMeta(q, hideUnit)
            return (
              <li key={q.id} className="flex items-start gap-2 py-2.5 first:pt-1">
                <div className="min-w-0 flex-1">
                  <p className="text-meta text-muted-foreground">
                    {meta}
                  </p>
                  <p className="mt-0.5 text-body">{q.question_text}</p>
                </div>
                <QuestionRowMenu onDelete={() => handleDelete(q.id)} />
              </li>
            )
          })}
        </ul>
      )}

      {/* Footer solo in vista normale */}
      {!isSelectionMode && (
        <div className="mt-auto flex flex-col gap-2 border-t pt-3 text-meta text-muted-foreground">
          <div className="flex items-center justify-between">
            <span>
              Unità per il recaller: {selectedUnitsCount} di {totalUnits}
              {unitsData?.custom ? ' (personalizzata)' : ' (solo rilevanti)'}
            </span>
            <button
              type="button"
              onClick={() => setUnitModalOpen(true)}
              className="font-medium text-primary hover:underline"
            >
              Scegli
            </button>
          </div>
          <div className="flex items-center justify-between">
            <span>Classificatore{classifierStatus ? `: ${classifierStatus}` : ''}</span>
            {onSwitchToClassifier && (
              <button
                type="button"
                onClick={onSwitchToClassifier}
                className="font-medium text-primary hover:underline"
              >
                Rivedi le etichette
              </button>
            )}
          </div>
        </div>
      )}

      {/* Modal selezione unità per il recaller */}
      <Modal
        open={unitModalOpen}
        onClose={() => setUnitModalOpen(false)}
        title="Unità per il recaller"
      >
        <div className="mt-3 flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-meta text-muted-foreground">
            <span>
              {selectedUnitsCount} di {totalUnits} unità selezionate · {unitsData?.custom ? 'scelta personalizzata' : 'solo rilevanti'}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!unitsData?.custom || selectUnits.isPending}
                onClick={() => selectUnits.mutate(null)}
              >
                Solo rilevanti
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={selectUnits.isPending}
                onClick={() => selectUnits.mutate((unitsData?.units ?? []).map((u) => u.unit_id))}
              >
                Tutte
              </Button>
            </div>
          </div>

          {selectUnits.isError && <Alert tone="danger">{errorMessage(selectUnits.error)}</Alert>}

          <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto divide-y divide-border/50" aria-label="Elenco unità per il recaller">
            {(unitsData?.units ?? []).map((u) => {
              const isChecked = u.selected
              const handleToggle = () => {
                const currentRows = unitsData?.units ?? []
                const newIds = currentRows
                  .filter((row) => (row.unit_id === u.unit_id ? !isChecked : row.selected))
                  .map((row) => row.unit_id)
                selectUnits.mutate(newIds)
              }
              return (
                <li key={u.unit_id} className="pt-1.5 first:pt-0">
                  <label
                    className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-body hover:bg-muted"
                    data-testid="recall-unit-choice"
                    data-unit-id={u.unit_id}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={handleToggle}
                      className="size-4 shrink-0 rounded border-input text-primary focus-visible:outline-2 focus-visible:outline-ring"
                    />
                    <span className="shrink-0 font-mono text-meta text-muted-foreground">{u.unit_id}</span>
                    <span className={cn('min-w-0 flex-1 truncate text-body', !u.suggested && 'text-muted-foreground')}>
                      {u.title || `Unità ${u.unit_id}`}
                    </span>
                    {u.category && u.category !== 'didactic' && (
                      <span className="shrink-0 text-meta text-muted-foreground">
                        {u.category === 'organizational' ? 'organizzativa' : 'senza contenuto'}
                      </span>
                    )}
                  </label>
                </li>
              )
            })}
          </ul>

          <div className="mt-2 flex justify-end border-t pt-3">
            <Button variant="default" size="sm" onClick={() => setUnitModalOpen(false)}>
              Fine
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
