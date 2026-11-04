import { BookOpen, Loader2, Plus, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, errorMessage, unwrap } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Alert } from '@/components/ui/alert'

export interface WelcomeBoxProps {
  onNewLesson: () => void
  onSampleImported: () => void
  onDismiss: () => void
}

export function WelcomeBox({ onNewLesson, onSampleImported, onDismiss }: WelcomeBoxProps) {
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const estimate = useQuery({
    queryKey: ['settings-estimate'],
    queryFn: () => unwrap(api.GET('/api/v1/settings/estimate')),
  })

  async function handleImportSample() {
    setImporting(true)
    setError(null)
    try {
      await unwrap(api.POST('/api/v1/lessons/sample'))
      onSampleImported()
    } catch (err) {
      setError(errorMessage(err))
      setImporting(false)
    }
  }

  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm max-w-2xl" data-testid="welcome-box">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-primary/10 p-2 text-primary">
          <BookOpen className="size-6" aria-hidden />
        </div>
        <div className="flex-1 space-y-3">
          <div>
            <h2 className="text-h3 font-semibold text-foreground">Benvenuto in RT</h2>
            <p className="mt-1 text-body text-muted-foreground">
              RT organizza le tue lezioni universitarie in unità di studio, le confronta con le fonti del docente e prepara il materiale per il ripasso attivo.
            </p>
          </div>
          {estimate.data && (
            <p className="text-meta text-muted-foreground" data-testid="welcome-estimate">
              Costo stimato con i modelli attuali:{' '}
              <strong className="font-semibold text-foreground">{estimate.data.formatted}</strong>
            </p>
          )}
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button
              variant="default"
              onClick={handleImportSample}
              disabled={importing}
              data-testid="welcome-import-sample"
            >
              {importing ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" aria-hidden />}
              Prova con una lezione di esempio
            </Button>
            <Button
              variant="outline"
              onClick={onNewLesson}
              disabled={importing}
              data-testid="welcome-create-lesson"
            >
              <Plus className="size-4" aria-hidden />
              Crea la tua prima lezione
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDismiss}
              disabled={importing}
              className="text-muted-foreground hover:text-foreground"
              data-testid="welcome-dismiss"
            >
              Non mostrare più
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
