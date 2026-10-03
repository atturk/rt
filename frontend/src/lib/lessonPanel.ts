import { useState } from 'react'

/** Pannelli laterali della pagina della lezione (components/lesson/LessonPanel.tsx). */
export type PanelView = 'dettagli' | 'verifica'

export const PANEL_ID = 'lesson-side-panel'
const PANEL_KEY = 'rt-lesson-side-panel'

/** Pannello laterale aperto (Dettagli o Verifica) o chiuso: la scelta resta nel browser. Chiuso di default (il contenuto davanti). */
export function usePanelView(): [PanelView | null, (view: PanelView | null) => void] {
  const [view, setView] = useState<PanelView | null>(() => {
    try {
      const saved = localStorage.getItem(PANEL_KEY)
      return saved === 'dettagli' || saved === 'verifica' ? saved : null
    } catch {
      return null
    }
  })
  const update = (next: PanelView | null) => {
    setView(next)
    try {
      localStorage.setItem(PANEL_KEY, next ?? 'closed')
    } catch {
      /* archiviazione non disponibile: vale solo per questa pagina */
    }
  }
  return [view, update]
}
