import type { ReactNode } from 'react'

import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'

export function Section({ title, description, children, id }: { title: string; description?: ReactNode; children: ReactNode; id?: string }) {
  const headingId = id ? `${id}-titolo` : undefined
  return (
    <Card className="p-5" role="region" aria-labelledby={headingId} id={id}>
      <h2 id={headingId} className="text-base font-bold tracking-tight">
        {title}
      </h2>
      {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      <div className="mt-4 flex flex-col gap-3">{children}</div>
    </Card>
  )
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** "Impostata" / "Mancante": dello stato di un segreto l'API dice solo questo. */
export function SecretBadge({ set }: { set: boolean }) {
  return <Badge tone={set ? 'success' : 'warning'}>{set ? 'Impostata' : 'Mancante'}</Badge>
}

type MutationLike = { isError: boolean; isSuccess: boolean; error: unknown }

/** Esito dell'ultimo salvataggio: l'errore dell'API o la conferma. */
export function SaveFeedback({ mutation, success = 'Salvato.' }: { mutation: MutationLike; success?: string }) {
  if (mutation.isError) return <Alert tone="danger">{errorMessage(mutation.error)}</Alert>
  if (mutation.isSuccess) return <p role="status" className="text-xs text-success">{success}</p>
  return null
}

export function Checkbox({ id, label, checked, onChange, disabled }: { id: string; label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label htmlFor={id} className="inline-flex items-center gap-2 text-sm">
      <input id={id} type="checkbox" className="size-4 accent-current" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )
}
