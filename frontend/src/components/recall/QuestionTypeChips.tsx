import { Sparkles } from 'lucide-react'
import type { RecallType } from '@/api/recall'
import { Chip } from '@/components/ui/chip'
import { Tooltip } from '@/components/ui/tooltip'
import { QUESTION_TYPE_LABELS } from '@/lib/questionTypes'

export function QuestionTypeChips({ value, onChange, suggested, hint = 'Consigliato da Jev', unit = false, disabled = false }: {
  value: RecallType; onChange: (type: RecallType) => void; suggested?: RecallType | null
  hint?: string; unit?: boolean; disabled?: boolean
}) {
  return <div role="group" aria-label="Tipo di domanda" className="flex flex-wrap gap-1.5">
    {(Object.keys(QUESTION_TYPE_LABELS) as RecallType[]).filter(type => !unit || type !== 'vasta').map(type =>
      <Chip key={type} aria-label={QUESTION_TYPE_LABELS[type]} size="sm" active={value === type} aria-pressed={value === type} disabled={disabled} onClick={() => onChange(type)}>
        {QUESTION_TYPE_LABELS[type]}
        {suggested === type && <Tooltip content={hint}>{trigger => <span {...trigger} data-testid="question-type-advice" aria-label={hint}><Sparkles className="size-3.5 text-accent-foreground" aria-hidden /></span>}</Tooltip>}
      </Chip>)}
  </div>
}
