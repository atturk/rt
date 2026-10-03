import {
  Brain,
  ChevronLeft,
  MessageSquare,
  Mic,
  SkipForward,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useLesson } from '@/api/hooks'
import {
  useAnswer,
  useAnswerVoice,
  useEndSession,
  useNextQuestion,
  useRecallHistory,
  useRecallOverview,
  useRegenerateQuestion,
  useSkip,
  useSubjectEnd,
  useSubjectNext,
  useSubjectRecall,
  useVote,
  type RecallQuestion,
  type RecallType,
} from '@/api/recall'
import { JobProgress } from '@/components/JobProgress'
import { VoiceRecorder } from '@/components/VoiceRecorder'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { IconButton } from '@/components/ui/icon-button'
import { lessonTitle } from '@/lib/format'
import { selectionSubject } from '@/lib/recallView'
import { cn } from '@/lib/utils'

type SessionType = RecallType | 'mista'

const SESSION_TYPES: { id: SessionType; label: string }[] = [
  { id: 'mista', label: 'Mista' },
  { id: 'quiz', label: 'Quiz' },
  { id: 'mirata', label: 'Mirata' },
  { id: 'vasta', label: 'Vasta' },
  { id: 'caso', label: 'Casi' },
  { id: 'esercizio', label: 'Esercizi' },
]

type DiscardReason = NonNullable<Schemas['RecallVote']['reasons']>[number]

const DISCARD_REASONS: { id: DiscardReason; label: string }[] = [
  { id: 'sbagliata', label: 'Sbagliata' },
  { id: 'ambigua', label: 'Ambigua' },
  { id: 'troppi_indizi', label: 'Troppi indizi' },
  { id: 'troppo_facile', label: 'Troppo facile' },
  { id: 'fuori_tema', label: 'Fuori tema' },
  { id: 'gia_vista', label: 'Già vista' },
]

const LAST_TYPE_KEY = 'rt-recall-last-type'

export function LightweightSession({
  lessonId: propLessonId,
  selectionIds: propSelectionIds,
}: {
  lessonId?: number
  selectionIds?: number[]
}) {
  const params = useParams()
  const navigate = useNavigate()

  const lessonId = propLessonId ?? (params.lessonId ? Number(params.lessonId) : undefined)
  const isSelection = Boolean(propSelectionIds?.length || params.ids)
  const selectionIds = useMemo(() => {
    if (propSelectionIds?.length) return propSelectionIds
    if (params.ids) return params.ids.split(',').map(Number).filter(Boolean)
    return []
  }, [propSelectionIds, params.ids])

  const subjectKey = isSelection ? selectionSubject(selectionIds.join(',')) : ''

  // Dati lezione o selezione
  const lessonQuery = useLesson(lessonId ?? 0)
  const overviewQuery = useRecallOverview(lessonId ?? 0)
  const subjectRecallQuery = useSubjectRecall(subjectKey)

  // Lezione della domanda corrente: nella selezione arriva insieme alla domanda
  const [questionLessonId, setQuestionLessonId] = useState<number | null>(null)
  const activeLessonId = questionLessonId ?? lessonId ?? 0
  // Valutazione delle risposte aperte: job in corso, poi esito letto dallo storico
  const [evaluationJob, setEvaluationJob] = useState<string | null>(null)
  const history = useRecallHistory(activeLessonId, false)

  // Hooks mutazioni
  const nextLesson = useNextQuestion(lessonId ?? 0)
  const nextSubject = useSubjectNext(subjectKey)
  const answerMutation = useAnswer(activeLessonId)
  const voiceMutation = useAnswerVoice(activeLessonId)
  const voteMutation = useVote(activeLessonId)
  const regenerateMutation = useRegenerateQuestion(activeLessonId)
  const skipMutation = useSkip(activeLessonId)
  const endLessonSession = useEndSession(lessonId ?? 0)
  const endSubjectSession = useSubjectEnd(subjectKey)

  // Tipo di recall (persiste l'ultimo usato)
  const [qtype, setQtype] = useState<SessionType>(() => {
    try {
      const saved = localStorage.getItem(LAST_TYPE_KEY)
      if (saved && SESSION_TYPES.some((t) => t.id === saved)) {
        return saved as SessionType
      }
    } catch {
      // Ignora errori di accesso a localStorage
    }
    return 'quiz'
  })

  // Stato domanda corrente e risposta
  const [currentQuestion, setCurrentQuestion] = useState<RecallQuestion | null>(null)
  const [questionCount, setQuestionCount] = useState<number>(0)
  const [selectedChoice, setSelectedChoice] = useState<number | null>(null)
  const [writtenAnswer, setWrittenAnswer] = useState<string>('')
  const [showVoiceRecorder, setShowVoiceRecorder] = useState<boolean>(false)
  const [emptyPoolError, setEmptyPoolError] = useState<boolean>(false)
  const [generalError, setGeneralError] = useState<string | null>(null)

  // Esito dopo risposta
  const [evaluatedResult, setEvaluatedResult] = useState<{
    correct?: boolean
    outcome?: 'corretta' | 'parziale' | 'sbagliata'
    explanation?: string
    correctIndex?: number
  } | null>(null)

  // Voto
  const [currentVote, setCurrentVote] = useState<'up' | 'down' | null>(null)

  // Modali feedback
  const [discardModalOpen, setDiscardModalOpen] = useState<boolean>(false)
  const [selectedReasons, setSelectedReasons] = useState<Set<DiscardReason>>(() => new Set())
  const [commentModalOpen, setCommentModalOpen] = useState<boolean>(false)
  const [commentText, setCommentText] = useState<string>('')

  // Richiesta prossima domanda: vale solo la risposta dell'ultima richiesta (es. tipo cambiato al volo)
  const requestSeq = useRef(0)
  const askNext = useCallback(
    async (typeToAsk: SessionType = qtype, excludeId?: string) => {
      const seq = ++requestSeq.current
      setEmptyPoolError(false)
      setGeneralError(null)
      setSelectedChoice(null)
      setWrittenAnswer('')
      setShowVoiceRecorder(false)
      setEvaluatedResult(null)
      setEvaluationJob(null)
      setCurrentVote(null)
      setDiscardModalOpen(false)
      setSelectedReasons(new Set())
      setCommentModalOpen(false)
      setCommentText('')

      try {
        let q: RecallQuestion
        if (isSelection) {
          const res = await nextSubject.mutateAsync({ qtype: typeToAsk, exclude: excludeId })
          if (seq !== requestSeq.current) return
          q = res.question
          setQuestionLessonId(res.lesson_id)
        } else if (lessonId) {
          q = await nextLesson.mutateAsync({ qtype: typeToAsk, excludeId })
          if (seq !== requestSeq.current) return
          setQuestionLessonId(lessonId)
        } else {
          return
        }
        setCurrentQuestion(q)
        setQuestionCount((c) => c + 1)
      } catch (err: unknown) {
        if (seq !== requestSeq.current) return
        if (err instanceof ApiError && err.code === 'no_questions') {
          setEmptyPoolError(true)
          setCurrentQuestion(null)
        } else {
          setGeneralError(errorMessage(err))
        }
      }
    },
    [isSelection, lessonId, nextLesson, nextSubject, qtype],
  )

  // Caricamento iniziale
  useEffect(() => {
    let active = true
    if (!currentQuestion && !emptyPoolError && (lessonId || isSelection)) {
      Promise.resolve().then(() => {
        if (active) void askNext(qtype)
      })
    }
    return () => {
      active = false
    }
  }, [lessonId, isSelection]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cambio tipo
  const handleTypeChange = (nextType: SessionType) => {
    setQtype(nextType)
    try {
      localStorage.setItem(LAST_TYPE_KEY, nextType)
    } catch {
      // Ignora errori localStorage
    }
    void askNext(nextType)
  }

  // Risposta a quiz
  const handleQuizAnswer = async () => {
    if (selectedChoice === null || !currentQuestion || !activeLessonId) return
    try {
      await answerMutation.mutateAsync({
        questionId: currentQuestion.id,
        choice: selectedChoice,
      })
      const isCorrect = currentQuestion.correct_index === selectedChoice
      setEvaluatedResult({
        correct: isCorrect,
        outcome: isCorrect ? 'corretta' : 'sbagliata',
        explanation: currentQuestion.explanation ?? undefined,
        correctIndex: currentQuestion.correct_index ?? undefined,
      })
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  // Risposta aperta scritta
  const handleWrittenAnswer = async () => {
    if (!writtenAnswer.trim() || !currentQuestion || !activeLessonId) return
    try {
      const result = await answerMutation.mutateAsync({
        questionId: currentQuestion.id,
        answer: writtenAnswer.trim(),
      })
      if (result.job) setEvaluationJob(result.job.job_id)
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  // Risposta vocale
  const handleVoiceAnswer = async (audio: File) => {
    if (!currentQuestion || !activeLessonId) return
    try {
      const job = await voiceMutation.mutateAsync({
        questionId: currentQuestion.id,
        audio,
      })
      setEvaluationJob(job.job_id)
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  // Fine della valutazione: esito e commento del modello dalla risposta salvata
  const evaluationFinished = async () => {
    const questionId = currentQuestion?.id
    const { data } = await history.refetch()
    const saved = data?.answers.filter((a) => a.question_id === questionId).pop()
    setEvaluationJob(null)
    setEvaluatedResult({
      outcome: saved?.outcome ?? undefined,
      explanation: saved?.evaluation ?? currentQuestion?.explanation ?? undefined,
    })
  }

  // Non lo so
  const handleDontKnow = async () => {
    if (!currentQuestion || !activeLessonId) return
    try {
      await answerMutation.mutateAsync({
        questionId: currentQuestion.id,
        dontKnow: true,
      })
      setEvaluatedResult({
        correct: false,
        outcome: 'sbagliata',
        explanation: currentQuestion.explanation ?? undefined,
        correctIndex: currentQuestion.correct_index ?? undefined,
      })
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  // Salta domanda
  const handleSkip = async () => {
    if (!currentQuestion || !activeLessonId) return
    try {
      await skipMutation.mutateAsync(currentQuestion.id)
      // la saltata torna in coda: non deve essere subito la prossima
      void askNext(qtype, currentQuestion.id)
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  // Voto
  const handleVote = (voteType: 'up' | 'down') => {
    if (!currentQuestion || !activeLessonId) return
    if (voteType === 'up') {
      voteMutation.mutate({ questionId: currentQuestion.id, vote: 'up' })
      setCurrentVote('up')
    } else {
      setCurrentVote('down')
      setDiscardModalOpen(true)
    }
  }

  // Conferma scarto con motivi
  const handleConfirmDiscard = () => {
    if (!currentQuestion || !activeLessonId) return
    const reasons = Array.from(selectedReasons)
    voteMutation.mutate({
      questionId: currentQuestion.id,
      vote: 'down',
      reasons,
    })
    setDiscardModalOpen(false)
    void askNext()
  }

  // Commenta e rigenera
  const handleCommentRegenerate = async () => {
    if (!currentQuestion || !activeLessonId || !commentText.trim()) return
    try {
      await regenerateMutation.mutateAsync({
        questionId: currentQuestion.id,
        comment: commentText.trim(),
      })
      setCommentModalOpen(false)
      void askNext()
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  // Termina sessione
  const handleEnd = async () => {
    if (isSelection) {
      await endSubjectSession.mutateAsync()
      navigate('/')
    } else if (lessonId) {
      await endLessonSession.mutateAsync()
      navigate(`/lezioni/${lessonId}`)
    }
  }

  // Titolo della lezione / selezione
  const title = useMemo(() => {
    if (isSelection) {
      return `Selezione (${selectionIds.length} lezioni)`
    }
    if (lessonQuery.data) {
      return lessonTitle(lessonQuery.data)
    }
    return 'Lezione'
  }, [isSelection, selectionIds.length, lessonQuery.data])

  const backUrl = isSelection ? '/' : `/lezioni/${lessonId ?? ''}`

  // Calcolo domande da porre
  const daPorreCount = useMemo(() => {
    if (isSelection) {
      const stats = subjectRecallQuery.data?.lessons ?? []
      return stats.reduce((acc, l) => {
        const byType = (l.questions ?? {}) as Record<string, Record<string, number>>
        let lessonPending = 0
        for (const s of Object.values(byType)) {
          lessonPending += s?.pending ?? 0
        }
        return acc + lessonPending
      }, 0)
    }
    const counts = overviewQuery.data?.questions ?? {}
    let total = 0
    for (const qtypeObj of Object.values(counts)) {
      total += (qtypeObj as Record<string, number>)?.pending ?? 0
    }
    return total
  }, [isSelection, subjectRecallQuery.data, overviewQuery.data])

  const isQuiz = currentQuestion?.type === 'quiz'
  const isAnswered = evaluatedResult !== null || evaluationJob !== null
  const busy =
    answerMutation.isPending ||
    voiceMutation.isPending ||
    voteMutation.isPending ||
    regenerateMutation.isPending ||
    nextLesson.isPending ||
    nextSubject.isPending

  const optionLetters = ['A', 'B', 'C', 'D']

  return (
    <div className="flex min-h-screen flex-col bg-background" data-testid="recall-session-page">
      {/* Header sessione */}
      <header className="flex h-14 items-center gap-3 border-b px-4">
        <Link to={backUrl} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ChevronLeft aria-hidden /> Esci
        </Link>
        <h1 className="flex-1 truncate text-meta font-normal text-muted-foreground">
          Recall · <strong className="font-semibold text-foreground">{title}</strong>
        </h1>
        <span className="text-meta text-muted-foreground">{daPorreCount} da porre</span>
      </header>

      {/* Main content */}
      <main className="flex flex-1 justify-center px-4 py-8">
        <div className="flex w-full max-w-(--reading-width) flex-col gap-5">
          {/* Selettore tipi (chips) */}
          <div
            role="group"
            aria-label="Tipo di domanda"
            className="flex flex-wrap gap-1.5"
          >
            {SESSION_TYPES.map(({ id: typeId, label }) => {
              const active = qtype === typeId
              return (
                <button
                  key={typeId}
                  type="button"
                  aria-pressed={active}
                  onClick={() => handleTypeChange(typeId)}
                  className={cn(
                    'inline-flex h-7 items-center rounded-full px-3 text-xs font-medium transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground font-semibold'
                      : 'bg-muted text-foreground hover:bg-muted/80',
                  )}
                >
                  {label}
                </button>
              )
            })}
          </div>

          {generalError && <Alert tone="danger">{generalError}</Alert>}

          {emptyPoolError && (
            <div className="rounded-lg border bg-card p-6 text-center">
              <Brain className="mx-auto mb-3 size-8 text-muted-foreground" aria-hidden />
              <p className="text-body font-semibold">Nessuna domanda disponibile</p>
              <p className="mt-1 text-meta text-muted-foreground">
                Non ci sono domande da porre per il tipo selezionato. Scegli un altro tipo o rigenera il pool nel pannello Domande.
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => handleTypeChange('mista')}
              >
                Prova mista
              </Button>
            </div>
          )}

          {/* Domanda corrente */}
          {currentQuestion && (
            <div className="flex flex-col gap-4" data-testid="recall-question" data-question-id={currentQuestion.id} data-type={currentQuestion.type}>
              <div className="flex flex-col gap-1">
                <p className="text-meta text-muted-foreground">
                  {currentQuestion.type.toUpperCase()} · unità {currentQuestion.unit_ids.join(', ')} · domanda {questionCount}
                </p>
                <h2 className="text-heading font-semibold leading-relaxed">
                  {currentQuestion.question_text}
                </h2>
              </div>

              {/* Area risposte Quiz */}
              {isQuiz && currentQuestion.options && (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-col gap-2">
                    {currentQuestion.options.map((option, idx) => {
                      const letter = optionLetters[idx] || String(idx + 1)
                      const isSelected = selectedChoice === idx
                      const isCorrect = evaluatedResult?.correctIndex === idx
                      const isWrongSelection = isAnswered && isSelected && !isCorrect

                      let buttonStyle = 'border-border bg-card hover:bg-muted/50 text-foreground'
                      if (isAnswered) {
                        if (isCorrect) {
                          buttonStyle = 'border-primary bg-primary/10 text-primary font-semibold'
                        } else if (isWrongSelection) {
                          buttonStyle = 'border-danger bg-danger/10 text-danger font-medium'
                        }
                      } else if (isSelected) {
                        buttonStyle = 'border-primary bg-primary/10 text-primary font-medium'
                      }

                      return (
                        <button
                          key={idx}
                          type="button"
                          disabled={isAnswered || busy}
                          onClick={() => setSelectedChoice(idx)}
                          className={cn(
                            'flex min-h-12 w-full items-center justify-start rounded-lg border px-3.5 py-2.5 text-left text-body transition-colors',
                            buttonStyle,
                          )}
                        >
                          <span className="mr-2 font-semibold opacity-75">{letter}.</span>
                          <span>{option}</span>
                        </button>
                      )
                    })}
                  </div>

                  {!isAnswered && (
                    <div className="mt-1 flex items-center justify-between gap-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={handleDontKnow}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        Non lo so
                      </Button>
                      <Button
                        variant="default"
                        disabled={selectedChoice === null || busy}
                        onClick={handleQuizAnswer}
                      >
                        Rispondi
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {/* Area risposte Aperte (Mirata, Vasta, Caso, Esercizio) */}
              {!isQuiz && (
                <div className="flex flex-col gap-3">
                  {!isAnswered && (
                    <>
                      {!showVoiceRecorder ? (
                        <div className="flex flex-col gap-2">
                          <textarea
                            value={writtenAnswer}
                            onChange={(e) => setWrittenAnswer(e.target.value)}
                            placeholder="Scrivi qui la tua risposta…"
                            rows={4}
                            aria-label="Risposta scritta"
                            disabled={busy}
                            className="block w-full resize-y rounded-md border bg-card p-3 text-body placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
                          />
                          <div className="flex items-center justify-between gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              onClick={() => setShowVoiceRecorder(true)}
                              className="text-muted-foreground hover:text-foreground"
                            >
                              <Mic className="mr-1.5 size-4" aria-hidden />
                              Rispondi a voce
                            </Button>
                            <div className="flex items-center gap-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={busy}
                                onClick={handleDontKnow}
                                className="text-muted-foreground hover:text-foreground"
                              >
                                Non lo so
                              </Button>
                              <Button
                                variant="default"
                                disabled={!writtenAnswer.trim() || busy}
                                onClick={handleWrittenAnswer}
                              >
                                Rispondi
                              </Button>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="rounded-lg border bg-card p-4">
                          <div className="mb-2 flex items-center justify-between">
                            <span className="text-meta font-medium">Registra o carica audio</span>
                            <IconButton
                              label="Annulla vocale"
                              icon={X}
                              onClick={() => setShowVoiceRecorder(false)}
                            />
                          </div>
                          <VoiceRecorder onRecorded={handleVoiceAnswer} disabled={busy} />
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {evaluationJob && (
                <JobProgress jobId={evaluationJob} label="Valutazione della risposta" onFinished={() => void evaluationFinished()} />
              )}

              {/* Scheda Esito */}
              {isAnswered && evaluatedResult && (
                <div
                  className={cn(
                    'rounded-lg border p-3.5 text-body',
                    evaluatedResult.outcome === 'corretta'
                      ? 'border-success/40 bg-success-soft'
                      : evaluatedResult.outcome === 'parziale'
                        ? 'border-warning/40 bg-warning-soft'
                        : evaluatedResult.outcome === 'sbagliata'
                          ? 'border-danger/30 bg-danger-soft'
                          : 'bg-card',
                  )}
                  data-testid="recall-result-card"
                >
                  <p
                    className={cn(
                      'font-semibold',
                      evaluatedResult.outcome === 'corretta'
                        ? 'text-success'
                        : evaluatedResult.outcome === 'parziale'
                          ? 'text-warning'
                          : evaluatedResult.outcome === 'sbagliata'
                            ? 'text-danger'
                            : 'text-foreground',
                    )}
                  >
                    {evaluatedResult.outcome === 'corretta'
                      ? 'Giusto.'
                      : evaluatedResult.outcome === 'parziale'
                        ? 'Risposta parziale.'
                        : evaluatedResult.outcome === 'sbagliata'
                          ? 'Sbagliata.'
                          : 'Valutazione'}
                  </p>
                  {evaluatedResult.explanation && (
                    <p className="mt-1 text-meta leading-relaxed">
                      {evaluatedResult.explanation}
                    </p>
                  )}
                  {currentQuestion.unit_ids.length > 0 && activeLessonId > 0 && (
                    <p className="mt-2 text-meta">
                      <Link
                        to={`/lezioni/${activeLessonId}`}
                        className="font-medium text-primary underline underline-offset-2 hover:opacity-80"
                      >
                        Rileggi l'unità {currentQuestion.unit_ids.join(', ')}
                      </Link>
                    </p>
                  )}
                </div>
              )}

              {/* Barra azioni inferiori */}
              <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t pt-3">
                <div className="flex items-center gap-1.5">
                  <IconButton
                    label="Buona domanda"
                    icon={ThumbsUp}
                    active={currentVote === 'up'}
                    onClick={() => handleVote('up')}
                  />
                  <IconButton
                    label="Domanda da scartare"
                    icon={ThumbsDown}
                    active={currentVote === 'down'}
                    onClick={() => handleVote('down')}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCommentModalOpen(true)}
                  >
                    <MessageSquare className="mr-1.5 size-3.5" aria-hidden />
                    Commenta
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={handleSkip}
                  >
                    <SkipForward className="mr-1.5 size-3.5" aria-hidden />
                    Salta
                  </Button>
                </div>

                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={handleEnd} disabled={busy}>
                    Termina
                  </Button>
                  <Button
                    variant="default"
                    disabled={busy}
                    onClick={() => askNext()}
                  >
                    Prossima
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Modal Domanda Scartata (Telefono-Pollice-Giu.dc.html) */}
      {discardModalOpen && (
        <div
          role="dialog"
          aria-labelledby="discard-title"
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
        >
          <div className="flex w-full max-w-md flex-col gap-3.5 rounded-t-xl border bg-card p-5 shadow-panel sm:rounded-xl">
            <div className="flex items-center justify-between">
              <h3 id="discard-title" className="text-body font-semibold">
                Domanda scartata
              </h3>
              <IconButton
                label="Chiudi"
                icon={X}
                onClick={() => setDiscardModalOpen(false)}
              />
            </div>

            <p className="text-meta text-muted-foreground">
              Non te la riproporrò. Perché? <span className="opacity-75">(facoltativo)</span>
            </p>

            <div role="group" aria-label="Motivo dello scarto" className="flex flex-wrap gap-2">
              {DISCARD_REASONS.map(({ id: reasonId, label: reasonLabel }) => {
                const checked = selectedReasons.has(reasonId)
                return (
                  <button
                    key={reasonId}
                    type="button"
                    aria-pressed={checked}
                    onClick={() => {
                      const next = new Set(selectedReasons)
                      if (checked) next.delete(reasonId)
                      else next.add(reasonId)
                      setSelectedReasons(next)
                    }}
                    className={cn(
                      'rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
                      checked
                        ? 'bg-primary text-primary-foreground font-semibold'
                        : 'bg-muted text-foreground hover:bg-muted/80',
                    )}
                  >
                    {reasonLabel}
                  </button>
                )
              })}
            </div>

            <button
              type="button"
              onClick={() => {
                setDiscardModalOpen(false)
                setCommentModalOpen(true)
              }}
              className="inline-flex items-center gap-1.5 self-start text-meta text-primary hover:underline"
            >
              <MessageSquare className="size-3.5" aria-hidden />
              Scrivi un commento e rigenera
            </button>

            <div className="mt-2 flex items-center justify-between gap-2 border-t pt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDiscardModalOpen(false)}
              >
                Annulla
              </Button>
              <Button variant="default" size="sm" onClick={handleConfirmDiscard}>
                Prossima
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Commenta e Rigenera (Telefono-Commenta.dc.html) */}
      {commentModalOpen && currentQuestion && (
        <div
          role="dialog"
          aria-labelledby="comment-title"
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
        >
          <div className="flex w-full max-w-md flex-col gap-3.5 rounded-t-xl border bg-card p-5 shadow-panel sm:rounded-xl">
            <div className="flex items-center justify-between">
              <h3 id="comment-title" className="text-body font-semibold">
                Commenta la domanda
              </h3>
              <IconButton
                label="Chiudi"
                icon={X}
                onClick={() => setCommentModalOpen(false)}
              />
            </div>

            <div className="rounded-lg bg-muted/50 p-2.5 text-meta">
              <p className="text-muted-foreground">
                {currentQuestion.type.toUpperCase()} · unità {currentQuestion.unit_ids.join(', ')}
              </p>
              <p className="mt-0.5 font-medium text-foreground">
                {currentQuestion.question_text}
              </p>
            </div>

            <div>
              <label
                htmlFor="comment-textarea"
                className="mb-1 block text-meta text-muted-foreground"
              >
                Cosa non va, o cosa vorresti invece
              </label>
              <textarea
                id="comment-textarea"
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                placeholder="Per esempio: troppo facile, chiedimi di ragionare su un caso concreto."
                rows={4}
                className="block w-full resize-none rounded-md border bg-card p-2.5 text-meta placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
              />
            </div>

            <Button
              variant="default"
              size="sm"
              disabled={!commentText.trim() || regenerateMutation.isPending}
              onClick={handleCommentRegenerate}
              className="mt-1"
            >
              <Sparkles className="mr-1.5 size-3.5" aria-hidden />
              {regenerateMutation.isPending ? 'Invio in corso…' : 'Invia e rigenera'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
