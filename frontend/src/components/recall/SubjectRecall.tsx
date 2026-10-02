import { useQueryClient } from '@tanstack/react-query'
import { SkipForward, Square } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage } from '@/api/client'
import { useLessons } from '@/api/hooks'
import {
  recallKeys,
  subjectKeys,
  useAnswer,
  useAnswerVoice,
  useRecallHistory,
  useSkip,
  useSubjectEnd,
  useSubjectGenerate,
  useSubjectNext,
  useSubjectRecall,
  type LessonRecallStats,
} from '@/api/recall'
import { JobProgress } from '@/components/JobProgress'
import { AnsweredQuestion, OpenAnswerForm, QuizForm, SessionSummary } from '@/components/recall/parts'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SlideToggle } from '@/components/ui/slide-toggle'
import { lessonTitle, type Lesson } from '@/lib/format'
import { RECALL_TYPES, TYPE_OPTIONS, countStatus, recallTypeParam, startedAt, typeLabel } from '@/lib/recall'
import { dayLabel } from '@/lib/lessonView'
import { daySubject } from '@/lib/recallView'

/** "della materia" o "del giorno" (la sessione del giorno è una sessione per materia GIORNO:<data>). */
const scopeNoun = (materia: string) => (dayOf(materia) ? 'del giorno' : 'della materia')
const dayOf = (materia: string) => /^GIORNO:(\d{4}-\d{2}-\d{2})$/i.exec(materia)?.[1] ?? null

/** Le lezioni della materia con il loro pool; genera quello delle lezioni che non ne hanno. */
function SubjectLessons({ materia, stats, lessons }: { materia: string; stats: LessonRecallStats[]; lessons: Map<number, Lesson> }) {
  const generate = useSubjectGenerate(materia)
  const client = useQueryClient()
  const [jobs, setJobs] = useState<{ id: string; lessonId: number | null }[]>([])
  const refresh = useCallback(
    () => Promise.all([client.invalidateQueries({ queryKey: subjectKeys.all }), client.invalidateQueries({ queryKey: ['recall'] })]),
    [client],
  )
  const missing = stats.filter((s) => s.ready && Object.keys(s.questions).length === 0).length
  return (
    <Card className="flex flex-col gap-3 p-5" aria-labelledby="subject-lessons-title">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="subject-lessons-title" className="mr-auto text-base font-bold">
          Lezioni {scopeNoun(materia)}
        </h2>
        {missing > 0 && (
          <Button size="sm" disabled={generate.isPending}
            onClick={() => generate.mutate(undefined, { onSuccess: (r) => setJobs(r.jobs.map((j) => ({ id: j.job_id, lessonId: j.lesson_id ?? null }))) })}>
            Genera le domande mancanti ({missing} {missing === 1 ? 'lezione' : 'lezioni'})
          </Button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] text-sm" aria-label="Domande da porre per lezione">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <th className="py-1 font-medium">Lezione</th>
              {RECALL_TYPES.map((t) => (
                <th key={t.value} className="py-1 text-right font-medium">
                  {t.label} <span className="sr-only">da porre</span>
                </th>
              ))}
              <th className="py-1 text-right font-medium">Risposte</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((s) => {
              const lesson = lessons.get(s.lesson_id)
              const title = lesson ? lessonTitle(lesson) : `Lezione ${s.lesson_id}`
              return (
                <tr key={s.lesson_id} className="border-t" data-testid="subject-lesson" data-lesson-id={s.lesson_id}>
                  <td className="py-2 pr-3">
                    {s.ready ? (
                      <Link to={`/lezioni/${s.lesson_id}/recall`} className="font-medium hover:underline">{title}</Link>
                    ) : (
                      <span className="font-medium text-muted-foreground">{title}</span>
                    )}
                    <span className="block text-xs text-muted-foreground">
                      {[lesson?.data, !s.ready ? 'serve prima la rielaborazione' : Object.keys(s.questions).length === 0 ? 'nessuna domanda generata' : null]
                        .filter(Boolean).join(' · ')}
                    </span>
                    {s.telegram && <Badge tone="warning" className="mt-1">In corso su Telegram: esclusa</Badge>}
                  </td>
                  {RECALL_TYPES.map((t) => (
                    <td key={t.value} className="py-2 text-right tabular-nums" data-type={t.value}>
                      {s.ready ? countStatus(s.questions, 'pending', t.value) : '—'}
                    </td>
                  ))}
                  <td className="py-2 text-right tabular-nums text-muted-foreground">{s.ready ? s.answers : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {generate.isError && <Alert tone="danger">{errorMessage(generate.error)}</Alert>}
      {jobs.map((job) => (
        <JobProgress key={job.id} jobId={job.id} onFinished={refresh}
          label={`Domande per ${job.lessonId != null && lessons.get(job.lessonId) ? lessonTitle(lessons.get(job.lessonId)!) : 'la lezione'}`} />
      ))}
    </Card>
  )
}

/** Sessione su tutte le lezioni della materia: stessa logica della sessione di una lezione. */
function SubjectSession({ materia, lessons }: { materia: string; lessons: Map<number, Lesson> }) {
  const [params, setParams] = useSearchParams()
  const qtype = recallTypeParam(params.get('tipo'))
  const lessonId = Number(params.get('lezione')) || 0
  const questionId = params.get('domanda')
  const evaluationJob = params.get('valutazione')
  const state = useSubjectRecall(materia)
  const history = useRecallHistory(lessonId, lessonId > 0)
  const next = useSubjectNext(materia)
  const end = useSubjectEnd(materia)
  const skip = useSkip(lessonId)
  const answer = useAnswer(lessonId)
  const voice = useAnswerVoice(lessonId)
  const transitionLock = useRef(false)
  const client = useQueryClient()
  const refresh = useCallback(
    () => Promise.all([client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }), client.invalidateQueries({ queryKey: subjectKeys.all })]),
    [client, lessonId],
  )

  const question = history.data?.questions.find((q) => q.id === questionId)
  const given = history.data?.answers.find((a) => a.question_id === questionId)
  const session = state.data?.session ?? null
  const lesson = lessons.get(lessonId)

  function update(changes: Record<string, string | null>) {
    const nextParams = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) nextParams.set(k, v)
      else nextParams.delete(k)
    }
    setParams(nextParams, { replace: false })
  }

  function askNext(exclude?: string, afterSkip = false) {
    if ((!afterSkip && transitionLock.current) || next.isPending || (skip.isPending && !afterSkip) || answer.isPending || voice.isPending) return
    transitionLock.current = true
    next.mutate({ qtype, exclude }, {
      onSuccess: (picked) => update({ lezione: String(picked.lesson_id), domanda: picked.question.id, valutazione: null }),
      onSettled: () => { transitionLock.current = false },
    })
  }

  function doSkip() {
    if (!questionId || !lessonId || transitionLock.current || skip.isPending || next.isPending || answer.isPending || voice.isPending) return
    transitionLock.current = true
    skip.mutate(questionId, {
      onSuccess: () => askNext(`${lessonId}:${questionId}`, true),
      onError: () => { transitionLock.current = false },
    })
  }

  const noQuestions = next.error instanceof ApiError && next.error.code === 'no_questions'
  const busy = answer.isPending || voice.isPending
  const writeError = answer.error ?? voice.error ?? skip.error
  const hint = RECALL_TYPES.find((t) => t.value === qtype)!

  return (
    <Card className="flex flex-col gap-4 p-5" aria-labelledby="subject-session-title">
      <h2 id="subject-session-title" className="text-base font-bold">
        Sessione {scopeNoun(materia)}
      </h2>
      <SlideToggle
        label="Tipo di domanda"
        options={TYPE_OPTIONS}
        value={qtype}
        onChange={(v) => update({ tipo: v })}
        description={
          <>
            <strong className="font-semibold text-foreground">{hint.label}</strong>: {hint.hint}. Le lezioni si danno il turno.
          </>
        }
        testId="type-toggle"
        className="max-w-md"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => askNext()} disabled={next.isPending || skip.isPending || busy}>
          Prossima domanda
        </Button>
        {session && (
          <Button size="sm" variant="outline" disabled={end.isPending}
            onClick={() => end.mutate(undefined, { onSuccess: () => update({ lezione: null, domanda: null, valutazione: null }) })}>
            <Square aria-hidden="true" /> Termina sessione
          </Button>
        )}
        {session && (
          <span className="text-xs text-muted-foreground" data-testid="subject-session" data-session-id={session.id}>
            Sessione in corso dalle {startedAt(session.started_at)} · domande poste: {session.questions}
          </span>
        )}
      </div>
      {end.isError && <Alert tone="danger">{errorMessage(end.error)}</Alert>}
      {!session && state.data?.last && <SessionSummary session={state.data.last} />}

      {noQuestions && <Alert tone="warning">Nessuna domanda di questo tipo da porre nelle lezioni {scopeNoun(materia)}: generane altre.</Alert>}
      {next.isError && !noQuestions && <Alert tone="danger">{errorMessage(next.error)}</Alert>}
      {history.isError && <Alert tone="danger">{errorMessage(history.error)}</Alert>}
      {!questionId && !noQuestions && !state.data?.last && (
        <p className="text-sm text-muted-foreground">Scegli il tipo e chiedi la prossima domanda: arriva a turno da ognuna delle lezioni.</p>
      )}
      {questionId && history.isSuccess && !question && <Alert tone="warning">Domanda non trovata: chiedi la prossima.</Alert>}

      {question && (
        <article className="flex flex-col gap-3" data-testid="recall-question" data-question-id={question.id} data-type={question.type} data-lesson-id={lessonId}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{typeLabel(question.type)}</Badge>
            <Link to={`/lezioni/${lessonId}`} className="text-xs font-medium text-link hover:underline" data-testid="question-lesson">
              {lesson ? lessonTitle(lesson) : `Lezione ${lessonId}`}
            </Link>
            <span className="text-xs text-muted-foreground">
              {[lesson?.data, question.unit_ids.join(', ')].filter(Boolean).join(' · ')}
            </span>
          </div>
          <p className="text-base font-medium leading-relaxed">{question.question_text}</p>

          {given ? (
            <AnsweredQuestion question={question} answer={given} lessonId={lessonId} />
          ) : evaluationJob ? (
            <JobProgress jobId={evaluationJob} label="Valutazione della risposta" onFinished={refresh} />
          ) : question.type === 'quiz' ? (
            <QuizForm question={question} pending={busy}
              onAnswer={(choice) => answer.mutate({ questionId: question.id, choice }, { onSuccess: () => void refresh() })} />
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
            <Button variant="ghost" size="sm" className="self-start" onClick={doSkip} disabled={skip.isPending || next.isPending || busy}>
              <SkipForward /> Salta
            </Button>
          )}
        </article>
      )}
    </Card>
  )
}

/** /recall/materie/:materia: recall su tutte le lezioni di una materia; /recall/giorno/:day
 * (Recall del giorno): su tutte le lezioni di una data. */
export function SubjectRecallPage() {
  const params = useParams()
  const materia = params.day ? daySubject(params.day) : (params.materia ?? '')
  const day = dayOf(materia)
  const noun = scopeNoun(materia)
  const state = useSubjectRecall(materia)
  const all = useLessons()
  const lessons = new Map((all.data ?? []).map((l) => [l.id, l]))
  const ready = (state.data?.lessons ?? []).filter((l) => l.ready).length
  return (
    <section className="flex flex-col gap-4">
      <Link to="/recall" className="text-xs text-muted-foreground hover:underline">
        ← Recall: tutte le lezioni
      </Link>
      <h1 className="text-xl font-bold tracking-tight">
        {day ? `Recall del giorno · ${dayLabel(day)}` : `Recall · ${state.data?.materia ?? materia}`}
      </h1>
      {state.isPending && <p className="text-sm text-muted-foreground">Carico le lezioni…</p>}
      {state.isError && <Alert tone="danger">{errorMessage(state.error)}</Alert>}
      {state.data && state.data.lessons.length === 0 && (
        <Alert tone="warning">{day ? 'Nessuna lezione in questo giorno.' : 'Nessuna lezione di questa materia.'}</Alert>
      )}
      {state.data && state.data.lessons.length > 0 && (
        <>
          <SubjectLessons materia={materia} stats={state.data.lessons} lessons={lessons} />
          {ready > 0 ? (
            <SubjectSession materia={materia} lessons={lessons} />
          ) : (
            <Alert tone="warning">Nessuna lezione {noun} ha ancora una rielaborazione valida: il recall parte dal draft.</Alert>
          )}
        </>
      )}
    </section>
  )
}
