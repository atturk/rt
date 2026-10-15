import { Merge, Split } from 'lucide-react'

import { IconButton } from '@/components/ui/icon-button'

/** Unisci gli audio: icona a due stati (unite in una registrazione / fonti separate). */
export function MergeAudioToggle({ merged, disabled, onChange }: {
  merged: boolean
  disabled?: boolean
  onChange: (merged: boolean) => void
}) {
  return (
    <IconButton
      label={merged
        ? "Le parti diventano un'unica registrazione: clic per tenerle separate"
        : 'Le parti restano fonti separate: clic per unirle'}
      icon={merged ? Merge : Split}
      side="top"
      active={merged}
      aria-pressed={merged}
      disabled={disabled}
      data-testid="merge-audio-toggle"
      onClick={() => onChange(!merged)}
    />
  )
}
