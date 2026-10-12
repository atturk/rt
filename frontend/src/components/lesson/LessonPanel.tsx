import { X } from 'lucide-react'
import { useEffect } from 'react'

import type { Schemas } from '@/api/client'
import { IconButton } from '@/components/ui/icon-button'
import { DetailsPanel } from './panels/DetailsPanel'
import { ReviewPanel } from './panels/ReviewPanel'
import { QuestionsPanel } from './panels/QuestionsPanel'
import { ClassifierPanel } from './panels/ClassifierPanel'
import { EnrichmentPanel } from './panels/EnrichmentPanel'
import { StudyNotesPanel } from './panels/StudyNotesPanel'
import { PANEL_ID, type PanelView } from '@/lib/lessonPanel'

type Section = Schemas['DocumentSection']

const TITLES: Record<PanelView, string> = {
  dettagli: 'Dettagli',
  verifica: 'Verifica con LLM',
  domande: 'Domande',
  classificatore: 'Classificatore',
  arricchimento: 'Arricchimento',
  note: 'Verifiche e domande',
}

/** Contenitore comune: un pannello per volta, chiusura con X o Esc. */
export function LessonPanel({
  view,
  lesson,
  sections,
  editingDocument,
  beforeReviewAction,
  onClose,
  onSwitchView,
  selectionContext,
  onClearSelection,
  selectedNoteId,
  onSelectNote,
}: {
  view: PanelView
  lesson: Schemas['LessonDetail']
  sections: Section[]
  editingDocument: boolean
  beforeReviewAction?: () => Promise<void>
  onClose: () => void
  onSwitchView?: (view: PanelView) => void
  selectionContext?: { units?: string[]; text?: string } | null
  onClearSelection?: () => void
  selectedNoteId?: number | null
  onSelectNote?: (noteId: number | null) => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !document.querySelector('dialog[open]')) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const isSelectionDomande = view === 'domande' && Boolean(selectionContext?.units && selectionContext.units.length > 0)
  const unitsText = selectionContext?.units
    ? selectionContext.units.length === 2
      ? `${selectionContext.units[0]} e ${selectionContext.units[1]}`
      : selectionContext.units.join(', ')
    : ''
  const panelTitle = isSelectionDomande ? `Domande unità ${unitsText}` : TITLES[view]

  return (
    <aside
      id={PANEL_ID}
      aria-label={panelTitle}
      data-testid="lesson-panel"
      data-view={view}
      className="fixed z-30 flex flex-col overflow-y-auto bg-background px-4 pb-6 pt-3 rt-panel-container max-md:max-h-[80dvh] max-md:z-40 max-md:pb-[calc(80px+env(safe-area-inset-bottom))]"
    >
      <div className="mb-3 flex items-center gap-2">
        <h2 className="min-w-0 flex-1 text-body font-semibold">{panelTitle}</h2>
        <IconButton label="Chiudi il pannello" icon={X} onClick={onClose} className="-mr-2" />
      </div>
      <div key={view} className="rt-panel-body-switch flex flex-col flex-1">
        {view === 'dettagli' && <DetailsPanel lesson={lesson} sections={sections} editingDocument={editingDocument} />}
        {view === 'verifica' && <ReviewPanel lesson={lesson} beforeAction={beforeReviewAction} />}
        {view === 'domande' && (
          <QuestionsPanel
            lessonId={lesson.id}
            selectedUnits={selectionContext?.units}
            selectedText={selectionContext?.text}
            onSwitchToClassifier={() => onSwitchView?.('classificatore')}
            onClearSelection={onClearSelection}
          />
        )}
        {view === 'classificatore' && <ClassifierPanel lessonId={lesson.id} />}
        {view === 'arricchimento' && <EnrichmentPanel lessonId={lesson.id} />}
        {view === 'note' && (
          <StudyNotesPanel
            lessonId={lesson.id}
            selectedNoteId={selectedNoteId}
            onSelectNote={onSelectNote}
          />
        )}
      </div>
    </aside>
  )
}

