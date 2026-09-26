import { Mic, Square, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { recordingFormat } from '@/lib/recording'

/**
 * Risposta vocale: registra dal microfono (MediaRecorder) oppure carica un file audio.
 * Il file va all'API così com'è; trascrizione e valutazione avvengono in un job.
 */
export function VoiceRecorder({ onRecorded, disabled }: { onRecorded: (audio: File) => void; disabled?: boolean }) {
  const [recording, setRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const supported = typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices?.getUserMedia

  useEffect(() => () => recorder.current?.stream.getTracks().forEach((t) => t.stop()), [])

  async function start() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const format = recordingFormat((t) => MediaRecorder.isTypeSupported(t))
      const rec = new MediaRecorder(stream, format.mimeType ? { mimeType: format.mimeType } : undefined)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const type = rec.mimeType || format.mimeType || 'audio/webm'
        onRecorded(new File(chunks, `risposta.${format.extension}`, { type }))
      }
      rec.start()
      recorder.current = rec
      setRecording(true)
    } catch (err) {
      setError(err instanceof Error && err.name === 'NotAllowedError' ? 'Il browser non ha il permesso di usare il microfono.' : 'Microfono non disponibile.')
    }
  }

  function stop() {
    recorder.current?.stop()
    recorder.current = null
    setRecording(false)
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">Risposta vocale</span>
      <div className="flex flex-wrap items-center gap-2">
        {recording ? (
          <Button variant="destructive" onClick={stop}>
            <Square /> Ferma e invia
          </Button>
        ) : (
          <Button variant="outline" onClick={start} disabled={disabled || !supported}>
            <Mic /> Registra
          </Button>
        )}
        {recording && (
          <span role="status" className="flex items-center gap-1.5 text-xs text-danger">
            <span className="size-2 animate-pulse rounded-full bg-danger" aria-hidden /> Registrazione in corso…
          </span>
        )}
        <Label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md px-3 text-sm font-normal hover:bg-muted">
          <Upload className="size-4" aria-hidden /> Carica un file audio
          <input
            type="file"
            accept="audio/*,.m4a,.mp3,.wav,.ogg,.oga,.opus,.webm,.aac,.flac"
            className="sr-only"
            disabled={disabled || recording}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) onRecorded(file)
              e.target.value = ''
            }}
          />
        </Label>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
    </div>
  )
}
