import { Fragment } from 'react'
import { Play } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { formatTime } from '@/lib/audio'

type Segment = Schemas['ASRRiskSegment']

/** I tratti restano leggibili anche nelle issue storiche prive di confidenza. */
export function ASRSegments({ segments, onSeek }: { segments: Segment[]; onSeek?: (seconds: number, play?: boolean, endSeconds?: number) => void }) {
  return <div className="flex flex-col gap-2">
    {[...segments].sort((a, b) => (a.start_s ?? Infinity) - (b.start_s ?? Infinity)).map((part, i) => {
      const words = [...(part.uncertain_words ?? [])].sort((a, b) => a.start_char - b.start_char)
      const characters = [...part.text_raw]
      let cursor = 0
      const text = words.flatMap((word, j) => {
        if (word.start_char < cursor || word.end_char > characters.length) return []
        const prefix = characters.slice(cursor, word.start_char).join('')
        cursor = word.end_char
        return [<Fragment key={j}>{prefix}<u className="decoration-danger decoration-wavy underline-offset-4">{characters.slice(word.start_char, word.end_char).join('')}</u></Fragment>]
      })
      return <div key={`${part.segment_id}:${i}`} className="flex min-w-0 flex-col gap-2 rounded-lg bg-muted p-3 text-meta" data-testid="asr-segment">
        <div className="flex flex-wrap items-center gap-2">
          {part.start_s != null && <span className="font-mono tabular-nums">{formatTime(part.start_s)}{part.end_s != null && ` – ${formatTime(part.end_s)}`}</span>}
          {onSeek && part.start_s != null && part.end_s != null && <Button size="sm" variant="link" onClick={() => onSeek(part.start_s!, true, part.end_s!)}><Play />Ascolta il tratto</Button>}
        </div>
        {part.confidence != null && <div className="flex flex-col gap-1">
          <div aria-hidden className="relative h-1.5 rounded-full bg-background">
            <span className="block h-full rounded-full bg-danger" style={{ width: `${Math.max(0, Math.min(1, part.confidence)) * 100}%` }} />
            {part.threshold != null && <span className="absolute -top-0.5 h-2.5 w-0.5 bg-foreground" style={{ left: `${Math.max(0, Math.min(1, part.threshold)) * 100}%` }} />}
          </div>
          <span className="text-muted-foreground">Confidenza {part.confidence.toLocaleString('it-IT', { maximumFractionDigits: 2 })}{part.threshold != null && ` · soglia della lezione ${part.threshold.toLocaleString('it-IT', { maximumFractionDigits: 2 })}`}</span>
        </div>}
        <p className="min-w-0 font-mono [overflow-wrap:anywhere]">{text}{characters.slice(cursor).join('')}</p>
      </div>
    })}
  </div>
}
