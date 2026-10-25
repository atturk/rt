import { X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

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

const getRemInPx = () => {
  if (typeof window === 'undefined') return 16
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
}

const getLimits = () => {
  const rem = getRemInPx()
  const minWidth = 24 * rem
  const maxWidth =
    typeof window !== 'undefined'
      ? Math.max(minWidth, Math.min(window.innerWidth * 0.6, window.innerWidth - 480))
      : minWidth
  return { minWidth, maxWidth }
}

const getInitialEnrichmentWidth = () => {
  const { minWidth, maxWidth } = getLimits()
  try {
    const saved = localStorage.getItem('rt.panel.enrichment.width')
    if (saved) {
      const num = parseFloat(saved)
      if (Number.isFinite(num)) {
        return Math.max(minWidth, Math.min(maxWidth, num))
      }
    }
  } catch {
    // Ignore storage errors
  }
  return minWidth
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
  const [enrichmentWidth, setEnrichmentWidth] = useState(getInitialEnrichmentWidth)
  const dragRef = useRef<{ x: number; width: number } | null>(null)

  const resize = useCallback((next: number) => {
    const { minWidth, maxWidth } = getLimits()
    const value = Math.max(minWidth, Math.min(maxWidth, next))
    setEnrichmentWidth(value)
    try {
      localStorage.setItem('rt.panel.enrichment.width', String(Math.round(value)))
    } catch {
      // Ignore storage errors
    }
  }, [])

  useEffect(() => {
    if (view === 'arricchimento') {
      document.documentElement.style.setProperty('--rt-panel-width', `${enrichmentWidth}px`)
    } else {
      document.documentElement.style.setProperty('--rt-panel-width', '24rem')
    }
    return () => {
      document.documentElement.style.setProperty('--rt-panel-width', '24rem')
    }
  }, [view, enrichmentWidth])

  useEffect(() => {
    if (view !== 'arricchimento') return
    const clampOnResize = () => {
      const { minWidth, maxWidth } = getLimits()
      setEnrichmentWidth((prev) => Math.max(minWidth, Math.min(maxWidth, prev)))
    }
    window.addEventListener('resize', clampOnResize)
    return () => window.removeEventListener('resize', clampOnResize)
  }, [view])

  useEffect(() => {
    const handleWindowPointerMove = (e: PointerEvent) => {
      if (dragRef.current) {
        resize(dragRef.current.width + (dragRef.current.x - e.clientX))
      }
    }
    const handleWindowPointerUp = () => {
      dragRef.current = null
    }
    window.addEventListener('pointermove', handleWindowPointerMove)
    window.addEventListener('pointerup', handleWindowPointerUp)
    return () => {
      window.removeEventListener('pointermove', handleWindowPointerMove)
      window.removeEventListener('pointerup', handleWindowPointerUp)
    }
  }, [resize])

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

  const limits = getLimits()

  return (
    <>
      {view === 'arricchimento' && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Larghezza del pannello"
          aria-valuenow={Math.round(enrichmentWidth)}
          aria-valuemin={Math.round(limits.minWidth)}
          aria-valuemax={Math.round(limits.maxWidth)}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
              e.preventDefault()
              resize(enrichmentWidth + (e.key === 'ArrowLeft' ? 32 : -32))
            }
          }}
          onDoubleClick={() => {
            const { minWidth } = getLimits()
            resize(minWidth)
          }}
          onPointerDown={(e) => {
            dragRef.current = { x: e.clientX, width: enrichmentWidth }
            if (e.currentTarget.setPointerCapture) {
              try {
                e.currentTarget.setPointerCapture(e.pointerId)
              } catch {
                // Ignore capture errors in tests
              }
            }
          }}
          onPointerMove={(e) => {
            if (dragRef.current) {
              resize(dragRef.current.width + (dragRef.current.x - e.clientX))
            }
          }}
          onPointerUp={(e) => {
            dragRef.current = null
            if (e.currentTarget.releasePointerCapture) {
              try {
                e.currentTarget.releasePointerCapture(e.pointerId)
              } catch {
                // Ignore
              }
            }
          }}
          onPointerCancel={() => {
            dragRef.current = null
          }}
          className="rt-panel-resize group hidden cursor-ew-resize items-center justify-center md:flex"
        >
          <div className="h-full w-[2px] transition-colors group-hover:bg-border group-focus-visible:bg-border" />
        </div>
      )}
      <aside
        id={PANEL_ID}
        aria-label={panelTitle}
        data-testid="lesson-panel"
        data-view={view}
        className="fixed z-10 flex flex-col overflow-y-auto bg-background px-4 pb-6 pt-3 rt-panel-container max-md:max-h-[80dvh] max-md:z-40 max-md:pb-[calc(80px+env(safe-area-inset-bottom))]"
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
    </>
  )
}

