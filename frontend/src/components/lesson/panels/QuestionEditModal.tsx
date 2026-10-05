import { Sparkles } from 'lucide-react'
import { useState } from 'react'

import { errorMessage, type Schemas } from '@/api/client'
import { jobFinished, useJobStatus } from '@/api/jobStatus'
import { useEditQuestion, useRecallQuestions, useRegenerateComment, type RecallQuestionDetail } from '@/api/recall'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { cn } from '@/lib/utils'

/** I tipi con il commento pregenerato dell'IA (per gli altri il modello non lo prevede). */
const TYPES_WITH_COMMENT = ['quiz', 'vasta', 'esercizio']

const COMMENT_LABEL: Record<string, string> = {
  quiz: "Spiegazione della risposta giusta",
  vasta: 'Scaletta della risposta ideale',
  esercizio: 'Schema di risoluzione',
}

const TYPE_LABEL: Record<string, string> = {
  quiz: 'Quiz', mirata: 'Domanda mirata', vasta: 'Domanda vasta', caso: 'Caso clinico', esercizio: 'Esercizio',
}

/**
 * Modifica a mano di una domanda del pannello (4.2.2b3): il testo sempre, le alternative e la
 * risposta giusta nei quiz, il commento dell'IA dove il tipo lo prevede (anche riscritto dall'IA).
 * Salvata, la domanda torna fra quelle da porre.
 */
export function QuestionEditModal({ lessonId, question, open, onClose }: {
  lessonId: number
  question: RecallQuestionDetail
  open: boolean
  onClose: () => void
}) {
  // Il testo delle domande da porre arriva senza soluzione: per modificarle serve reveal.
  const revealed = useRecallQuestions(lessonId, true)
  const full = revealed.data?.questions.find((q) => q.id === question.id)
  return (
    <Modal open={open} onClose={onClose} title={`Modifica domanda · ${TYPE_LABEL[question.type] ?? question.type}`}
      className="w-[min(560px,calc(100vw-32px))]" testId="question-edit-modal">
      {revealed.isError ? (
        <Alert tone="danger" className="mt-3">{errorMessage(revealed.error)}</Alert>
      ) : !full ? (
        <div className="mt-4 flex flex-col gap-2" aria-busy="true" role="status" aria-label="Carico la domanda">
          <div className="h-16 animate-pulse rounded bg-muted" />
          <div className="h-8 animate-pulse rounded bg-muted" />
        </div>
      ) : (
        <EditForm key={full.id} lessonId={lessonId} question={full} onClose={onClose} />
      )}
    </Modal>
  )
}

function EditForm({ lessonId, question, onClose }: {
  lessonId: number
  question: RecallQuestionDetail
  onClose: () => void
}) {
  const edit = useEditQuestion(lessonId)
  const regenerate = useRegenerateComment(lessonId)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJobStatus(jobId)
  const isQuiz = question.type === 'quiz'
  const hasComment = TYPES_WITH_COMMENT.includes(question.type)

  const [text, setText] = useState(question.question_text)
  const [options, setOptions] = useState<string[]>(() => {
    const given = question.options ?? []
    return [0, 1, 2, 3].map((i) => given[i] ?? '')
  })
  const [correct, setCorrect] = useState<number>(question.correct_index ?? 0)
  const [comment, setComment] = useState(question.explanation ?? '')

  // Il job restituisce la domanda col commento riscritto: si legge da lì, senza aspettare il refetch.
  const regenerated = jobFinished(job.data) ? (job.data?.result?.question as Schemas['RecallQuestion'] | undefined) : undefined
  const commentValue = regenerated?.explanation ?? comment
  const regenerating = jobId !== null && !jobFinished(job.data)

  const canSave = text.trim().length > 0
    && (!isQuiz || (options.every((o) => o.trim()) && new Set(options.map((o) => o.trim().toLowerCase())).size === 4))
    && (!hasComment || commentValue.trim().length > 0)

  const save = () => {
    edit.mutate({
      questionId: question.id,
      body: {
        question_text: text.trim(),
        options: isQuiz ? options.map((o) => o.trim()) : null,
        correct_index: isQuiz ? correct : null,
        explanation: hasComment ? commentValue.trim() : null,
      },
    }, { onSuccess: onClose })
  }

  return (
    <div className="mt-3 flex flex-col gap-3">
      <div>
        <label htmlFor="edit-q-text" className="mb-1 block text-meta text-muted-foreground">Testo della domanda</label>
        <textarea
          id="edit-q-text"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="block w-full resize-y rounded-md border bg-card px-2.5 py-1.5 text-body focus-visible:outline-2 focus-visible:outline-ring"
        />
      </div>

      {isQuiz && (
        <fieldset>
          <legend className="mb-1 text-meta text-muted-foreground">Alternative (la giusta è quella segnata)</legend>
          <div className="flex flex-col gap-1.5">
            {options.map((option, i) => (
              <label key={i} className={cn('flex items-center gap-2 rounded-md border px-2 py-1.5', correct === i && 'border-success bg-success-soft')}>
                <input
                  type="radio"
                  name="edit-q-correct"
                  checked={correct === i}
                  onChange={() => setCorrect(i)}
                  aria-label={`La ${i + 1}ª alternativa è quella giusta`}
                  className="size-4 shrink-0 text-primary focus-visible:outline-2 focus-visible:outline-ring"
                />
                <span className="shrink-0 text-meta font-semibold text-muted-foreground">{'ABCD'[i]}.</span>
                <Input
                  value={option}
                  aria-label={`Alternativa ${'ABCD'[i]}`}
                  onChange={(e) => setOptions(options.map((o, j) => (j === i ? e.target.value : o)))}
                  className="h-8 flex-1 border-0 bg-transparent px-1 py-0 focus-visible:outline-0"
                />
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {hasComment && (
        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <label htmlFor="edit-q-comment" className="text-meta text-muted-foreground">{COMMENT_LABEL[question.type]}</label>
            <Button
              variant="ghost"
              size="sm"
              disabled={regenerating || regenerate.isPending}
              data-testid="question-edit-regenerate"
              onClick={() => regenerate.mutate(question.id, { onSuccess: (accepted) => setJobId(accepted.job_id) })}
            >
              <Sparkles className="mr-1.5 size-3.5" aria-hidden />
              {regenerating ? 'Riscrivo…' : "Rigenera con l'IA"}
            </Button>
          </div>
          <textarea
            id="edit-q-comment"
            rows={4}
            value={commentValue}
            disabled={regenerating}
            onChange={(e) => setComment(e.target.value)}
            className="block w-full resize-y rounded-md border bg-card px-2.5 py-1.5 text-meta focus-visible:outline-2 focus-visible:outline-ring"
          />
        </div>
      )}

      {job.data?.state === 'failed' && <Alert tone="danger">{job.data.error ?? 'Rigenerazione non riuscita.'}</Alert>}
      {regenerate.isError && <Alert tone="danger">{errorMessage(regenerate.error)}</Alert>}
      {edit.isError && <Alert tone="danger">{errorMessage(edit.error)}</Alert>}

      <p className="text-meta text-muted-foreground">La domanda modificata torna fra quelle da porre.</p>
      <div className="flex items-center justify-end gap-2 border-t pt-3">
        <Button variant="outline" size="sm" onClick={onClose}>Annulla</Button>
        <Button size="sm" disabled={!canSave || edit.isPending || regenerating} onClick={save} data-testid="question-edit-save">Salva</Button>
      </div>
    </div>
  )
}
