import {
  BookOpen,
  Brain,
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
  useRestorable,
  useRestoreQuestions,
  useSkip,
  useSubjectEnd,
  useSubjectNext,
  useSubjectRecall,
  useVote,
  type RecallQuestion,
  type RecallType,
} from '@/api/recall'
import { JobProgress } from '@/components/JobProgress'
import { PageHeader } from '@/components/shell/PageHeader'
import { VoiceRecorder } from '@/components/VoiceRecorder'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { buttonVariants } from '@/components/ui/button-variants'
import { Chip } from '@/components/ui/chip'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'
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
  unit,
}: {
  lessonId?: number
  selectionIds?: number[]
  /** Ripasso di una sola unità (dallo Studio): domande filtrate e ritorno alla lettura. */
  unit?: {
    id: string
    title: string
    /** Domande da porre per tipo: i tipi vuoti restano spenti. */
    pending: Record<string, number>
    onBack: () => void
    /** Finite le domande dell'unità: avanti nello Studio (unità o lezione successiva). */
    onDone?: () => void
    /** Etichetta del pulsante di `onDone` ("Unità successiva", "Fine"…). */
    doneLabel?: string
  }
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
  // Rigenerazione della domanda: job in corso
  const [regenerationJob, setRegenerationJob] = useState<string | null>(null)
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
  const restorable = useRestorable(lessonId ?? 0, Boolean(lessonId && !isSelection))
  const restore = useRestoreQuestions(lessonId ?? 0)
  const askedCount = restorable.data?.asked ?? 0
  const wrongCount = restorable.data?.wrong ?? 0

  // Tipo di recall (persiste l'ultimo usato)
  const [qtype, setQtype] = useState<SessionType>(() => {
    // Ripasso di un'unità: si parte sempre da tutti i tipi, l'ultimo usato altrove non c'entra.
    if (unit) return 'mista'
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
      setRegenerationJob(null)
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
          q = await nextLesson.mutateAsync({ qtype: typeToAsk, excludeId, unitId: unit?.id })
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
    [isSelection, lessonId, nextLesson, nextSubject, qtype, unit],
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
    // lo stesso tipo non scarta la domanda che c'è già
    if (nextType === qtype && currentQuestion) return
    setQtype(nextType)
    if (!unit) {
      try {
        localStorage.setItem(LAST_TYPE_KEY, nextType)
      } catch {
        // Ignora errori localStorage
      }
    }
    void askNext(nextType)
  }

  const handleRestore = (scope: 'asked' | 'wrong') => {
    restore.mutate(scope, {
      onSuccess: () => {
        void askNext(qtype)
      },
    })
  }

  // Risposta a quiz: il clic sull'alternativa è già la risposta (come nello Studio).
  // L'esito, la risposta giusta e la spiegazione li dice il server: /recall/next non li manda.
  const handleQuizAnswer = async (choice: number) => {
    if (!currentQuestion || !activeLessonId || isAnswered || busy) return
    setSelectedChoice(choice)
    try {
      const res = await answerMutation.mutateAsync({ questionId: currentQuestion.id, choice })
      const quiz = 'quiz' in res ? (res.quiz as Schemas['QuizResult']) : null
      setEvaluatedResult({
        correct: quiz?.correct ?? false,
        outcome: quiz?.correct ? 'corretta' : 'sbagliata',
        explanation: quiz?.question.explanation ?? undefined,
        correctIndex: quiz?.question.correct_index ?? undefined,
      })
    } catch (err) {
      setSelectedChoice(null)
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
      const res = await answerMutation.mutateAsync({ questionId: currentQuestion.id, dontKnow: true })
      const quiz = 'quiz' in res ? (res.quiz as Schemas['QuizResult']) : null
      setEvaluatedResult({
        correct: false,
        outcome: 'sbagliata',
        explanation: quiz?.question.explanation ?? currentQuestion.explanation ?? undefined,
        correctIndex: quiz?.question.correct_index ?? undefined,
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
      const res = await regenerateMutation.mutateAsync({
        questionId: currentQuestion.id,
        comment: commentText.trim(),
      })
      setCommentModalOpen(false)
      if (res && typeof res === 'object' && 'job_id' in res && (res as { job_id?: string }).job_id) {
        setRegenerationJob((res as { job_id: string }).job_id)
      } else {
        void askNext()
      }
    } catch (err) {
      setGeneralError(errorMessage(err))
    }
  }

  const regenerationFinished = () => {
    setRegenerationJob(null)
    void askNext()
  }

  // Termina sessione. La domanda lasciata a metà torna fra quelle da porre: /recall/next l'ha
  // già segnata come posta, e senza questo resterebbe tale per sempre.
  const handleEnd = async () => {
    if (currentQuestion && !isAnswered) {
      try {
        await skipMutation.mutateAsync(currentQuestion.id)
      } catch {
        // se non si riesce a rimetterla in coda, la sessione finisce comunque
      }
    }
    if (unit) {
      if (lessonId) {
        try {
          await endLessonSession.mutateAsync()
        } catch {
          // la sessione dell'unità finisce comunque: si torna allo studio
        }
      }
      unit.onBack()
      return
    }
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

  const unitPending = unit ? Object.values(unit.pending).reduce((a, b) => a + b, 0) : 0
  // Le domande vaste non si attaccano a una singola unità: nel ripasso dell'unità non ci sono.
  const sessionTypes = unit ? SESSION_TYPES.filter((t) => t.id !== 'vasta') : SESSION_TYPES
  const isQuiz = currentQuestion?.type === 'quiz'
  const isAnswered = evaluatedResult !== null || evaluationJob !== null
  const busy =
    answerMutation.isPending ||
    voiceMutation.isPending ||
    voteMutation.isPending ||
    regenerateMutation.isPending ||
    regenerationJob !== null ||
    nextLesson.isPending ||
    nextSubject.isPending

  const optionLetters = ['A', 'B', 'C', 'D']

  return (
    <div className="flex min-h-screen flex-col bg-background" data-testid="recall-session-page">
      {/* Header sessione */}
      <PageHeader
        back={unit ? { onClick: unit.onBack, label: 'Torna allo studio' } : { to: backUrl, label: 'Esci' }}
        title={
          unit ? (
            <>
              Ripasso · <strong className="font-semibold text-foreground">{unit.title}</strong>
            </>
          ) : (
            <>
              Recall · <strong className="font-semibold text-foreground">{title}</strong>
            </>
          )
        }
        muted
        titleAs="h1"
        actions={
          unit ? (
            <IconButton label="Torna allo studio" icon={BookOpen} onClick={unit.onBack} />
          ) : (
            <span className="text-meta text-muted-foreground">{daPorreCount} da porre</span>
          )
        }
      />

      {/* Main content */}
      <main className="flex flex-1 justify-center px-4 py-8">
        <div className="flex w-full max-w-(--reading-width) flex-col gap-5">
          {/* Selettore tipi (chips) */}
          <div
            role="group"
            aria-label="Tipo di domanda"
            className="flex flex-wrap gap-1.5"
          >
            {sessionTypes.map(({ id: typeId, label }) => {
              const active = qtype === typeId
              const count = unit ? (typeId === 'mista' ? unitPending : unit.pending[typeId] ?? 0) : null
              return (
                <Chip
                  key={typeId}
                  active={active}
                  aria-pressed={active}
                  disabled={count === 0}
                  onClick={() => handleTypeChange(typeId)}
                >
                  {label}{count ? ` ${count}` : ''}
                </Chip>
              )
            })}
          </div>

          {generalError && <Alert tone="danger">{generalError}</Alert>}

          {emptyPoolError && (
            <div className="rounded-lg border bg-card p-6 text-center" data-testid="recall-empty">
              <Brain className="mx-auto mb-3 size-8 text-muted-foreground" aria-hidden />
              <p className="text-body font-semibold">
                {unit
                  ? qtype === 'mista'
                    ? 'Hai finito le domande di questa unità'
                    : 'Nessuna domanda di questo tipo'
                  : 'Nessuna domanda disponibile'}
              </p>
              <p className="mt-1 text-meta text-muted-foreground">
                {unit
                  ? qtype === 'mista'
                    ? 'Puoi tornare al testo dell’unità o andare avanti.'
                    : 'Scegli un altro tipo o prova mista.'
                  : isSelection
                    ? daPorreCount === 0
                      ? 'Non ci sono domande da porre. Puoi generare nuove domande dai pannelli delle rispettive lezioni.'
                      : 'Non ci sono domande da porre per il tipo selezionato. Scegli un altro tipo o prova mista.'
                    : daPorreCount === 0
                      ? 'Non ci sono domande da porre in questa lezione. Puoi generarne di nuove o riproporre quelle già poste.'
                      : 'Non ci sono domande da porre per il tipo selezionato. Scegli un altro tipo o prova mista.'}
              </p>
              {restore.isError && <Alert tone="danger" className="mt-3">{errorMessage(restore.error)}</Alert>}
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                {/* Prova mista: solo quando serve davvero (tipo diverso da mista e domande da porre > 0) */}
                {qtype !== 'mista' && (unit ? unitPending > 0 : daPorreCount > 0) && (
                  <Button variant="outline" size="sm" onClick={() => handleTypeChange('mista')}>
                    Prova mista
                  </Button>
                )}

                {/* Una lezione sola, zero da porre: Genera domande */}
                {!unit && !isSelection && daPorreCount === 0 && lessonId && (
                  <Link
                    to={`/lezioni/${lessonId}?panel=domande`}
                    className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                  >
                    Genera domande
                  </Link>
                )}

                {/* Ripescaggio: solo se una lezione sola o modo unità, e conteggio > 0 */}
                {!isSelection && lessonId && wrongCount > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={restore.isPending}
                    onClick={() => handleRestore('wrong')}
                  >
                    Riproponi le sbagliate ({wrongCount})
                  </Button>
                )}
                {!isSelection && lessonId && askedCount > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={restore.isPending}
                    onClick={() => handleRestore('asked')}
                  >
                    Riproponi le poste ({askedCount})
                  </Button>
                )}

                {/* Modo unità: Torna allo studio e Unità successiva */}
                {unit && (
                  <Button variant="outline" size="sm" onClick={unit.onBack}>
                    Torna allo studio
                  </Button>
                )}
                {unit?.onDone && (
                  <Button size="sm" onClick={unit.onDone} data-testid="recall-unit-done">
                    {unit.doneLabel ?? 'Avanti'}
                  </Button>
                )}
              </div>
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

                      return (
                        <Button
                          key={idx}
                          variant={isSelected ? 'default' : 'outline'}
                          disabled={isAnswered || busy}
                          onClick={() => void handleQuizAnswer(idx)}
                          className={cn(
                            'h-auto min-h-12 w-full justify-start whitespace-normal rounded-lg px-3.5 py-2.5 text-left text-body font-normal transition-colors',
                            isAnswered && isCorrect && 'border-success bg-success-soft text-success font-semibold',
                            isAnswered && isWrongSelection && 'border-danger bg-danger-soft text-danger font-medium',
                          )}
                        >
                          <span className="mr-2 font-semibold opacity-75">{letter}.</span>
                          <span className="flex-1">{option}</span>
                        </Button>
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
                      <span className="text-meta text-muted-foreground">Tocca l’alternativa per rispondere</span>
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
              {regenerationJob && (
                <JobProgress jobId={regenerationJob} label="Rigenerazione della domanda" onFinished={regenerationFinished} />
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
                        to={`/lezioni/${activeLessonId}#unit-${currentQuestion.unit_ids[0]}`}
                        className="font-medium text-link underline underline-offset-2 hover:opacity-80"
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
                  {/* Prima di rispondere si salta (la domanda torna fra quelle da porre); "Prossima"
                      compare dopo la risposta, quando non lascia niente a metà. */}
                  {!isAnswered && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={handleSkip}
                    >
                      <SkipForward className="mr-1.5 size-3.5" aria-hidden />
                      Salta
                    </Button>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={handleEnd} disabled={busy}>
                    Termina
                  </Button>
                  {isAnswered && (
                    <Button
                      variant="default"
                      disabled={busy}
                      onClick={() => {
                        if (!isSelection && currentQuestion.remaining === 0) {
                          setCurrentQuestion(null)
                          setEmptyPoolError(true)
                        } else void askNext()
                      }}
                    >
                      {!isSelection && currentQuestion.remaining === 0 ? 'Fine' : 'Prossima'}
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Modal Domanda Scartata (Telefono-Pollice-Giu.dc.html) */}
      <Modal
        open={discardModalOpen}
        onClose={() => setDiscardModalOpen(false)}
        title="Domanda scartata"
      >
        <div className="mt-3 flex flex-col gap-3.5">
          <p className="text-meta text-muted-foreground">
            Non te la riproporrò. Perché? <span className="opacity-75">(facoltativo)</span>
          </p>

          <div role="group" aria-label="Motivo dello scarto" className="flex flex-wrap gap-2">
            {DISCARD_REASONS.map(({ id: reasonId, label: reasonLabel }) => {
              const checked = selectedReasons.has(reasonId)
              return (
                <Chip
                  key={reasonId}
                  active={checked}
                  aria-pressed={checked}
                  onClick={() => {
                    const next = new Set(selectedReasons)
                    if (checked) next.delete(reasonId)
                    else next.add(reasonId)
                    setSelectedReasons(next)
                  }}
                >
                  {reasonLabel}
                </Chip>
              )
            })}
          </div>

          <button
            type="button"
            onClick={() => {
              setDiscardModalOpen(false)
              setCommentModalOpen(true)
            }}
            className="inline-flex items-center gap-1.5 self-start text-meta text-link hover:underline"
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
      </Modal>

      {/* Modal Commenta e Rigenera (Telefono-Commenta.dc.html) */}
      <Modal
        open={commentModalOpen && Boolean(currentQuestion)}
        onClose={() => setCommentModalOpen(false)}
        title="Commenta la domanda"
      >
        {currentQuestion && (
          <div className="mt-3 flex flex-col gap-3.5">
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
              className="mt-1 self-start"
            >
              <Sparkles className="mr-1.5 size-3.5" aria-hidden />
              {regenerateMutation.isPending ? 'Invio in corso…' : 'Invia e rigenera'}
            </Button>
          </div>
        )}
      </Modal>
    </div>
  )
}
