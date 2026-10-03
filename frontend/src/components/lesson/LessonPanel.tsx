import { X } from 'lucide-react'
import { useEffect } from 'react'

import type { Schemas } from '@/api/client'
import { IconButton } from '@/components/ui/icon-button'
import { DetailsPanel } from './panels/DetailsPanel'
import { ReviewPanel } from './panels/ReviewPanel'
import { QuestionsPanel } from './panels/QuestionsPanel'
import { ClassifierPanel } from './panels/ClassifierPanel'
import { EnrichmentPanel } from './panels/EnrichmentPanel'
import { PANEL_ID, type PanelView } from '@/lib/lessonPanel'

type Section = Schemas['DocumentSection']

const TITLES: Record<PanelView, string> = { dettagli: 'Dettagli', verifica: 'Verifica con LLM', domande: 'Domande', classificatore: 'Classificatore', arricchimento: 'Arricchimento' }

/** Contenitore comune: un pannello per volta, chiusura con X o Esc. */
export function LessonPanel({ view, lesson, sections, editingDocument, beforeReviewAction, reviewMarkdown, onClose }: {
  view: PanelView
  lesson: Schemas['LessonDetail']
  sections: Section[]
  editingDocument: boolean
  reviewMarkdown?: string
  beforeReviewAction?: () => Promise<void>
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !document.querySelector('dialog[open]')) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <aside
      id={PANEL_ID}
      aria-label={TITLES[view]}
      data-testid="lesson-panel"
      data-view={view}
      className="fixed bottom-0 right-0 top-(--header-height) z-10 flex w-[min(24rem,100vw)] flex-col overflow-y-auto border-l bg-background px-4 pb-6 pt-3 shadow-panel max-md:top-auto max-md:max-h-[80dvh] max-md:rounded-t-xl max-md:border-t max-md:z-40 max-md:pb-[calc(80px+env(safe-area-inset-bottom))]"
    >
      <div className="mb-3 flex items-center gap-2">
        <h2 className="min-w-0 flex-1 text-body font-semibold">{TITLES[view]}</h2>
        <IconButton label="Chiudi il pannello" icon={X} onClick={onClose} className="-mr-2" />
      </div>
      {view === 'dettagli' && <DetailsPanel lesson={lesson} sections={sections} editingDocument={editingDocument} />}
      {view === 'verifica' && <ReviewPanel lesson={lesson} beforeAction={beforeReviewAction} markdown={reviewMarkdown} />}
      {view === 'domande' && <QuestionsPanel />}
      {view === 'classificatore' && <ClassifierPanel />}
      {view === 'arricchimento' && <EnrichmentPanel />}
    </aside>
  )
}

