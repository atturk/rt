import { useEffect, useRef } from 'react'

import type { Schemas } from '@/api/client'
import { activeUnit } from '@/lib/audio'
import { withImageUrls } from '@/lib/images'
import { useLessonAudio } from './audio'

type Props = {
  document: Schemas['LessonDocument']
  hasAudio: boolean
  lessonId: number
  /** Passaggio da evidenziare (review) e unità in cui cercarlo. */
  highlightText?: string | null
  highlightUnit?: string | null
}

const norm = (s: string) => s.replace(/\s+/g, ' ').trim()

/** Elementi del blocco di un'unità: l'intestazione e quelli che seguono fino alla prossima. */
function unitBlock(root: HTMLElement, unitId: string): Element[] {
  const first = root.querySelector(`[data-unit-id="${CSS.escape(unitId)}"]`)
  const out: Element[] = []
  let el: Element | null = first
  while (el && (el === first || !/^H[1-3]$/.test(el.tagName))) {
    out.push(el)
    el = el.nextElementSibling
  }
  return out
}

/** Avvolge in <mark> la prima occorrenza del testo (o del suo inizio) dentro gli elementi. */
function markText(elements: Element[], text: string): HTMLElement | null {
  const needles = [norm(text), norm(text).slice(0, 80), norm(text).slice(0, 40)].filter((n) => n.length >= 8)
  for (const needle of needles) {
    for (const el of elements) {
      const walker = window.document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
        const value = node.data.replace(/\s+/g, ' ')
        const at = value.indexOf(needle)
        if (at < 0 || value.length !== node.data.length) continue
        const range = window.document.createRange()
        range.setStart(node, at)
        range.setEnd(node, at + needle.length)
        const mark = window.document.createElement('mark')
        mark.className = 'rt-claim'
        range.surroundContents(mark)
        return mark
      }
    }
  }
  return null
}

/**
 * Documento della lezione: l'HTML arriva già sanificato dall'API, con le intestazioni delle
 * unità marcate (data-unit-id). I timecode cliccabili vengono dai secondi strutturati di
 * `sections`, non dal testo; il blocco dell'unità in ascolto si evidenzia.
 */
export function DocumentView({ document: doc, hasAudio, lessonId, highlightText, highlightUnit }: Props) {
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

  // Passaggio dell'issue selezionata: evidenziato e portato in vista.
  useEffect(() => {
    const root = ref.current
    if (!root) return
    root.querySelectorAll('mark.rt-claim').forEach((m) => m.replaceWith(...Array.from(m.childNodes)))
    root.querySelectorAll('.rt-claim-unit').forEach((el) => el.classList.remove('rt-claim-unit'))
    root.normalize()
    if (!highlightText) return
    const block = highlightUnit ? unitBlock(root, highlightUnit) : []
    const target = markText(block.length ? block : [root], highlightText) ?? markText([root], highlightText)
    if (!target) block.forEach((el) => el.classList.add('rt-claim-unit'))
    const visible = target ?? block[0]
    visible?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }, [highlightText, highlightUnit, doc])

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
      dangerouslySetInnerHTML={{ __html: withImageUrls(doc.html, lessonId) }}
    />
  )
}
