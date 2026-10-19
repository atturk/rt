import { ArrowDownToLine, ListChecks, Sparkles, Trash2, Unlink, X } from 'lucide-react'

import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface MediaSelectionBarProps {
  selectedCount: number
  hasUsedSelected: boolean
  canInsertAtCursor: boolean
  onSelectAll: () => void
  onInsertAtCursor: () => void
  onAutoPlace: () => void
  onRemoveFromText: () => void
  onDelete: () => void
  canDelete: boolean
  onClearSelection: () => void
}

export function MediaSelectionBar({
  selectedCount,
  hasUsedSelected,
  canInsertAtCursor,
  onSelectAll,
  onInsertAtCursor,
  onAutoPlace,
  onRemoveFromText,
  onDelete,
  canDelete,
  onClearSelection,
}: MediaSelectionBarProps) {
  if (selectedCount === 0) return null

  const insertTooltip = canInsertAtCursor
    ? 'Inserisci al cursore'
    : 'Clicca nel testo dove vuoi le pagine'

  return (
    <div
      className="sticky bottom-3 z-20 flex items-center gap-1.5 rounded-xl bg-foreground px-3.5 py-1.5 text-background shadow-xl animate-in fade-in slide-in-from-bottom-2 duration-150"
      data-testid="media-selection-bar"
      role="toolbar"
      aria-label="Azioni media selezionati"
    >
      <span className="flex-1 text-meta font-medium tabular-nums text-background select-none">
        {selectedCount} {selectedCount === 1 ? 'selezionata' : 'selezionate'}
      </span>

      {/* Seleziona tutte */}
      <Tooltip content="Seleziona tutte (⌘A)" side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label="Seleziona tutte (⌘A)"
            className="flex size-8 items-center justify-center rounded-lg text-background hover:bg-background/20 cursor-pointer transition-colors"
            {...trigger}
            onClick={onSelectAll}
          >
            <ListChecks className="size-4.5" aria-hidden />
          </button>
        )}
      </Tooltip>

      {/* Inserisci al cursore */}
      <Tooltip content={insertTooltip} side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label="Inserisci al cursore"
            disabled={!canInsertAtCursor}
            className={cn(
              'flex size-8 items-center justify-center rounded-lg cursor-pointer transition-colors',
              canInsertAtCursor
                ? 'bg-accent text-accent-foreground hover:bg-accent/90'
                : 'text-background opacity-35 cursor-default',
            )}
            {...trigger}
            onClick={canInsertAtCursor ? onInsertAtCursor : undefined}
          >
            <ArrowDownToLine className="size-4.5" aria-hidden />
          </button>
        )}
      </Tooltip>

      {/* Colloca in automatico */}
      <Tooltip content="Colloca in automatico le selezionate" side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label="Colloca in automatico le selezionate"
            className="flex size-8 items-center justify-center rounded-lg text-background hover:bg-background/20 cursor-pointer transition-colors"
            {...trigger}
            onClick={onAutoPlace}
          >
            <Sparkles className="size-4.5" aria-hidden />
          </button>
        )}
      </Tooltip>

      {/* Togli dal testo */}
      <Tooltip content="Togli dal testo (resta nei media)" side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label="Togli dal testo (resta nei media)"
            disabled={!hasUsedSelected}
            className={cn(
              'flex size-8 items-center justify-center rounded-lg transition-colors',
              hasUsedSelected
                ? 'text-background hover:bg-background/20 cursor-pointer'
                : 'text-background opacity-35 cursor-default',
            )}
            {...trigger}
            onClick={hasUsedSelected ? onRemoveFromText : undefined}
          >
            <Unlink className="size-4.5" aria-hidden />
          </button>
        )}
      </Tooltip>

      {/* Elimina */}
      <Tooltip content={canDelete ? 'Elimina dalla lezione' : 'Elimina dalla lezione: le pagine dei materiali si tolgono con la fonte'} side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label="Elimina dalla lezione"
            aria-disabled={canDelete ? undefined : true}
            className={cn(
              'flex size-8 items-center justify-center rounded-lg transition-colors',
              canDelete
                ? 'text-background hover:bg-background/20 cursor-pointer'
                : 'text-background opacity-35 cursor-default',
            )}
            {...trigger}
            onClick={canDelete ? onDelete : undefined}
          >
            <Trash2 className="size-4.5" aria-hidden />
          </button>
        )}
      </Tooltip>

      {/* Annulla la selezione */}
      <Tooltip content="Annulla la selezione" side="top">
        {(trigger) => (
          <button
            type="button"
            aria-label="Annulla la selezione"
            className="flex size-8 items-center justify-center rounded-lg text-background hover:bg-background/20 cursor-pointer transition-colors"
            {...trigger}
            onClick={onClearSelection}
          >
            <X className="size-4.5" aria-hidden />
          </button>
        )}
      </Tooltip>
    </div>
  )
}
