import { Sparkles } from 'lucide-react'
import { BASE_RECALL_TYPES, useRecallTypes, type RecallTypeInfo, type RecallGenerateType } from '@/api/recall'
import { Chip } from '@/components/ui/chip'
import { Tooltip } from '@/components/ui/tooltip'
import { TypeIcon } from './TypeIcon'

export function QuestionTypeChips({
  value,
  onChange,
  suggested,
  hint = 'Consigliato da Jev',
  unit = false,
  disabled = false,
  lessonId,
  types,
  withConsigliato = false,
  groupLabel = 'Tipo di domanda',
}: {
  value: RecallGenerateType
  onChange: (type: RecallGenerateType) => void
  suggested?: string | null
  hint?: string
  unit?: boolean
  disabled?: boolean
  lessonId?: number
  types?: RecallTypeInfo[]
  withConsigliato?: boolean
  groupLabel?: string
}) {
  const registry = useRecallTypes(lessonId)
  return (
    <div role="group" aria-label={groupLabel} className="flex flex-wrap items-center gap-1.5">
      {withConsigliato && !unit && (
        <>
          <Chip
            aria-label="Consigliato"
            size="sm"
            active={value === 'consigliato'}
            aria-pressed={value === 'consigliato'}
            disabled={disabled}
            onClick={() => onChange('consigliato')}
          >
            <Sparkles className="size-3.5 text-accent-foreground" aria-hidden />
            Consigliato
          </Chip>
          <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
        </>
      )}
      {(types ?? registry.data ?? BASE_RECALL_TYPES)
        .filter((type) => !unit || type.id !== 'vasta')
        .map((type) => {
          const unavailable = type.custom && !type.available && !unit
          const chip = (
            <Chip
              aria-label={type.nome}
              title={type.nome}
              size="sm"
              className="max-w-full"
              active={value === type.id}
              aria-pressed={value === type.id}
              disabled={disabled || unavailable}
              onClick={() => onChange(type.id)}
            >
              {type.custom && <TypeIcon name={type.icona} className="size-3.5 shrink-0" />}
              <span className="min-w-0 truncate">{type.nome}</span>
              {suggested === type.id && (
                <Tooltip content={hint}>
                  {(trigger) => (
                    <span {...trigger} data-testid="question-type-advice" aria-label={hint} className="shrink-0">
                      <Sparkles className="size-3.5 text-accent-foreground" aria-hidden />
                    </span>
                  )}
                </Tooltip>
              )}
            </Chip>
          )
          return unavailable ? (
            <Tooltip key={type.id} content="Nessuna unità">
              {(trigger) => <span {...trigger} className="flex min-w-0 max-w-full">{chip}</span>}
            </Tooltip>
          ) : (
            <span key={type.id} className="flex min-w-0 max-w-full">{chip}</span>
          )
        })}
    </div>
  )
}
