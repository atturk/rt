import { Input } from '@/components/ui/input'
import { normalizeCountInput } from '@/lib/count'

/** Input per un numero intero piccolo: testo libero durante la digitazione (si può
 *  cancellare tutto, niente "03"), validato dal chiamante al salvataggio. */
export function CountInput({
  value,
  onChange,
  invalid = false,
  ...props
}: Omit<React.ComponentProps<'input'>, 'value' | 'onChange' | 'type'> & {
  value: string
  onChange: (value: string) => void
  invalid?: boolean
}) {
  return (
    <Input
      type="text"
      inputMode="numeric"
      autoComplete="off"
      value={value}
      aria-invalid={invalid || undefined}
      onChange={(e) => onChange(normalizeCountInput(e.target.value))}
      className={invalid ? 'border-danger' : undefined}
      {...props}
    />
  )
}
