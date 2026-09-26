import { useQueryClient } from '@tanstack/react-query'
import { Brain, SkipForward, ThumbsDown, ThumbsUp, Zap } from 'lucide-react'
import { useCallback, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage } from '@/api/client'
import { useLesson } from '@/api/hooks'
import {
  recallKeys,
  useAnswer,
  useAnswerVoice,
  useGenerateRecall,
  useNextQuestion,
  useRecallHistory,
  useRecallOverview,
  useSkip,
  useVote,
  type RecallAnswerRecord,
  type RecallQuestion,
  type RecallType,
  type Vote,
} from '@/api/recall'
import { JobProgress } from '@/components/JobProgress'
import { LessonPicker } from '@/components/LessonPicker'
import { VoiceRecorder } from '@/components/VoiceRecorder'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { lessonTitle } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Area } from './types'

const RECALL_TYPES: { value: RecallType; label: string; hint: string }[] = [
  { value: 'quiz', label: 'Quiz', hint: 'Scelta multipla, esito immediato' },
  { value: 'mirata', label: 'Mirata', hint: 'Domanda aperta su un punto preciso' },
  { value: 'vasta', label: 'Vasta', hint: 'Domanda aperta di collegamento' },
]
const STATUS_LABELS: Record<string, string> = { pending: 'Da porre', asked: 'Poste', answered: 'Risposte' }
const VOTES: { value: Vote; label: string; icon: typeof ThumbsUp }[] = [
  { value: 'up', label: 'Domanda utile', icon: ThumbsUp },
  { value: 'down', label: 'Domanda da scartare', icon: ThumbsDown },
  { value: 'lightning', label: 'Domanda fulminante', icon: Zap },
]

function typeLabel(type: string) {
  return RECALL_TYPES.find((t) => t.value === type)?.label ?? type
}

function RecallIndex() {
  return (
    <LessonPicker
      title="Active recall"
      intro="Scegli una lezione per ripassarla con domande a scelta multipla o aperte, anche a voce."
      href={(l) => `/lezioni/${l.id}/recall`}
      ready={(l) => l.phases.rewrite === 'VALID'}
      notReady="serve prima la rielaborazione"
    />
  )
}

/** Riserva di domande per tipo e generazione (job recall_generate o recall_batch). */
function Reserve({ lessonId }: { lessonId: number }) {
  const overview = useRecallOverview(lessonId)
  const generate = useGenerateRecall(lessonId)
  const client = useQueryClient()
  const [job, setJob] = useState<{ id: string; label: string } | null>(null)
  const refresh = useCallback(() => client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }), [client, lessonId])
  const counts = overview.data?.questions ?? {}
  const empty = Object.keys(counts).length === 0

  function start(qtype: RecallType | null) {
    generate.mutate(qtype, {
      onSuccess: (accepted) => setJob({ id: accepted.job_id, label: qtype ? `Nuove domande ${typeLabel(qtype).toLowerCase()}` : 'Riserva iniziale' }),
    })
  }

  return (
    <Card className="flex flex-col gap-3 p-5" aria-labelledby="reserve-title">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="reserve-title" className="mr-auto text-base font-bold">
          Riserva di domande
        </h2>
        <Button size="sm" onClick={() => start(null)} disabled={generate.isPending}>
          {empty ? 'Genera la riserva iniziale' : 'Completa la riserva'}
        </Button>
      </div>
      {overview.isError && <Alert tone="danger">{errorMessage(overview.error)}</Alert>}
      <table className="w-full text-sm" aria-label="Domande per tipo">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground">
            <th className="py-1 font-medium">Tipo</th>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <th key={k} className="py-1 text-right font-medium">
                {v}
              </th>
            ))}
            <th className="sr-only">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {RECALL_TYPES.map((t) => (
            <tr key={t.value} className="border-t" data-testid="reserve-row" data-type={t.value}>
              <td className="py-2 font-medium">{t.label}</td>
              {Object.keys(STATUS_LABELS).map((status) => (
                <td key={status} className="py-2 text-right tabular-nums" data-status={status}>
                  {counts[t.value]?.[status] ?? 0}
                </td>
              ))}
              <td className="py-2 pl-3 text-right">
                <Button size="sm" variant="outline" onClick={() => start(t.value)} disabled={generate.isPending}>
                  Genera altre <span className="sr-only">{t.label.toLowerCase()}</span>
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">Risposte date: {overview.data?.answers ?? 0}</p>
      {generate.isError && <Alert tone="danger">{errorMessage(generate.error)}</Alert>}
      {job && <JobProgress jobId={job.id} label={job.label} onFinished={refresh} />}
    </Card>
  )
}

function VoteButtons({ lessonId, questionId, current }: { lessonId: number; questionId: string; current?: string | null }) {
  const vote = useVote(lessonId)
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Voto sulla domanda">
      {VOTES.map(({ value, label, icon: Icon }) => (
        <Button
          key={value}
          size="icon"
          variant={current === value ? 'default' : 'outline'}
          aria-label={label}
          title={label}
          aria-pressed={current === value}
          disabled={vote.isPending}
          onClick={() => vote.mutate({ questionId, vote: value })}
        >
          <Icon />
        </Button>
      ))}
      {vote.isError && <span className="text-xs text-danger">{errorMessage(vote.error)}</span>}
    </div>
  )
}

/** Esito di una domanda già risposta, tutto riletto dallo storico dell'API. */
function AnsweredQuestion({ question, answer, lessonId }: { question: RecallQuestion; answer: RecallAnswerRecord; lessonId: number }) {
  const isQuiz = question.type === 'quiz'
  const correct = isQuiz && question.options && question.correct_index != null ? question.options[question.correct_index] : null
  return (
    <div className="flex flex-col gap-3" data-testid="recall-result">
      {isQuiz ? (
        <>
          <ol className="flex flex-col gap-1.5">
            {question.options?.map((option, i) => (
              <li
                key={i}
                className={cn(
                  'rounded-md border px-3 py-2 text-sm',
                  i === question.correct_index && 'border-success bg-success-soft text-success',
                  option === answer.answer_text && i !== question.correct_index && 'border-danger bg-danger-soft text-danger',
                )}
              >
                {option}
              </li>
            ))}
          </ol>
          <Alert tone={answer.answer_text === correct ? 'neutral' : 'warning'}>
            {answer.answer_text === correct ? 'Risposta corretta.' : `Risposta sbagliata: la corretta è «${correct}».`}
          </Alert>
        </>
      ) : (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            La tua risposta{answer.is_voice ? ' (vocale, trascritta)' : ''}
          </span>
          <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm" data-testid="recall-answer">
            {answer.answer_text}
          </p>
        </div>
      )}
      {(answer.evaluation || question.explanation) && (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted-foreground">{isQuiz ? 'Spiegazione' : 'Valutazione'}</span>
          <p className="whitespace-pre-wrap text-sm" data-testid="recall-evaluation">
            {answer.evaluation || question.explanation}
          </p>
        </div>
      )}
      <VoteButtons lessonId={lessonId} questionId={question.id} current={answer.vote} />
    </div>
  )
}

function QuizForm({ question, onAnswer, pending }: { question: RecallQuestion; onAnswer: (choice: number) => void; pending: boolean }) {
  const [choice, setChoice] = useState<number | null>(null)
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (choice !== null) onAnswer(choice)
      }}
      className="flex flex-col gap-2"
    >
      <fieldset className="flex flex-col gap-1.5">
        <legend className="sr-only">Opzioni</legend>
        {question.options?.map((option, i) => (
          <label key={i} className="flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted has-[:checked]:border-foreground">
            <input type="radio" name="choice" value={i} checked={choice === i} onChange={() => setChoice(i)} className="mt-0.5" />
            {option}
          </label>
        ))}
      </fieldset>
      <Button type="submit" className="self-start" disabled={choice === null || pending}>
        Rispondi
      </Button>
    </form>
  )
}

function OpenAnswerForm({
  onWritten,
  onVoice,
  pending,
}: {
  onWritten: (answer: string) => void
  onVoice: (audio: File) => void
  pending: boolean
}) {
  const [text, setText] = useState('')
  function submit(e: FormEvent) {
    e.preventDefault()
    if (text.trim()) onWritten(text.trim())
  }
  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={submit} className="flex flex-col gap-2">
        <Label htmlFor="recall-answer">Risposta scritta</Label>
        <textarea
          id="recall-answer"
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
        />
        <Button type="submit" className="self-start" disabled={!text.trim() || pending}>
          Invia la risposta
        </Button>
      </form>
      <VoiceRecorder onRecorded={onVoice} disabled={pending} />
    </div>
  )
}

function Session({ lessonId }: { lessonId: number }) {
  const [params, setParams] = useSearchParams()
  const qtype = (RECALL_TYPES.some((t) => t.value === params.get('tipo')) ? params.get('tipo') : 'quiz') as RecallType
  const questionId = params.get('domanda')
  const evaluationJob = params.get('valutazione')
  const history = useRecallHistory(lessonId)
  const next = useNextQuestion(lessonId)
  const skip = useSkip(lessonId)
  const answer = useAnswer(lessonId)
  const voice = useAnswerVoice(lessonId)
  const client = useQueryClient()
  const refresh = useCallback(() => client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }), [client, lessonId])

  const question = history.data?.questions.find((q) => q.id === questionId)
  const given = history.data?.answers.find((a) => a.question_id === questionId)

  function update(changes: Record<string, string | null>) {
    const nextParams = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) nextParams.set(k, v)
      else nextParams.delete(k)
    }
    setParams(nextParams, { replace: false })
  }

  function askNext(excludeId?: string) {
    next.mutate({ qtype, excludeId }, { onSuccess: (q) => update({ domanda: q.id, valutazione: null }) })
  }

  function doSkip() {
    if (!questionId) return
    skip.mutate(questionId, { onSuccess: () => askNext(questionId) })
  }

  const noQuestions = next.error instanceof ApiError && next.error.code === 'no_questions'
  const busy = answer.isPending || voice.isPending
  const writeError = answer.error ?? voice.error ?? skip.error

  return (
    <Card className="flex flex-col gap-4 p-5" aria-labelledby="session-title">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="session-title" className="mr-auto text-base font-bold">
          Sessione
        </h2>
        <div role="radiogroup" aria-label="Tipo di domanda" className="flex gap-1">
          {RECALL_TYPES.map((t) => (
            <Button
              key={t.value}
              size="sm"
              role="radio"
              aria-checked={qtype === t.value}
              variant={qtype === t.value ? 'default' : 'outline'}
              title={t.hint}
              onClick={() => update({ tipo: t.value })}
            >
              {t.label}
            </Button>
          ))}
        </div>
        <Button size="sm" onClick={() => askNext()} disabled={next.isPending}>
          Prossima domanda
        </Button>
      </div>

      {noQuestions && <Alert tone="warning">Nessuna domanda di questo tipo da porre: generane altre dalla riserva.</Alert>}
      {next.isError && !noQuestions && <Alert tone="danger">{errorMessage(next.error)}</Alert>}
      {history.isError && <Alert tone="danger">{errorMessage(history.error)}</Alert>}
      {!questionId && !noQuestions && (
        <p className="text-sm text-muted-foreground">Scegli il tipo e chiedi la prossima domanda.</p>
      )}
      {questionId && history.isSuccess && !question && <Alert tone="warning">Domanda non trovata: chiedi la prossima.</Alert>}

      {question && (
        <article className="flex flex-col gap-3" data-testid="recall-question" data-question-id={question.id} data-type={question.type}>
          <div className="flex items-center gap-2">
            <Badge>{typeLabel(question.type)}</Badge>
            <span className="text-xs text-muted-foreground">{question.unit_ids.join(', ')}</span>
          </div>
          <p className="text-base font-medium leading-relaxed">{question.question_text}</p>

          {given ? (
            <AnsweredQuestion question={question} answer={given} lessonId={lessonId} />
          ) : evaluationJob ? (
            <JobProgress jobId={evaluationJob} label="Valutazione della risposta" onFinished={refresh} />
          ) : question.type === 'quiz' ? (
            <QuizForm question={question} pending={busy} onAnswer={(choice) => answer.mutate({ questionId: question.id, choice })} />
          ) : (
            <OpenAnswerForm
              pending={busy}
              onWritten={(text) =>
                answer.mutate({ questionId: question.id, answer: text }, { onSuccess: (r) => r.job && update({ valutazione: r.job.job_id }) })
              }
              onVoice={(audio) => voice.mutate({ questionId: question.id, audio }, { onSuccess: (j) => update({ valutazione: j.job_id }) })}
            />
          )}

          {writeError && <Alert tone="danger">{errorMessage(writeError)}</Alert>}
          {!given && !evaluationJob && (
            <Button variant="ghost" size="sm" className="self-start" onClick={doSkip} disabled={skip.isPending || next.isPending}>
              <SkipForward /> Salta
            </Button>
          )}
        </article>
      )}
    </Card>
  )
}

function History({ lessonId }: { lessonId: number }) {
  const history = useRecallHistory(lessonId)
  const byId = new Map(history.data?.questions.map((q) => [q.id, q]))
  const answers = [...(history.data?.answers ?? [])].sort((a, b) => b.answered_at.localeCompare(a.answered_at))
  return (
    <Card className="flex flex-col gap-3 p-5" aria-labelledby="history-title">
      <h2 id="history-title" className="text-base font-bold">
        Storico
      </h2>
      {answers.length === 0 && <p className="text-sm text-muted-foreground">Nessuna risposta ancora.</p>}
      <ul className="flex flex-col divide-y">
        {answers.map((a) => {
          const q = byId.get(a.question_id)
          return (
            <li key={a.question_id} className="flex flex-col gap-1 py-3" data-testid="history-item" data-question-id={a.question_id}>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge>{typeLabel(q?.type ?? '')}</Badge>
                {a.is_voice && <Badge tone="warning">Vocale</Badge>}
                {a.vote && <span data-testid="history-vote">Voto: {VOTES.find((v) => v.value === a.vote)?.label ?? a.vote}</span>}
                <time dateTime={a.answered_at}>{new Date(a.answered_at).toLocaleString('it-IT')}</time>
              </div>
              <p className="text-sm font-medium">{q?.question_text ?? a.question_id}</p>
              <p className="text-sm">
                <span className="text-muted-foreground">Risposta: </span>
                {a.answer_text}
              </p>
              {a.evaluation && q?.type !== 'quiz' && <p className="whitespace-pre-wrap text-sm text-muted-foreground">{a.evaluation}</p>}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

export function RecallPage() {
  const id = Number(useParams().lessonId)
  const lesson = useLesson(id)
  if (lesson.isPending) return <p className="text-sm text-muted-foreground">Carico la lezione…</p>
  if (lesson.isError) return <Alert tone="danger">{errorMessage(lesson.error)}</Alert>
  const ready = lesson.data.phases.rewrite === 'VALID'
  return (
    <section className="flex flex-col gap-4">
      <Link to="/recall" className="text-xs text-muted-foreground hover:underline">
        ← Recall: tutte le lezioni
      </Link>
      <h1 className="text-xl font-bold tracking-tight">
        Recall · {lessonTitle(lesson.data)}
      </h1>
      {ready ? (
        <>
          <Reserve lessonId={id} />
          <Session lessonId={id} />
          <History lessonId={id} />
        </>
      ) : (
        <Alert tone="warning">La lezione non ha ancora una rielaborazione valida: il recall parte dal draft.</Alert>
      )}
    </section>
  )
}

export const recallArea: Area = {
  routes: [
    { path: 'recall', element: <RecallIndex /> },
    { path: 'lezioni/:lessonId/recall', element: <RecallPage /> },
  ],
  nav: [{ to: '/recall', label: 'Recall', icon: Brain }],
}
