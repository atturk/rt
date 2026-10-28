import { ArrowDownToLine, Crop, ImageMinus, Info, ScanEye, Trash2, WandSparkles } from 'lucide-react'

import { IconButton } from '@/components/ui/icon-button'
import { SelectionBar } from '@/components/ui/selection-bar'

export interface MediaSelectionBarProps {
  selectedCount: number
  canDescribe: boolean
  canInsertAtCursor: boolean
  hasUsedSelected: boolean
  canDelete: boolean
  onDescribe: () => void
  onAutoPlace: () => void
  onInsertAtCursor: () => void
  onCrop: () => void
  onRemoveFromText: () => void
  onDelete: () => void
  onInfo?: () => void
  onSelectAll?: () => void
  onClearSelection?: () => void
}

export function MediaSelectionBar({
  selectedCount,
  canDescribe,
  canInsertAtCursor,
  hasUsedSelected,
  canDelete,
  onDescribe,
  onAutoPlace,
  onInsertAtCursor,
  onCrop,
  onRemoveFromText,
  onDelete,
  onInfo,
}: MediaSelectionBarProps) {
  if (selectedCount === 0) return null

  const countLabel = `${selectedCount} ${selectedCount === 1 ? 'scelto' : 'scelti'}`
  const canCrop = selectedCount === 1

  return (
    <div
      className="sticky bottom-3 z-20 flex justify-center animate-in fade-in slide-in-from-bottom-2 duration-150"
      data-testid="media-selection-bar"
    >
      <SelectionBar count={countLabel}>
        {onInfo && <IconButton
          icon={Info}
          label="Informazioni"
          unavailable={canCrop ? undefined : 'Solo con una immagine'}
          onClick={canCrop ? onInfo : undefined}
          data-testid="info-media-button"
        />}
        <IconButton
          icon={ScanEye}
          label="Descrivi"
          unavailable={canDescribe ? undefined : 'Tutte le immagini selezionate sono già descritte'}
          onClick={canDescribe ? onDescribe : undefined}
          data-testid="describe-media-button"
        />
        <IconButton
          icon={WandSparkles}
          label="Posiziona"
          onClick={onAutoPlace}
          data-testid="autoplace-media-button"
        />
        <IconButton
          icon={ArrowDownToLine}
          label="Inserisci al cursore"
          unavailable={canInsertAtCursor ? undefined : 'Clicca nel testo dove vuoi le pagine'}
          onClick={canInsertAtCursor ? onInsertAtCursor : undefined}
          data-testid="insert-at-cursor-button"
        />
        <IconButton
          icon={Crop}
          label="Ritaglia"
          unavailable={canCrop ? undefined : 'Solo con una immagine'}
          onClick={canCrop ? onCrop : undefined}
          data-testid="crop-media-button"
        />
        <IconButton
          icon={ImageMinus}
          label="Togli dal testo"
          unavailable={hasUsedSelected ? undefined : 'Nessuna immagine selezionata è nel testo'}
          onClick={hasUsedSelected ? onRemoveFromText : undefined}
          data-testid="remove-from-text-button"
        />
        <IconButton
          icon={Trash2}
          label="Elimina dalla lezione"
          className="text-danger hover:text-danger"
          unavailable={canDelete ? undefined : 'Le pagine dei materiali si tolgono con la fonte'}
          onClick={canDelete ? onDelete : undefined}
          data-testid="delete-media-button"
        />
      </SelectionBar>
    </div>
  )
}
