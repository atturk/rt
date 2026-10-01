import { Trash2 } from 'lucide-react'
import { useMemo, useState, type MouseEvent } from 'react'
import { Link, useParams } from 'react-router'

import { errorMessage } from '@/api/client'
import { useLesson } from '@/api/hooks'
import { useDeleteQuestions, useRecallQuestions, type RecallQuestionDetail } from '@/api/recall'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { lessonTitle } from '@/lib/format'
import { RECALL_TYPES, VOTES, typeLabel } from '@/lib/recall'
import { cn } from '@/lib/utils'

const STATUS: Record<string, string> = { pending: 'Da porre', asked: 'Posta', answered: 'Risposta' }

function QuestionItem({
  question,
  unitTitles,
  checked,
  onCheck,
}: {
  question: RecallQuestionDetail
  unitTitles: Record<string, string>
  checked: boolean
  onCheck: (event: MouseEvent<HTMLInputElement>) => void
}) {
  const vote = VOTES.find((v) => v.value === question.vote)
  const units = question.unit_ids.map((u) => (unitTitles[u] ? `${u} ${unitTitles[u]}` : u)).join(' · ')
  return (
    <li
      className={cn('flex gap-3 border-t py-3', checked && 'bg-accent/40')}
      data-testid="question-item"
      data-question-id={question.id}
      data-type={question.type}
    >
      <input
        type="checkbox"
        className="mt-1 shrink-0"
        checked={checked}
        onClick={onCheck}
        onChange={() => undefined}
        aria-label={`Seleziona ${question.question_text}`}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge>{typeLabel(question.type)}</Badge>
          <Badge tone={question.status === 'pending' ? 'neutral' : 'success'}>{STATUS[question.status] ?? question.status}</Badge>
          {question.classifier_level != null && <span>L{question.classifier_level}</span>}
          {vote && <span>{vote.label}</span>}
          <span className="min-w-0 truncate" title={units}>
            {units}
          </span>
        </div>
        <p className="text-sm font-medium leading-relaxed">{question.question_text}</p>
        {question.options && (
          <ol className="ml-5 list-[upper-alpha] text-sm">
            {question.options.map((option, i) => (
              <li key={i} className={cn(i === question.correct_index && 'font-medium text-success')}>
                {option}
              </li>
            ))}
          </ol>
        )}
        {question.explanation && <p className="whitespace-pre-wrap text-xs text-muted-foreground">{question.explanation}</p>}
      </div>
    </li>
  )
}

/** /lezioni/:id/recall/domande: tutte le domande della lezione, da rivedere ed eliminare anche in blocco. */
export function QuestionsPage() {
  const lessonId = Number(useParams().lessonId)
  const lesson = useLesson(lessonId)
  const [reveal, setReveal] = useState(false)
  const [type, setType] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [anchor, setAnchor] = useState<number | null>(null)
  const [confirming, setConfirming] = useState(false)
  const questions = useRecallQuestions(lessonId, reveal)
  const remove = useDeleteQuestions(lessonId)

  const all = useMemo(() => questions.data?.questions ?? [], [questions.data])
  const shown = useMemo(
    () => all.filter((q) => (!type || q.type === type) && (!status || q.status === status)),
    [all, type, status],
  )
  // Si elimina solo ciò che si vede: le domande nascoste dai filtri restano fuori.
  const chosen = shown.filter((q) => selected.has(q.id))
  const allShownChosen = shown.length > 0 && shown.every((q) => selected.has(q.id))

  function check(index: number, event: MouseEvent<HTMLInputElement>) {
    const id = shown[index].id
    const on = !selected.has(id)
    const next = new Set(selected)
    // Maiuscolo+clic: tutte le domande fra l'ultima spuntata e questa prendono lo stesso stato.
    const range = event.shiftKey && anchor != null ? shown.slice(Math.min(anchor, index), Math.max(anchor, index) + 1) : [shown[index]]
    for (const q of range) {
      if (on) next.add(q.id)
      else next.delete(q.id)
    }
    setSelected(next)
    setAnchor(index)
  }

  function toggleShown() {
    const next = new Set(selected)
    for (const q of shown) {
      if (allShownChosen) next.delete(q.id)
      else next.add(q.id)
    }
    setSelected(next)
  }

  function confirmDelete() {
    remove.mutate(chosen.map((q) => q.id), {
      onSuccess: () => {
        setSelected(new Set())
        setAnchor(null)
      },
      onSettled: () => setConfirming(false),
    })
  }

  const answered = chosen.filter((q) => q.status !== 'pending').length
  return (
    <section className="flex flex-col gap-4">
      <Link to={`/lezioni/${lessonId}/recall`} className="text-xs text-muted-foreground hover:underline">
        ← Recall della lezione
      </Link>
      <h1 className="text-xl font-bold tracking-tight">Domande · {lesson.data ? lessonTitle(lesson.data) : '…'}</h1>
      <Card className="flex flex-col gap-3 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="questions-type">Tipo</Label>
            <Select id="questions-type" className="w-36" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">Tutti</option>
              {RECALL_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="questions-status">Stato</Label>
            <Select id="questions-status" className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Tutti</option>
              {Object.entries(STATUS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
            Mostra le soluzioni
          </label>
          <span className="ml-auto pb-2 text-xs text-muted-foreground" data-testid="questions-count">
            {shown.length} di {all.length} domande
          </span>
        </div>
        {reveal && <p className="text-xs text-muted-foreground">Le soluzioni delle domande ancora da porre tolgono la sorpresa al recall.</p>}
        <div className="flex flex-wrap items-center gap-3 border-t pt-3">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={allShownChosen} onChange={toggleShown} disabled={shown.length === 0} />
            Seleziona tutte quelle mostrate
          </label>
          <span className="text-xs text-muted-foreground">Maiuscolo+clic seleziona un intervallo.</span>
          <Button size="sm" variant="outline" className="ml-auto" disabled={chosen.length === 0 || remove.isPending} onClick={() => setConfirming(true)}>
            <Trash2 aria-hidden="true" /> Elimina selezionate ({chosen.length})
          </Button>
        </div>
        {remove.isError && <Alert tone="danger">{errorMessage(remove.error)}</Alert>}
        {remove.isSuccess && <Alert>Domande eliminate: {remove.data.deleted}.</Alert>}
        {questions.isError && <Alert tone="danger">{errorMessage(questions.error)}</Alert>}
        {questions.isPending && <p className="text-sm text-muted-foreground">Carico le domande…</p>}
        {questions.isSuccess && all.length === 0 && <p className="text-sm text-muted-foreground">Nessuna domanda: genera il pool dalla pagina del recall.</p>}
        <ul aria-label="Domande della lezione">
          {shown.map((q, i) => (
            <QuestionItem key={q.id} question={q} unitTitles={questions.data?.unit_titles ?? {}} checked={selected.has(q.id)} onCheck={(e) => check(i, e)} />
          ))}
        </ul>
      </Card>
      <ConfirmDialog
        open={confirming}
        title={`Eliminare ${chosen.length === 1 ? 'la domanda selezionata' : `le ${chosen.length} domande selezionate`}?`}
        confirmLabel="Elimina"
        confirmDisabled={remove.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setConfirming(false)}
      >
        L'eliminazione non si può annullare.
        {answered === 1 && ' Una è già stata posta: la sua risposta sparisce dallo storico.'}
        {answered > 1 && ` ${answered} sono già state poste: le loro risposte spariscono dallo storico.`}
      </ConfirmDialog>
    </section>
  )
}
