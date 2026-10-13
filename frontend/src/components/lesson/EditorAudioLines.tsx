import type { EditorView } from '@codemirror/view'

import type { Schemas } from '@/api/client'
import { unitSpeechProgress } from '@/lib/audio'
import { cn } from '@/lib/utils'
import { useLessonAudio } from './audio'
import { unitRanges } from './lessonUnits'

/**
 * AU1 (wireframe RT-audio-linea.html) nel testo della lezione: linea di 2 px a destra dell'unità che
 * si ascolta, che avanza contando solo il parlato; le unità già ascoltate tengono una traccia
 * leggera. Le posizioni vengono da CodeMirror (lineBlockAt), valide anche per le righe fuori vista;
 * l'editor rinnova il componente a ogni suo aggiornamento, anche di geometria.
 * Va dentro un contenitore `relative` che ha in cima l'editor.
 */
export function EditorAudioLines({ view, sections }: { view: EditorView | null; sections: Schemas['DocumentSection'][] }) {
  const { currentTime } = useLessonAudio()
  if (!view || sections.length === 0) return null
  const offset = view.documentTop - view.dom.getBoundingClientRect().top
  const units = new Map(unitRanges(view.state).map((u) => [u.id, u]))
  return (
    <div className="pointer-events-none absolute inset-0 select-none" aria-hidden="true" data-testid="audio-speech-lines">
      {sections.map((section) => {
        const unit = units.get(section.unit_id)
        if (!unit) return null
        const { cur, done, percent } = unitSpeechProgress(section, currentTime)
        if (!cur && !done) return null
        const top = view.lineBlockAt(unit.from).top + offset
        const bottom = view.lineBlockAt(unit.to).bottom + offset
        return (
          <div
            key={section.unit_id}
            className={cn('rt-audio-line', cur && 'cur', done && 'done')}
            style={{ top: `${top}px`, height: `${Math.max(16, bottom - top)}px` }}
            data-testid={`audio-line-${section.unit_id}`}
            data-active={cur ? 'true' : 'false'}
            data-done={done ? 'true' : 'false'}
          >
            <i style={{ height: done ? '100%' : `${percent}%` }} />
          </div>
        )
      })}
    </div>
  )
}
