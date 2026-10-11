import { Sparkles } from 'lucide-react'
import { BASE_RECALL_TYPES, useRecallTypes, type RecallType, type RecallTypeInfo } from '@/api/recall'
import { Chip } from '@/components/ui/chip'
import { Tooltip } from '@/components/ui/tooltip'
import { TypeIcon } from './TypeIcon'

export function QuestionTypeChips({ value, onChange, suggested, hint = 'Consigliato da Jev', unit = false, disabled = false, lessonId, types }: {
  value: RecallType; onChange: (type: RecallType) => void; suggested?: RecallType | null
  hint?: string; unit?: boolean; disabled?: boolean; lessonId?: number; types?: RecallTypeInfo[]
}) {
  const registry = useRecallTypes(lessonId)
  return <div role="group" aria-label="Tipo di domanda" className="flex flex-wrap gap-1.5">
    {(types ?? registry.data ?? BASE_RECALL_TYPES).filter(type => !unit || type.id !== 'vasta').map(type => {
      const unavailable = type.custom && !type.available && !unit
      const chip = <Chip aria-label={type.nome} size="sm" active={value === type.id} aria-pressed={value === type.id} disabled={disabled || unavailable} onClick={() => onChange(type.id)}>
        {type.custom && <TypeIcon name={type.icona} className="size-3.5" />}{type.nome}
        {suggested === type.id && <Tooltip content={hint}>{trigger => <span {...trigger} data-testid="question-type-advice" aria-label={hint}><Sparkles className="size-3.5 text-accent-foreground" aria-hidden /></span>}</Tooltip>}
      </Chip>
      return unavailable ? <Tooltip key={type.id} content="Nessuna unità">{trigger => <span {...trigger}>{chip}</span>}</Tooltip> : <span key={type.id}>{chip}</span>
    })}
  </div>
}
