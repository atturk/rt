import { type FormEvent, useState } from 'react'

import { errorMessage } from '@/api/client'
import { useVote, type RecallAnswerRecord, type RecallQuestion, type RecallSessionInfo } from '@/api/recall'
import { VoiceRecorder } from '@/components/VoiceRecorder'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { VOTES } from '@/lib/recall'
import { cn } from '@/lib/utils'

/* Pezzi della sessione di recall comuni alla sessione di una lezione e a quella per materia. */

export function VoteButtons({ lessonId, questionId, current }: { lessonId: number; questionId: string; current?: string | null }) {
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
export function AnsweredQuestion({ question, answer, lessonId }: { question: RecallQuestion; answer: RecallAnswerRecord; lessonId: number }) {
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

export function QuizForm({ question, onAnswer, pending }: { question: RecallQuestion; onAnswer: (choice: number) => void; pending: boolean }) {
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

export function OpenAnswerForm({
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

/** Riepilogo salvato dal backend alla chiusura della sessione. */
export function SessionSummary({ session }: { session: RecallSessionInfo }) {
  const s = session.summary
  if (!s) return null
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-muted/50 px-4 py-3" data-testid="session-summary" data-session-id={session.id}>
      <h3 className="text-sm font-bold">Sessione terminata</h3>
      <dl className="grid grid-cols-3 gap-2 text-center">
        {[
          ['Domande', s.questions, 'questions'],
          ['Risposte date', s.answered, 'answered'],
          ['Quiz giusti', `${s.correct} su ${s.quiz_answered}`, 'correct'],
        ].map(([label, value, key]) => (
          <div key={key} className="flex flex-col rounded-md bg-card px-2 py-1.5">
            <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</dt>
            <dd className="text-lg font-bold tabular-nums" data-summary={key}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
