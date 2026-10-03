import { useQueryClient } from '@tanstack/react-query'
import { Monitor, Send, SkipForward, Square } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ApiError, errorMessage } from '@/api/client'
import { useLesson } from '@/api/hooks'
import {
  recallKeys,
  useAnswer,
  useAnswerVoice,
  useEndSession,
  useGenerateRecall,
  useNextQuestion,
  useRecallHistory,
  useRecallOverview,
  useRecallSession,
  useSkip,
  useStartTelegram,
  useStopTelegram,
  useTelegramRecall,
  type RecallSessionInfo,
  type RecallType,
} from '@/api/recall'
import { ClassificationNotice } from '@/components/ClassificationNotice'
import { JobProgress } from '@/components/JobProgress'
import { AnsweredQuestion, OpenAnswerForm, QuizForm, SessionSummary } from '@/components/recall/parts'
import { UnitSelector } from '@/components/recall/UnitSelector'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SlideToggle, type SlideOption } from '@/components/ui/slide-toggle'
import { lessonTitle } from '@/lib/format'
import { RECALL_TYPES, TYPE_OPTIONS, VOTES, recallTypeParam, startedAt, typeLabel } from '@/lib/recall'

// Le altre pagine del recall, nello stesso chunk di questa (routes/index.tsx).
export { QuestionsPage } from '@/components/recall/QuestionsPage'
export { RecallOverviewPage } from '@/components/recall/RecallOverview'
export { SubjectRecallPage } from '@/components/recall/SubjectRecall'

const PLURAL: Record<RecallType, string> = { quiz: 'quiz', mirata: 'mirate', vasta: 'vaste', caso: 'casi', esercizio: 'esercizi' }
const STATUS_LABELS: Record<string, string> = { pending: 'Da porre', asked: 'Poste', answered: 'Risposte' }

/** Pool di domande per tipo, unità del recaller e generazione (job recall_generate o recall_batch). */
function Pool({ lessonId }: { lessonId: number }) {
  const overview = useRecallOverview(lessonId)
  const generate = useGenerateRecall(lessonId)
  const client = useQueryClient()
  const [job, setJob] = useState<{ id: string; label: string } | null>(null)
  const refresh = useCallback(() => client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }), [client, lessonId])
  const counts = overview.data?.questions ?? {}
  const empty = Object.keys(counts).length === 0
  const thresholds = overview.data?.refill_thresholds ?? {}

  function start(qtype: RecallType | null) {
    generate.mutate(qtype, {
      onSuccess: (accepted) => setJob({ id: accepted.job_id, label: qtype ? `Nuove domande ${typeLabel(qtype).toLowerCase()}` : 'Pool di domande' }),
    })
  }

  return (
    <Card className="flex flex-col gap-3 p-5" aria-labelledby="pool-title">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="pool-title" className="mr-auto text-base font-bold">
          Pool di domande
        </h2>
        <Button size="sm" onClick={() => start(null)} disabled={generate.isPending}>
          {empty ? 'Genera il pool' : 'Rigenera pool'}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {empty ? 'Genera il pool' : 'Rigenera pool'} passa al recaller tutte le unità selezionate
        {empty ? '.' : ', che aggiunge domande nuove a quelle già generate.'}
        {Object.keys(thresholds).length > 0 &&
          ` Quando restano ${RECALL_TYPES.map((t) => `${thresholds[t.value]} ${PLURAL[t.value]}`).join(', ')} da porre, il recaller ne genera altre da unità selezionate a caso.`}
      </p>
      <ClassificationNotice lessonId={lessonId} compact />
      <UnitSelector lessonId={lessonId} />
      {!empty && (
        <Link to={`/lezioni/${lessonId}/recall/domande`} className="self-start text-sm underline-offset-4 hover:underline" data-testid="questions-link">
          Rivedi le domande generate
        </Link>
      )}
      {overview.isError && <Alert tone="danger">{errorMessage(overview.error)}</Alert>}
      {!!overview.data?.legacy_pending && <Alert>Ci sono domande generate prima della nuova politica di pertinenza. Generare altre domande conserva risposte e voti precedenti.</Alert>}
      {!!overview.data?.evaluated_empty && <Alert>Alcune unità sono state valutate senza trovare altre domande pertinenti. Puoi rivalutarle con Genera altre.</Alert>}
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
            <tr key={t.value} className="border-t" data-testid="pool-row" data-type={t.value}>
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

type Place = 'telegram' | 'qui'

const PLACES: SlideOption<Place>[] = [
  { value: 'telegram', label: 'Telegram', icon: <Send aria-hidden="true" /> },
  { value: 'qui', label: 'Qui', icon: <Monitor aria-hidden="true" /> },
]
/** Una sessione in corso su Telegram, con "Interrompi". */
function TelegramSessionRow({ session, current }: { session: RecallSessionInfo; current: boolean }) {
  const stop = useStopTelegram()
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-accent-foreground/30 bg-accent px-3 py-2 text-sm text-accent-foreground"
      data-testid="telegram-session"
      data-session-id={session.id}
      data-lesson-id={session.lesson_id ?? ''}
    >
      <Send className="size-4 shrink-0" aria-hidden="true" />
      <span className="mr-auto">
        {current ? 'Sessione in corso su Telegram' : <>In corso su Telegram: <strong>{session.lesson_title || 'altra lezione'}</strong></>}
        {session.qtype && <> · {typeLabel(session.qtype)}</>} · dalle {startedAt(session.started_at)}
      </span>
      {!current && session.lesson_id != null && (
        <Link to={`/lezioni/${session.lesson_id}/recall`} className="text-xs underline-offset-4 hover:underline">
          Apri
        </Link>
      )}
      <Button size="sm" variant="outline" disabled={stop.isPending} onClick={() => stop.mutate(session.id)}>
        <Square aria-hidden="true" /> Interrompi
      </Button>
      {stop.isError && <span className="w-full text-xs text-danger">{errorMessage(stop.error)}</span>}
    </div>
  )
}

function Session({ lessonId }: { lessonId: number }) {
  const [params, setParams] = useSearchParams()
  const qtype = recallTypeParam(params.get('tipo'))
  const questionId = params.get('domanda')
  const evaluationJob = params.get('valutazione')
  const history = useRecallHistory(lessonId)
  const session = useRecallSession(lessonId)
  const bot = useTelegramRecall()
  const next = useNextQuestion(lessonId)
  const skip = useSkip(lessonId)
  const transitionLock = useRef(false)
  const answer = useAnswer(lessonId)
  const voice = useAnswerVoice(lessonId)
  const end = useEndSession(lessonId)
  const startTelegram = useStartTelegram(lessonId)
  const client = useQueryClient()
  const refresh = useCallback(() => client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }), [client, lessonId])

  const question = history.data?.questions.find((q) => q.id === questionId)
  const given = history.data?.answers.find((a) => a.question_id === questionId)
  const web = session.data?.web ?? null
  const telegram = session.data?.telegram ?? null
  const command = session.data?.command ?? null
  // Telegram spento (il predefinito): il recall si fa solo qui, la scelta del posto non c'è
  const telegramOn = bot.data?.enabled === true
  const botReady = telegramOn && !!bot.data?.configured && !!bot.data?.running
  const requested = params.get('luogo')
  const place: Place = requested === 'telegram' || requested === 'qui' ? requested : telegram ? 'telegram' : 'qui'
  const placeLocked = !botReady && !telegram
  const effectivePlace: Place = placeLocked ? 'qui' : place
  const others = (bot.data?.sessions ?? []).filter((s) => s.lesson_id !== lessonId)
  const commandPending = command?.kind === 'start_recall' && (command.state === 'pending' || command.state === 'running')

  function update(changes: Record<string, string | null>) {
    const nextParams = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) nextParams.set(k, v)
      else nextParams.delete(k)
    }
    setParams(nextParams, { replace: false })
  }

  function askNext(excludeId?: string, afterSkip = false) {
    if ((!afterSkip && transitionLock.current) || next.isPending || (skip.isPending && !afterSkip) || answer.isPending || voice.isPending) return
    transitionLock.current = true
    next.mutate({ qtype, excludeId }, {
      onSuccess: (q) => update({ domanda: q.id, valutazione: null }),
      onSettled: () => { transitionLock.current = false },
    })
  }

  function doSkip() {
    if (!questionId || transitionLock.current || skip.isPending || next.isPending || answer.isPending || voice.isPending) return
    transitionLock.current = true
    skip.mutate(questionId, {
      onSuccess: () => askNext(questionId, true),
      onError: () => { transitionLock.current = false },
    })
  }

  function endSession() {
    end.mutate(undefined, { onSuccess: () => update({ domanda: null, valutazione: null }) })
  }

  const noQuestions = next.error instanceof ApiError && next.error.code === 'no_questions'
  const busy = answer.isPending || voice.isPending
  const writeError = answer.error ?? voice.error ?? skip.error
  const hint = RECALL_TYPES.find((t) => t.value === qtype)!
  const placeHelp = !bot.data ? null : !bot.data.configured ? (
    <>
      Per il recall su Telegram configura il bot in{' '}
      <Link to="/impostazioni" className="underline underline-offset-2">
        Impostazioni
      </Link>
      .
    </>
  ) : !bot.data.running ? (
    <>
      Il bot Telegram è fermo: avvialo dalla pagina{' '}
      <Link to="/bot" className="underline underline-offset-2">
        Bot Telegram
      </Link>
      .
    </>
  ) : null

  return (
    <Card className="flex flex-col gap-4 p-5" aria-labelledby="session-title">
      <h2 id="session-title" className="text-base font-bold">
        Sessione
      </h2>

      {others.map((s) => (
        <TelegramSessionRow key={s.id} session={s} current={false} />
      ))}

      <div className="grid gap-4 sm:grid-cols-2">
        {telegramOn && <div className="flex flex-col gap-1">
          <SlideToggle
            label="Dove fare il recall"
            options={PLACES}
            value={effectivePlace}
            onChange={(v) => update({ luogo: v })}
            disabled={placeLocked}
            description={effectivePlace === 'telegram' ? 'Recall su Telegram' : 'Recall qui'}
            testId="place-toggle"
          />
          {placeLocked && placeHelp && <p className="text-xs text-warning">{placeHelp}</p>}
        </div>}
        <SlideToggle
          label="Tipo di domanda"
          options={TYPE_OPTIONS}
          value={qtype}
          onChange={(v) => update({ tipo: v })}
          description={
            <>
              <strong className="font-semibold text-foreground">{hint.label}</strong>: {hint.hint}
            </>
          }
          testId="type-toggle"
        />
      </div>

      {effectivePlace === 'telegram' ? (
        <div className="flex flex-col gap-3" data-testid="telegram-panel">
          {telegram ? (
            <TelegramSessionRow session={telegram} current />
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Il bot apre la sessione nel topic della materia: rispondi dal telefono.
              </p>
              <Button
                className="self-start"
                onClick={() => startTelegram.mutate(qtype)}
                disabled={!botReady || !!web || commandPending || startTelegram.isPending}
              >
                <Send aria-hidden="true" /> Avvia su Telegram
              </Button>
              {web && <Alert tone="warning">C'è una sessione in corso qui: terminala prima di passare a Telegram.</Alert>}
              {commandPending && <Alert>Richiesta inviata al bot…</Alert>}
              {command?.kind === 'start_recall' && command.state === 'failed' && (
                <Alert tone="danger">Il bot non ha avviato la sessione: {command.error}</Alert>
              )}
              {startTelegram.isError && <Alert tone="danger">{errorMessage(startTelegram.error)}</Alert>}
            </>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-4" data-testid="web-panel">
          {telegram && (
            <>
              <Alert tone="warning">C'è una sessione in corso su Telegram per questa lezione: interrompila per continuare qui.</Alert>
              <TelegramSessionRow session={telegram} current />
            </>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => askNext()} disabled={next.isPending || skip.isPending || busy || !!telegram}>
              Prossima domanda
            </Button>
            {web && (
              <Button size="sm" variant="outline" onClick={endSession} disabled={end.isPending}>
                <Square aria-hidden="true" /> Termina sessione
              </Button>
            )}
            {web && (
              <span className="text-xs text-muted-foreground" data-testid="web-session" data-session-id={web.id}>
                Sessione in corso dalle {startedAt(web.started_at)} · domande poste: {web.questions}
              </span>
            )}
          </div>
          {end.isError && <Alert tone="danger">{errorMessage(end.error)}</Alert>}
          {!web && session.data?.last && <SessionSummary session={session.data.last} />}

          {noQuestions && <Alert tone="warning">Nessuna domanda di questo tipo da porre: rigenera il pool o generane altre.</Alert>}
          {next.isError && !noQuestions && <Alert tone="danger">{errorMessage(next.error)}</Alert>}
          {history.isError && <Alert tone="danger">{errorMessage(history.error)}</Alert>}
          {!questionId && !noQuestions && !session.data?.last && (
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
                <Button variant="ghost" size="sm" className="self-start" onClick={doSkip} disabled={skip.isPending || next.isPending || busy}>
                  <SkipForward /> Salta
                </Button>
              )}
            </article>
          )}
        </div>
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
          <Pool lessonId={id} />
          <Session lessonId={id} />
          <History lessonId={id} />
        </>
      ) : (
        <Alert tone="warning">La lezione non ha ancora una rielaborazione valida: il recall parte dal draft.</Alert>
      )}
    </section>
  )
}
