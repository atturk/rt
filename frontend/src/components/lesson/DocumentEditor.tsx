import { useEffect, useState } from 'react'

import { ApiError, errorMessage, type Schemas } from '@/api/client'
import { useCheckDocument, useSaveDocument } from '@/api/documentEdit'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

import { MarkdownEditor } from './MarkdownEditor'

type Problem = Schemas['DocumentEditProblem']
export type DocumentSaveResult = Schemas['DocumentEditResult']

const CHECK_DELAY_MS = 400

function problemsOf(error: unknown): Problem[] | null {
  if (!(error instanceof ApiError) || error.code !== 'document_invalid') return null
  const errors = (error.details as { errors?: Problem[] } | undefined)?.errors
  return Array.isArray(errors) ? errors : null
}

type Props = {
  lessonId: number
  markdown: string
  leaseToken?: string
  /** Chiamata all'uscita: con il risultato se si è salvato, null se annullato o invariato. */
  onClose: (result: DocumentSaveResult | null) => void
}

/**
 * Editor Markdown con gli errori di validazione del server. Solo Fine salva;
 * Esc e Annulla scartano le modifiche.
 */
export function DocumentEditor({ lessonId, markdown, leaseToken, onClose }: Props) {
  const [text, setText] = useState(markdown)
  const [focusLine, setFocusLine] = useState<number | null>(null)
  const [preview, setPreview] = useState<{ html: string; errors: Problem[] } | null>(null)
  const check = useCheckDocument(lessonId)
  const save = useSaveDocument(lessonId, leaseToken)

  const { mutate: runCheck } = check
  useEffect(() => {
    const timer = window.setTimeout(() => {
      runCheck(text, { onSuccess: (data) => setPreview(data) })
    }, CHECK_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [text, runCheck])

  const finish = () => {
    if (save.isPending) return
    if (text === markdown) {
      onClose(null)
      return
    }
    save.mutate(text, { onSuccess: (result) => onClose(result) })
  }
  const saveProblems = problemsOf(save.error)
  const problems = saveProblems ?? preview?.errors ?? []

  return (
    <div className="flex flex-col gap-3" data-testid="document-editor">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-sm font-bold">
          Modifica dell'anteprima <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium uppercase">beta</span>
        </h2>
        <span className="text-xs text-muted-foreground">Fine salva · Esc annulla</span>
        <Button variant="outline" size="sm" onClick={() => onClose(null)} disabled={save.isPending}>
          Annulla
        </Button>
        <Button size="sm" onClick={finish} disabled={save.isPending}>
          {save.isPending ? 'Salvo…' : 'Fine'}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Ogni unità inizia con <code>### 1.1 Titolo</code> e nella riga sotto ha il suo timecode da solo, per esempio{' '}
        <code>12:30</code> (minuti:secondi) o <code>1:02:30</code> (ore:minuti:secondi): cambialo per spostare l'inizio
        dell'unità nell'audio. Non aggiungere né togliere sezioni o unità.
      </p>
      {save.isError && !saveProblems && <Alert tone="danger">{errorMessage(save.error)}</Alert>}
      {problems.length > 0 && (
        <Alert tone="danger">
          <p className="font-semibold">{saveProblems ? 'Non ho salvato:' : 'Così non si può salvare:'}</p>
          <ul className="mt-1 flex flex-col gap-0.5" data-testid="document-edit-errors">
            {problems.map((p, i) => (
              <li key={`${p.line ?? 'x'}-${i}`}>
                {p.line != null ? (
                  <button type="button" className="font-semibold underline" onClick={() => setFocusLine(p.line ?? null)}>
                    Riga {p.line}
                  </button>
                ) : null}
                {p.line != null ? ': ' : ''}
                {p.message}
              </li>
            ))}
          </ul>
        </Alert>
      )}
      <MarkdownEditor value={markdown} onChange={setText} onEscape={() => onClose(null)} label="Markdown dell'anteprima" focusLine={focusLine} />
    </div>
  )
}
