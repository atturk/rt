import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { ArrowLeft, CircleAlert, CircleCheck, CircleX, List, Mic } from 'lucide-react'

import { useRecallHistory } from '@/api/recall'
import type { Schemas } from '@/api/client'
import { MathText } from '@/components/MathText'
import { IconButton } from '@/components/ui/icon-button'
import { cn } from '@/lib/utils'

type OutcomeFilter = 'tutte' | 'sbagliata' | 'parziale' | 'corretta'

function formatShortDateTime(isoStr: string): string {
  try {
    const d = new Date(isoStr)
    if (isNaN(d.getTime())) return isoStr
    return `${d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })}, ${d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}`
  } catch {
    return isoStr
  }
}

export function RecallAnswersPage() {
  const { lessonId } = useParams()
  const id = Number(lessonId) || 0
  const navigate = useNavigate()
  const { data, isPending } = useRecallHistory(id)

  const [filter, setFilter] = useState<OutcomeFilter>('tutte')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const toggleExpand = (key: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const questionsById = useMemo(() => {
    const map = new Map<string, Schemas['RecallQuestion']>()
    for (const q of data?.questions ?? []) {
      map.set(q.id, q)
    }
    return map
  }, [data?.questions])

  const groups = useMemo(() => {
    const answers = data?.answers ?? []
    const map = new Map<string, Schemas['RecallAnswerRecord'][]>()
    for (const a of answers) {
      const list = map.get(a.question_id) ?? []
      list.push(a)
      map.set(a.question_id, list)
    }

    for (const list of map.values()) {
      list.sort((x, y) => (y.answered_at > x.answered_at ? 1 : -1))
    }

    const result: {
      questionId: string
      question: Schemas['RecallQuestion'] | undefined
      answers: Schemas['RecallAnswerRecord'][]
    }[] = []

    for (const [qid, list] of map.entries()) {
      const filtered = filter === 'tutte' ? list : list.filter((a) => a.outcome === filter)
      if (filtered.length > 0) {
        result.push({
          questionId: qid,
          question: questionsById.get(qid),
          answers: filtered,
        })
      }
    }

    result.sort((x, y) => {
      const tx = x.answers[0]?.answered_at ?? ''
      const ty = y.answers[0]?.answered_at ?? ''
      return ty > tx ? 1 : -1
    })

    return result
  }, [data?.answers, questionsById, filter])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4 sm:p-6" data-testid="recall-answers-page">
      {/* Intestazione con pulsante Indietro e Filtro a icone */}
      <div className="flex items-center justify-between gap-3 border-b pb-4">
        <IconButton
          label="Torna alle domande"
          icon={ArrowLeft}
          onClick={() => navigate(`/lezioni/${id}?panel=domande`)}
        />
        <div role="group" aria-label="Filtra per esito" className="flex items-center gap-1.5" data-testid="outcome-filter">
          <IconButton
            label="Tutte"
            icon={List}
            active={filter === 'tutte'}
            onClick={() => setFilter('tutte')}
          />
          <IconButton
            label="Sbagliate"
            icon={CircleX}
            active={filter === 'sbagliata'}
            className={filter === 'sbagliata' ? '' : 'text-danger hover:text-danger'}
            onClick={() => setFilter((curr) => (curr === 'sbagliata' ? 'tutte' : 'sbagliata'))}
          />
          <IconButton
            label="Parziali"
            icon={CircleAlert}
            active={filter === 'parziale'}
            className={filter === 'parziale' ? '' : 'text-warning hover:text-warning'}
            onClick={() => setFilter((curr) => (curr === 'parziale' ? 'tutte' : 'parziale'))}
          />
          <IconButton
            label="Corrette"
            icon={CircleCheck}
            active={filter === 'corretta'}
            className={filter === 'corretta' ? '' : 'text-success hover:text-success'}
            onClick={() => setFilter((curr) => (curr === 'corretta' ? 'tutte' : 'corretta'))}
          />
        </div>
      </div>

      {/* Caricamento o stato vuoto */}
      {isPending && (
        <div className="flex flex-col gap-4 py-8">
          <div className="h-6 w-1/3 animate-pulse rounded bg-muted" />
          <div className="h-16 w-full animate-pulse rounded bg-muted" />
          <div className="h-16 w-full animate-pulse rounded bg-muted" />
        </div>
      )}

      {!isPending && groups.length === 0 && (
        <p className="py-12 text-center text-meta text-muted-foreground" data-testid="empty-answers">
          Nessuna risposta.
        </p>
      )}

      {/* Elenco domande e tentativi */}
      {!isPending && groups.length > 0 && (
        <div className="flex flex-col gap-5">
          {groups.map((group) => {
            const qText = group.question?.question_text || group.questionId
            return (
              <div
                key={group.questionId}
                className="flex flex-col gap-2 rounded-xl border bg-card p-4 shadow-sm"
                data-testid="question-group"
                data-question-id={group.questionId}
              >
                <div className="text-body font-semibold leading-snug">
                  <MathText text={qText} />
                </div>

                <div className="mt-1 flex flex-col divide-y divide-border/60">
                  {group.answers.map((ans, idx) => {
                    const rowKey = ans.attempt_id || `${group.questionId}-${idx}-${ans.answered_at}`
                    const isExpanded = expandedIds.has(rowKey)
                    return (
                      <div key={rowKey} className="flex flex-col py-2.5 first:pt-1 last:pb-1">
                        <button
                          type="button"
                          onClick={() => toggleExpand(rowKey)}
                          className="flex w-full items-start justify-between gap-3 text-left transition-opacity hover:opacity-80"
                          data-testid="answer-row"
                        >
                          <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
                            {ans.is_voice && <Mic className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                            {ans.dont_know ? (
                              <span className="italic text-muted-foreground">Non lo so</span>
                            ) : (
                              <span className="font-normal">
                                <MathText text={ans.answer_text} />
                              </span>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-2.5">
                            <span
                              className={cn(
                                'text-xs font-medium',
                                ans.outcome === 'corretta'
                                  ? 'text-success'
                                  : ans.outcome === 'parziale'
                                    ? 'text-warning'
                                    : ans.outcome === 'sbagliata'
                                      ? 'text-danger'
                                      : 'text-foreground',
                              )}
                            >
                              {ans.outcome === 'corretta'
                                ? 'Corretta'
                                : ans.outcome === 'parziale'
                                  ? 'Parziale'
                                  : ans.outcome === 'sbagliata'
                                    ? 'Sbagliata'
                                    : 'Risposta'}
                            </span>
                            <span className="text-meta text-muted-foreground">
                              {formatShortDateTime(ans.answered_at)}
                            </span>
                          </div>
                        </button>

                        {/* Valutazione espandibile */}
                        {isExpanded && ans.evaluation && (
                          <div
                            className={cn(
                              'mt-2.5 rounded-lg border p-3 text-sm',
                              ans.outcome === 'corretta'
                                ? 'border-success/30 bg-success-soft'
                                : ans.outcome === 'parziale'
                                  ? 'border-warning/30 bg-warning-soft'
                                  : ans.outcome === 'sbagliata'
                                    ? 'border-danger/30 bg-danger-soft'
                                    : 'bg-muted/40',
                            )}
                            data-testid="answer-evaluation"
                          >
                            <p
                              className={cn(
                                'mb-1 text-xs font-semibold',
                                ans.outcome === 'corretta'
                                  ? 'text-success'
                                  : ans.outcome === 'parziale'
                                    ? 'text-warning'
                                    : ans.outcome === 'sbagliata'
                                      ? 'text-danger'
                                      : 'text-foreground',
                              )}
                            >
                              {ans.outcome === 'corretta'
                                ? 'Giusto.'
                                : ans.outcome === 'parziale'
                                  ? 'Risposta parziale.'
                                  : ans.outcome === 'sbagliata'
                                    ? 'Sbagliata.'
                                    : 'Valutazione'}
                            </p>
                            <div className="text-meta leading-relaxed">
                              <MathText text={ans.evaluation} />
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
