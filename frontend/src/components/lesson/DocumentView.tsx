import { useEffect, useRef } from 'react'

import type { Schemas } from '@/api/client'
import { activeUnit } from '@/lib/audio'
import { useLessonAudio } from './audio'

type Props = { document: Schemas['LessonDocument']; hasAudio: boolean }

/**
 * Documento della lezione: l'HTML arriva già sanificato dall'API, con le intestazioni delle
 * unità marcate (data-unit-id). I timecode cliccabili vengono dai secondi strutturati di
 * `sections`, non dal testo; il blocco dell'unità in ascolto si evidenzia.
 */
export function DocumentView({ document: doc, hasAudio }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const { currentTime, seek } = useLessonAudio()
  const current = hasAudio ? activeUnit(doc.sections, currentTime) : null

  // Pulsante timecode dentro ogni intestazione di unità.
  useEffect(() => {
    const root = ref.current
    if (!root) return
    for (const section of doc.sections) {
      const heading = root.querySelector<HTMLElement>(`[data-unit-id="${CSS.escape(section.unit_id)}"]`)
      if (!heading || section.start_seconds == null || heading.querySelector('.rt-timecode')) continue
      const button = window.document.createElement('button')
      button.type = 'button'
      button.className = 'rt-timecode'
      button.dataset.seconds = String(section.start_seconds)
      button.textContent = section.start_formatted ?? ''
      button.disabled = !hasAudio
      button.title = hasAudio ? `Ascolta da ${section.start_formatted}` : 'Audio non disponibile'
      button.setAttribute('aria-label', `Ascolta l'unità ${section.unit_id} da ${section.start_formatted}`)
      heading.append(' ', button)
    }
  }, [doc, hasAudio])

  // Evidenzia l'unità in ascolto (intestazione e blocchi fino alla prossima intestazione).
  useEffect(() => {
    const root = ref.current
    if (!root) return
    root.querySelectorAll('.rt-unit-active').forEach((el) => el.classList.remove('rt-unit-active'))
    if (!current) return
    let el: Element | null = root.querySelector(`[data-unit-id="${CSS.escape(current)}"]`)
    const first = el
    while (el && (el === first || !/^H[1-3]$/.test(el.tagName))) {
      el.classList.add('rt-unit-active')
      el = el.nextElementSibling
    }
  }, [current, doc])

  return (
    <article
      ref={ref}
      className="rt-document"
      data-testid="lesson-document"
      data-active-unit={current ?? ''}
      onClick={(e) => {
        const target = (e.target as HTMLElement).closest<HTMLElement>('[data-seconds]')
        if (target) seek(Number(target.dataset.seconds))
      }}
      dangerouslySetInnerHTML={{ __html: doc.html }}
    />
  )
}
