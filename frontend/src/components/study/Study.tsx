import { BookOpen, Check, Mic, Pause, Play, SendHorizontal, Square, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import {
  recallKeys, useAnswer, useAnswerVoice, useGenerateForUnits, useNextQuestion, useSkip, useStudyLesson,
  type RecallQuestion, type StudyUnit,
} from '@/api/recall'
import { useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '@/components/shell/PageHeader'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { lessonTitle, type Lesson } from '@/lib/format'
import { withImageUrls } from '@/lib/images'
import { renderDelimitedMath } from '@/lib/math'
import { recordingFormat } from '@/lib/recording'
import { useIsPhone } from '@/lib/phone'
import { cn } from '@/lib/utils'

/**
 * Studio (schermate 05, 05b, 06): si legge un'unità intera, poi le sue domande una alla volta,
 * poi l'unità dopo; con un gruppo (giorno, materia, docente) le lezioni una dopo l'altra.
 * Domande su questa parte (menu della lezione) parte dalle domande di alcune unità.
 * Le domande sono quelle del pool (POST /recall/next con unit_id, come Leggi e ripeti).
 */
export function StudyFlow({ lessons, onlyUnits = null, back }: {
  /** Lezioni nell'ordine dello studio (pronte: rielaborazione valida). */
  lessons: Lesson[]
  /** Solo queste unità, partendo dalle domande (Domande su questa parte). */
  onlyUnits?: string[] | null
  back: { to: string; label: string }
}) {
  const [lessonIndex, setLessonIndex] = useState(0)
  const [unitIndex, setUnitIndex] = useState(0)
  const [phase, setPhase] = useState<'lettura' | 'domande'>(onlyUnits ? 'domande' : 'lettura')
  const [rereading, setRereading] = useState(false)
  const [finished, setFinished] = useState(false)
  const lesson = lessons[lessonIndex] ?? null
  const study = useStudyLesson(lesson?.id ?? null)
  // Le unità della lezione nell'ordine: con onlyUnits quelle della parte.
  const [units, setUnits] = useState<StudyUnit[] | null>(null)
  const loaded = study.data && study.data.id === lesson?.id ? study.data : null
  useEffect(() => {
    // La lista si fissa all'ingresso nella lezione: dopo ogni risposta il conteggio cambia, l'ordine no.
    // oxlint-disable-next-line react/set-state-in-effect
    if (loaded && units === null) setUnits(onlyUnits ? loaded.units.filter((u) => onlyUnits.includes(u.id)) : loaded.units)
  }, [loaded, units, onlyUnits])
  const unit = units?.[unitIndex] ?? null
  const live = loaded?.units.find((u) => u.id === unit?.id) ?? unit

  const advance = useCallback(() => {
    setRereading(false)
    if (units && unitIndex + 1 < units.length) {
      setUnitIndex(unitIndex + 1)
      setPhase(onlyUnits ? 'domande' : 'lettura')
    } else if (lessonIndex + 1 < lessons.length) {
      setLessonIndex(lessonIndex + 1)
      setUnitIndex(0)
      setUnits(null)
      setPhase('lettura')
    } else setFinished(true)
    window.scrollTo?.({ top: 0 })
  }, [units, unitIndex, lessonIndex, lessons.length, onlyUnits])

  if (lessons.length === 0) {
    return (
      <StudyShell title="Studio" back={back}>
        <p className="text-body text-muted-foreground" data-testid="study-empty">Nessuna lezione pronta per lo Studio: serve la rielaborazione.</p>
      </StudyShell>
    )
  }
  const title = lesson ? lessonTitle(lesson) : 'Studio'
  if (finished) {
    return (
      <StudyShell title={title} back={back}>
        <div className="flex flex-col items-start gap-4" data-testid="study-done">
          <p className="text-body">{onlyUnits ? 'Hai finito le domande su questa parte.' : lessons.length > 1 ? 'Hai finito lo Studio di queste lezioni.' : 'Hai finito lo Studio della lezione.'}</p>
          <Link to={back.to} className="font-semibold text-link underline-offset-2 hover:underline">{back.label === 'Esci' ? 'Torna indietro' : back.label}</Link>
        </div>
      </StudyShell>
    )
  }
  if (study.isError) {
    return (
      <StudyShell title={title} back={back}>
        <p role="alert" className="flex items-center gap-3 text-body"><span className="text-danger">{errorMessage(study.error)}</span>
          <Button variant="outline" size="sm" onClick={() => void study.refetch()}>Riprova</Button></p>
      </StudyShell>
    )
  }
  if (!units || !loaded) {
    return (
      <StudyShell title={title} back={back}>
        <ReadingSkeleton />
      </StudyShell>
    )
  }
  const none = onlyUnits && units.every((u) => u.questions === 0)
  if (units.length === 0 || !unit || !live || none) {
    return (
      <StudyShell title={title} back={back}>
        {onlyUnits ? <NoQuestionsYet lessonId={lesson!.id} units={units.length ? units.map((u) => u.id) : onlyUnits} onReady={() => setUnits(null)} /> : (
          <div className="flex flex-col items-start gap-4">
            <p className="text-body text-muted-foreground">Questa lezione non ha unità da studiare.</p>
            {lessonIndex + 1 < lessons.length && <Button onClick={advance}>Lezione successiva</Button>}
          </div>
        )}
      </StudyShell>
    )
  }
  const position = `${title} · unità ${unitIndex + 1} di ${units.length}`
  const audio = loaded.has_audio && live.start != null ? { lessonId: lesson!.id, start: live.start, end: live.end ?? null } : null
  const reading = phase === 'lettura' || rereading
  return (
    <>
      {reading && (
        <StudyShell
          title={position}
          back={back}
          actions={<UnitAudio key={`${lesson!.id}-${unit.id}`} clip={audio} />}
          footer={
            rereading ? (
              <Button className="w-full max-w-(--reading-width) justify-center" onClick={() => setRereading(false)}>Torna alle domande</Button>
            ) : live.questions > 0 ? (
              <Button className="w-full max-w-(--reading-width) justify-center" onClick={() => setPhase('domande')} data-testid="study-quiz">
                Mettimi alla prova · {live.questions === 1 ? '1 domanda' : `${live.questions} domande`}
              </Button>
            ) : (
              <Button className="w-full max-w-(--reading-width) justify-center" onClick={advance} data-testid="study-next">
                {unitIndex + 1 < units.length ? 'Nessuna domanda · unità successiva' : lessonIndex + 1 < lessons.length ? 'Nessuna domanda · lezione successiva' : 'Nessuna domanda · fine'}
              </Button>
            )
          }
        >
          <Dots count={units.length} current={unitIndex} />
          <UnitText lessonId={lesson!.id} unit={live} />
        </StudyShell>
      )}
      {phase === 'domande' && (
        <div hidden={rereading}>
          <QuestionPhase
            key={`${lesson!.id}-${unit.id}`}
            lessonId={lesson!.id}
            unit={live}
            total={unit.questions || live.questions}
            back={back}
            dots={<Dots count={units.length} current={unitIndex} />}
            onReread={() => setRereading(true)}
            onDone={advance}
          />
        </div>
      )}
    </>
  )
}

/** Intestazione (Esci, dove sei, azione a destra), colonna di lettura e pulsante in basso. */
function StudyShell({ title, back, actions, footer, children }: { title: string; back: { to: string; label: string }; actions?: ReactNode; footer?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-[calc(100dvh-64px)] flex-1 flex-col md:min-h-dvh" data-testid="study">
      <PageHeader title={title} muted titleAs="h1" back={back} actions={actions} className="max-md:min-h-14 max-md:flex-nowrap [&_h1]:max-md:text-meta" />
      <div className="flex-1 px-7 max-md:px-[18px]">
        <div className="mx-auto w-full max-w-(--reading-width) pb-8 pt-3">{children}</div>
      </div>
      {footer && (
        <div className="sticky bottom-0 z-10 flex justify-center border-t bg-background p-4 max-md:bottom-[calc(64px+env(safe-area-inset-bottom))] max-md:border-t-0 max-md:px-[18px] max-md:pt-0 [&_button]:min-h-12">
          {footer}
        </div>
      )}
    </div>
  )
}

function Dots({ count, current }: { count: number; current: number }) {
  return (
    <div className="mb-6 mt-1 flex gap-1" aria-hidden data-testid="study-dots">
      {Array.from({ length: count }, (_, i) => (
        <i key={i} className={cn('h-[3px] flex-1 rounded-md', i <= current ? 'bg-foreground' : 'bg-muted')} data-done={i <= current || undefined} />
      ))}
    </div>
  )
}

function ReadingSkeleton() {
  return (
    <div aria-busy="true" aria-label="Carico l'unità" role="status">
      {[['40%', 18], ['100%', 10], ['92%', 10], ['75%', 10], ['100%', 10], ['60%', 10]].map(([width, height], i) => (
        <div key={i} className="my-3 rounded-md bg-muted" style={{ width: String(width), height: Number(height) }} />
      ))}
    </div>
  )
}

/** Testo dell'unità: HTML sanificato dall'API, immagini della lezione e formule. */
function UnitText({ lessonId, unit }: { lessonId: number; unit: StudyUnit }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) void renderDelimitedMath(ref.current)
  }, [unit.html])
  return (
    <section aria-labelledby="study-unit-title">
      <h2 id="study-unit-title" className="mb-3.5 text-heading font-semibold leading-snug">{unit.id} {unit.title}</h2>
      <div ref={ref} className="rt-document rt-reading" data-testid="study-text" dangerouslySetInnerHTML={{ __html: withImageUrls(unit.html, lessonId) }} />
    </section>
  )
}

/**
 * Audio della lezione per questa unità (dai timecode, non TTS): parte dall'inizio dell'unità e
 * si ferma alla fine. L'audio si scarica solo al primo ascolto.
 */
function UnitAudio({ clip }: { clip: { lessonId: number; start: number; end: number | null } | null }) {
  const ref = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState(false)
  if (!clip) return <IconButton label="Audio della lezione per questa unità" icon={Play} unavailable="audio non disponibile" />
  const toggle = () => {
    const audio = ref.current
    if (!audio) return
    if (!audio.paused) {
      audio.pause()
      return
    }
    const start = () => {
      if (audio.currentTime < clip.start || (clip.end != null && audio.currentTime >= clip.end - 0.25)) audio.currentTime = clip.start
      audio.play().catch(() => setError(true))
    }
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) start()
    else {
      audio.addEventListener('loadedmetadata', start, { once: true })
      audio.load()
    }
  }
  return (
    <>
      <audio
        ref={ref}
        src={`/api/v1/lessons/${clip.lessonId}/audio`}
        preload="none"
        data-testid="study-audio"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => setError(true)}
        onTimeUpdate={(e) => {
          if (clip.end != null && e.currentTarget.currentTime >= clip.end) e.currentTarget.pause()
        }}
      />
      <IconButton
        label={playing ? "Ferma l'audio dell'unità" : 'Audio della lezione per questa unità'}
        icon={playing ? Pause : Play}
        aria-pressed={playing}
        unavailable={error ? 'il browser non riesce a riprodurre questo audio' : null}
        onClick={toggle}
      />
    </>
  )
}

/** Domande su una parte che non ne ha ancora: si generano solo su quelle unità (quiz e mirate). */
function NoQuestionsYet({ lessonId, units, onReady }: { lessonId: number; units: string[]; onReady: () => void }) {
  const generate = useGenerateForUnits(lessonId)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const client = useQueryClient()
  const done = jobFinished(job.data)
  useEffect(() => {
    if (!done) return
    void client.invalidateQueries({ queryKey: recallKeys.all(lessonId) }).then(onReady)
  }, [done, client, lessonId, onReady])
  return (
    <div className="flex flex-col items-start gap-4" data-testid="study-no-questions">
      <p className="text-body">Nessuna domanda su {units.length === 1 ? 'questa unità' : 'queste unità'} ({units.join(', ')}).</p>
      {jobId && !done ? (
        <p role="status" className="text-meta text-muted-foreground">Genero le domande…</p>
      ) : (
        <Button onClick={() => generate.mutate(units, { onSuccess: (accepted) => setJobId(accepted.job_id) })} disabled={generate.isPending}>
          Genera le domande
        </Button>
      )}
      {job.data?.state === 'failed' && <Alert tone="danger">{job.data.error ?? 'Generazione non riuscita.'}</Alert>}
      {generate.isError && <Alert tone="danger">{errorMessage(generate.error)}</Alert>}
    </div>
  )
}

type QuizResult = Schemas['QuizResult']

type Outcome =
  | { kind: 'quiz'; question: RecallQuestion; choice: number; correct: boolean }
  | { kind: 'open'; jobId: string; answer: string | null }

const OPEN_LABEL: Record<string, string> = { mirata: 'Domanda mirata', vasta: 'Domanda vasta', caso: 'Caso clinico', esercizio: 'Esercizio' }

/** Le domande dell'unità, una alla volta (schermata 06). */
function QuestionPhase({ lessonId, unit, total, back, dots, onReread, onDone }: {
  lessonId: number
  unit: StudyUnit
  total: number
  back: { to: string; label: string }
  dots: ReactNode
  onReread: () => void
  onDone: () => void
}) {
  const next = useNextQuestion(lessonId)
  const answer = useAnswer(lessonId)
  const voice = useAnswerVoice(lessonId)
  const skip = useSkip(lessonId)
  const [question, setQuestion] = useState<RecallQuestion | null>(null)
  const [asked, setAsked] = useState(0)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const requested = useRef(false)

  const ask = useCallback((excludeId?: string) => {
    setOutcome(null)
    next.mutate({ qtype: 'mista', unitId: unit.id, excludeId }, {
      onSuccess: (q) => {
        setQuestion(q)
        setAsked((n) => n + 1)
      },
      onError: (error) => {
        if (error instanceof ApiError && error.code === 'no_questions') onDone()
      },
    })
  }, [next, unit.id, onDone])

  useEffect(() => {
    if (requested.current) return
    requested.current = true
    ask()
  }, [ask])

  const proceed = () => {
    if (asked >= total) onDone()
    else ask()
  }
  const busy = answer.isPending || voice.isPending || next.isPending || skip.isPending
  const count = Math.max(total, asked)
  const label = `${unit.title} · domanda ${Math.max(asked, 1)} di ${count}`
  const failure = next.error && !(next.error instanceof ApiError && next.error.code === 'no_questions') ? next.error : (answer.error ?? voice.error ?? skip.error)
  return (
    <div className="flex min-h-[calc(100dvh-64px)] flex-1 flex-col md:min-h-dvh" data-testid="study-questions">
      <PageHeader title={label} muted titleAs="h1" back={back} actions={<IconButton label="Rileggi l'unità" icon={BookOpen} onClick={onReread} />}
        className="max-md:min-h-14 max-md:flex-nowrap [&_h1]:max-md:text-meta" />
      <div className="flex-1 px-7 pb-8 pt-3 max-md:px-[18px]">
        <div className="mx-auto w-full max-w-[560px]">
          {dots}
          {failure && <Alert tone="danger" className="mb-4">{errorMessage(failure)}</Alert>}
          {!question ? (
            <div className="h-48 rounded-lg bg-muted" aria-busy="true" aria-label="Carico la domanda" role="status" />
          ) : (
            <article className="rounded-lg bg-muted p-4" data-testid="study-question" data-type={question.type} data-question-id={question.id}>
              {question.type !== 'quiz' && <p className="mb-1 text-meta text-muted-foreground">{OPEN_LABEL[question.type] ?? 'Domanda aperta'}</p>}
              <h2 className="mb-0.5 text-[15px] font-semibold leading-relaxed">{question.question_text}</h2>
              {question.type === 'quiz' ? (
                <QuizAnswers
                  question={outcome?.kind === 'quiz' ? outcome.question : question}
                  outcome={outcome?.kind === 'quiz' ? outcome : null}
                  disabled={busy || !!outcome}
                  onAnswer={(choice) => answer.mutate({ questionId: question.id, choice }, {
                    onSuccess: (r) => {
                      const quiz = r.quiz as QuizResult | undefined
                      if (quiz) setOutcome({ kind: 'quiz', question: quiz.question, choice, correct: quiz.correct })
                    },
                  })}
                />
              ) : outcome?.kind === 'open' ? (
                <Evaluation jobId={outcome.jobId} />
              ) : (
                <OpenAnswer
                  disabled={busy}
                  onWritten={(text) => answer.mutate({ questionId: question.id, answer: text }, { onSuccess: (r) => r.job && setOutcome({ kind: 'open', jobId: r.job.job_id, answer: text }) })}
                  onVoice={(audio) => voice.mutate({ questionId: question.id, audio }, { onSuccess: (job) => setOutcome({ kind: 'open', jobId: job.job_id, answer: null }) })}
                />
              )}
            </article>
          )}
          {question && (
            <div className="mt-4 flex items-center justify-end gap-2">
              {!outcome && (
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => skip.mutate(question.id, { onSuccess: () => (asked >= total ? onDone() : ask(question.id)) })}>
                  Salta
                </Button>
              )}
              {outcome && (
                <Button onClick={proceed} disabled={busy} data-testid="study-continue">
                  {asked >= total ? 'Avanti' : 'Prossima domanda'}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** Risposte del quiz come righe grandi; dopo la scelta, giusta e sbagliata e la spiegazione. */
function QuizAnswers({ question, outcome, disabled, onAnswer }: {
  question: RecallQuestion
  outcome: { choice: number; correct: boolean } | null
  disabled: boolean
  onAnswer: (choice: number) => void
}) {
  return (
    <>
      <div role="group" aria-label="Risposte">
        {question.options?.map((option, i) => {
          const right = outcome && question.correct_index === i
          const wrong = outcome && outcome.choice === i && !outcome.correct
          return (
            <button
              key={i}
              type="button"
              aria-pressed={outcome ? outcome.choice === i : false}
              disabled={disabled}
              onClick={() => onAnswer(i)}
              data-state={right ? 'correct' : wrong ? 'wrong' : undefined}
              className={cn(
                'mt-3 flex min-h-[52px] w-full items-start gap-2 rounded-md border bg-card p-3.5 text-left text-[15px] leading-normal text-foreground',
                'enabled:hover:border-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-default',
                right && 'border-success bg-success-soft text-success',
                wrong && 'border-danger bg-danger-soft text-danger',
              )}
            >
              <span className="flex-1">{option}</span>
              {right && <Check className="mt-0.5 size-[18px] shrink-0" aria-label="Risposta giusta" />}
              {wrong && <X className="mt-0.5 size-[18px] shrink-0" aria-label="Risposta sbagliata" />}
            </button>
          )
        })}
      </div>
      {outcome && (
        <div role="status" className="mt-4 text-body" data-testid="study-feedback">
          <p className="font-semibold">{outcome.correct ? 'Giusto.' : 'Sbagliato.'}</p>
          {question.explanation && <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{question.explanation}</p>}
        </div>
      )}
    </>
  )
}

/** Risposta aperta: scritta o a voce (il microfono c'è solo qui, non nel quiz). */
function OpenAnswer({ disabled, onWritten, onVoice }: { disabled: boolean; onWritten: (text: string) => void; onVoice: (audio: File) => void }) {
  const [text, setText] = useState('')
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const phone = useIsPhone()
  const supported = typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices?.getUserMedia
  useEffect(() => () => recorder.current?.stream.getTracks().forEach((t) => t.stop()), [])
  const start = async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const format = recordingFormat((t) => MediaRecorder.isTypeSupported(t))
      const rec = new MediaRecorder(stream, format.mimeType ? { mimeType: format.mimeType } : undefined)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        onVoice(new File(chunks, `risposta.${format.extension}`, { type: rec.mimeType || format.mimeType || 'audio/webm' }))
      }
      rec.start()
      recorder.current = rec
      setRecording(true)
    } catch (err) {
      setError(err instanceof Error && err.name === 'NotAllowedError' ? 'Il browser non ha il permesso di usare il microfono.' : 'Microfono non disponibile.')
    }
  }
  const stop = () => {
    recorder.current?.stop()
    recorder.current = null
    setRecording(false)
  }
  return (
    <form
      className="mt-3"
      onSubmit={(event) => {
        event.preventDefault()
        if (text.trim()) onWritten(text.trim())
      }}
    >
      <textarea
        aria-label="La tua risposta"
        placeholder="Scrivi la risposta, o rispondi a voce"
        rows={phone ? 4 : 5}
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="block w-full rounded-md border bg-card px-3 py-2.5 text-[15px] text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
      />
      <div className="mt-2 flex items-center gap-1">
        {recording ? (
          <IconButton label="Ferma e invia la risposta a voce" icon={Square} onClick={stop} className="text-danger" />
        ) : (
          <IconButton label="Rispondi a voce" icon={Mic} onClick={() => void start()} unavailable={!supported ? 'microfono non disponibile in questo browser' : disabled ? 'attendi' : null} />
        )}
        {recording && <span role="status" className="text-meta text-danger">Registrazione in corso…</span>}
        <span className="flex-1" />
        <IconButton label="Invia la risposta" icon={SendHorizontal} variant="solid" type="submit" unavailable={!text.trim() ? 'scrivi una risposta' : disabled ? 'attendi' : null} />
      </div>
      {error && <p role="alert" className="mt-2 text-meta text-danger">{error}</p>}
    </form>
  )
}

/** Valutazione della risposta aperta (job recall_evaluate), dal canale live. */
function Evaluation({ jobId }: { jobId: string }) {
  const job = useJobStatus(jobId)
  const result = job.data?.result as { evaluation?: string; answer?: string } | null | undefined
  if (!jobFinished(job.data)) return <p role="status" className="mt-3 text-meta text-muted-foreground" data-testid="study-evaluating">Valuto la risposta…</p>
  if (job.data?.state !== 'succeeded') return <Alert tone="danger" className="mt-3">{job.data?.error ?? 'Valutazione non riuscita.'}</Alert>
  return (
    <div role="status" className="mt-3 flex flex-col gap-2 text-body" data-testid="study-feedback">
      {result?.answer && <p className="whitespace-pre-wrap rounded-md bg-card px-3 py-2"><span className="text-meta text-muted-foreground">La tua risposta: </span>{result.answer}</p>}
      <p className="whitespace-pre-wrap">{result?.evaluation ?? 'Valutazione non disponibile.'}</p>
    </div>
  )
}
