import { ChevronDown } from 'lucide-react'
import { Children, createContext, isValidElement, useContext, type ReactNode } from 'react'

import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { MenuButton } from '@/components/ui/menu'
import { cn } from '@/lib/utils'

const FieldLabel = createContext('Scelta')

export function Section({ title, children, id }: { title: string; description?: ReactNode; children: ReactNode; id?: string }) {
  const headingId = id ? `${id}-titolo` : undefined
  return (
    <section className="py-3" role="region" aria-labelledby={headingId} id={id}>
      <h2 id={headingId} className="text-meta font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </section>
  )
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <FieldLabel value={label}>
      {/* Etichetta accanto al controllo solo se c'è spazio: dentro le righe a più colonne va sopra. */}
      <div className="@container min-w-0 border-b py-3 last:border-0">
        <div className="grid items-start gap-2 @lg:grid-cols-[minmax(10rem,1fr)_minmax(0,2fr)]">
          <div><Label htmlFor={htmlFor} className="text-body">{label}</Label>{hint && <div className="mt-1 text-meta text-muted-foreground">{hint}</div>}</div>
          <div className="flex min-w-0 flex-col gap-1">{children}</div>
        </div>
      </div>
    </FieldLabel>
  )
}

type ChoiceProps = {
  id?: string; value?: string | number | readonly string[]; children: ReactNode; className?: string
  disabled?: boolean; required?: boolean; 'aria-label'?: string
  onChange?: (event: { target: { value: string } }) => void
}

/** Adatta le opzioni dei form al menu comune (focus, frecce, Esc e clic fuori). */
export function SettingsSelect({ id, value, children, className, disabled, onChange, 'aria-label': ariaLabel }: ChoiceProps) {
  const fieldLabel = useContext(FieldLabel)
  const label = ariaLabel ?? fieldLabel
  const options: { value: string; label: string; disabled?: boolean }[] = []
  function textValue(nodes: ReactNode): string {
    return Children.toArray(nodes).map(node => isValidElement<{ children?: ReactNode }>(node) ? textValue(node.props.children) : String(node)).join('')
  }
  function collect(nodes: ReactNode) {
    Children.forEach(nodes, child => {
      if (!isValidElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>(child)) return
      if (child.type === 'option') options.push({ value: String(child.props.value ?? ''), label: textValue(child.props.children), disabled: child.props.disabled })
      else collect(child.props.children)
    })
  }
  collect(children)
  const selected = options.find(o => o.value === String(value))
  return <div id={id} data-testid={id ?? label} data-value={value} className={cn('flex min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-body', className)}>
    <span className="min-w-0 break-words">{selected?.label ?? value}</span>
    {!disabled && <MenuButton label={label} icon={ChevronDown} sections={[{ label, items: options.filter(o => !o.disabled).map(o => ({
      label: o.label, checked: o.value === String(value), onSelect: () => onChange?.({ target: { value: o.value } }),
    })) }]} />}
  </div>
}

export function SecretBadge({ set }: { set: boolean }) {
  return <Badge tone={set ? 'success' : 'warning'}>{set ? 'Impostata' : 'Mancante'}</Badge>
}

type MutationLike = { isError: boolean; isSuccess: boolean; error: unknown }
export function SaveFeedback({ mutation, success = 'Salvato.' }: { mutation: MutationLike; success?: string }) {
  if (mutation.isError) return <Alert tone="danger">{errorMessage(mutation.error)}</Alert>
  if (mutation.isSuccess) return <p role="status" className="text-meta text-success">{success}</p>
  return null
}

export function Checkbox({ id, label, checked, onChange, disabled }: { id: string; label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return <div className="flex items-center justify-between gap-3 border-b py-3 last:border-0">
    <Label htmlFor={id} className="text-body">{label}</Label>
    <Button id={id} role="switch" aria-label={label} aria-checked={checked} disabled={disabled} variant={checked ? 'default' : 'outline'} size="sm" onClick={() => onChange(!checked)}>{checked ? 'Sì' : 'No'}</Button>
  </div>
}
