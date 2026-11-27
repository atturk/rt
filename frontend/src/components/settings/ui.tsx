import { ChevronDown, ChevronRight, Info, Loader2 } from 'lucide-react'
import {
  Children,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { MenuButton } from '@/components/ui/menu'
import { Switch } from '@/components/ui/switch'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const FieldLabel = createContext('Scelta')

/**
 * Contenitore di una pagina delle Impostazioni: titolo sezione, riga di descrizione e gruppi
 * distanziati con larghezza massima leggibile (`max-w-3xl`, `gap-8`).
 */
export function SettingsPage({
  title,
  description,
  children,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex max-w-3xl flex-col gap-8', className)}>
      <header className="flex flex-col gap-1">
        <h2 className="hidden text-heading font-semibold tracking-tight md:block">{title}</h2>
        {description && <p className="text-body text-muted-foreground">{description}</p>}
      </header>
      {children}
    </div>
  )
}

/**
 * Gruppo "a lista inserita": titolo piccolo in sentence case sopra un riquadro `bg-card`
 * con separatori interni `divide-y` e nessun `overflow-hidden` (così i portali restano liberi).
 */
export function SettingsGroup({
  id,
  title,
  description,
  footer,
  children,
  className,
  cardClassName,
  headerAction,
}: {
  id?: string
  title?: ReactNode
  description?: ReactNode
  footer?: ReactNode
  children: ReactNode
  className?: string
  cardClassName?: string
  headerAction?: ReactNode
}) {
  const autoId = useId()
  const headingId = title ? (id ? `${id}-titolo` : `${autoId}-titolo`) : undefined
  return (
    <section
      id={id}
      role={title ? 'region' : undefined}
      aria-labelledby={headingId}
      className={cn('flex min-w-0 flex-col gap-2', className)}
    >
      {(title || description || headerAction) && (
        <div className="flex items-end justify-between gap-3 px-1">
          <div className="flex min-w-0 flex-col gap-0.5">
            {title && (
              <h3 id={headingId} className="text-meta font-medium text-muted-foreground">
                {title}
              </h3>
            )}
            {description && <p className="text-meta text-muted-foreground">{description}</p>}
          </div>
          {headerAction}
        </div>
      )}
      <div className={cn('min-w-0 divide-y divide-border/60 rounded-lg border bg-card', cardClassName)}>
        {children}
      </div>
      {footer && <p className="px-1 text-meta text-muted-foreground">{footer}</p>}
    </section>
  )
}

export type AutoSaveState = {
  status: 'idle' | 'saving' | 'saved' | 'error'
  error: string | null
  retry: () => void
}

/**
 * Mostra lo stato discreto di un salvataggio automatico dentro la riga:
 * spinner mentre salva, «Salvato» muted per 1,5 s, errore in rosso con «Riprova».
 */
export function AutoSaveStatus({
  status,
  error,
  onRetry,
  className,
}: {
  status: AutoSaveState['status']
  error: string | null
  onRetry?: () => void
  className?: string
}) {
  if (status === 'idle') return null
  if (status === 'saving') {
    return (
      <span role="status" className={cn('inline-flex items-center gap-1 text-meta text-muted-foreground', className)}>
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        <span className="sr-only">Salvataggio…</span>
      </span>
    )
  }
  if (status === 'saved') {
    return (
      <span role="status" className={cn('text-meta text-muted-foreground', className)}>
        Salvato
      </span>
    )
  }
  return (
    <span role="alert" className={cn('inline-flex flex-wrap items-center gap-1.5 text-meta text-danger', className)}>
      <span>{error ?? 'Errore durante il salvataggio.'}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer font-medium underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
        >
          Riprova
        </button>
      )}
    </span>
  )
}

/** Etichetta con (i): l'icona resta attaccata all'ultima parola, mai da sola a capo. */
export function LabelWithInfo({ label, info, infoLabel }: { label: ReactNode; info?: ReactNode; infoLabel: string }) {
  if (!info) return <>{label}</>
  // Spazio unificatore: la (i) va a capo insieme all'ultima parola, mai da sola.
  return <>{label}{'\u00a0'}<SettingsInfoButton label={infoLabel} info={info} className="align-middle" /></>
}

/**
 * Pulsante discreto (i) accanto all'etichetta che apre il Tooltip portale di RT.
 */
export function SettingsInfoButton({ label, info, className }: { label: string; info: ReactNode; className?: string }) {
  return (
    <Tooltip content={info} openOnClick>
      {(trigger) => (
        <button
          type="button"
          aria-label={`Informazioni su ${label}`}
          className={cn(
            'inline-flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            className,
          )}
          {...trigger}
        >
          <Info className="size-3.5" aria-hidden />
        </button>
      )}
    </Tooltip>
  )
}

/**
 * Riga standard delle Impostazioni: griglia `1fr auto`, descrizione su una riga,
 * eventuale icona `info` col tooltip portale, stato discreto di salvataggio e supporto `stacked`
 * (o stretto via `@container`).
 */
export function SettingsRow({
  label,
  infoLabel,
  description,
  info,
  control,
  htmlFor,
  stacked = false,
  compactControl = false,
  status,
  className,
  testId,
}: {
  label: ReactNode
  infoLabel?: string
  description?: ReactNode
  info?: ReactNode
  control: ReactNode
  htmlFor?: string
  stacked?: boolean
  compactControl?: boolean
  status?: AutoSaveState
  className?: string
  testId?: string
}) {
  const labelText = infoLabel ?? (typeof label === 'string' ? label : 'questa impostazione')
  return (
    <FieldLabel value={labelText}>
      <div className={cn('@container min-w-0 px-4 py-3', className)} data-testid={testId}>
        <div
          className={cn(
            'grid min-h-6 gap-x-4 gap-y-2',
            stacked
              ? 'grid-cols-1 items-start'
              : compactControl
                ? 'grid-cols-[minmax(0,1fr)_auto] items-center'
                : 'grid-cols-1 items-start @sm:grid-cols-[minmax(0,1fr)_auto] @sm:items-center',
          )}
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <div className="min-w-0">
              {htmlFor ? (
                <>
                  <label htmlFor={htmlFor} className="text-body font-medium text-foreground">
                    {label}
                  </label>
                  {info && (
                    <>
                      {'\u00a0'}
                      <SettingsInfoButton label={labelText} info={info} className="align-middle" />
                    </>
                  )}
                </>
              ) : (
                <span className="text-body font-medium text-foreground">
                  <LabelWithInfo label={label} info={info} infoLabel={labelText} />
                </span>
              )}
            </div>
            {description && <p className="text-meta text-muted-foreground">{description}</p>}
          </div>
          <div
            className={cn(
              'flex min-w-0 max-w-full flex-col gap-1',
              stacked ? 'w-full' : compactControl ? 'items-end' : 'w-full @sm:w-auto @sm:items-end',
            )}
          >
            {control}
          </div>
        </div>
        {status && status.status !== 'idle' && (
          <div className="mt-1.5 flex justify-end">
            <AutoSaveStatus status={status.status} error={status.error} onRetry={status.retry} />
          </div>
        )}
      </div>
    </FieldLabel>
  )
}

/**
 * Riga con interruttore booleano (`components/ui/switch.tsx`).
 */
export function SettingsSwitch({
  id,
  label,
  description,
  info,
  checked,
  onChange,
  disabled,
  status,
  className,
  testId,
}: {
  id: string
  label: string
  description?: ReactNode
  info?: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  status?: AutoSaveState
  className?: string
  testId?: string
}) {
  return (
    <SettingsRow
      label={label}
      htmlFor={id}
      description={description}
      info={info}
      compactControl
      status={status}
      className={className}
      testId={testId}
      control={<Switch id={id} label={label} checked={checked} onChange={onChange} disabled={disabled} />}
    />
  )
}

type ChoiceProps = {
  id?: string
  value?: string | number | readonly string[]
  children: ReactNode
  className?: string
  disabled?: boolean
  required?: boolean
  'aria-label'?: string
  onChange?: (event: { target: { value: string } }) => void
}

/** Selettore coerente con il menu comune di RT (focus, frecce, Esc e clic fuori). */
export function SettingsSelect({
  id,
  value,
  children,
  className,
  disabled,
  onChange,
  'aria-label': ariaLabel,
}: ChoiceProps) {
  const fieldLabel = useContext(FieldLabel)
  const label = ariaLabel ?? fieldLabel
  const options: { value: string; label: string; disabled?: boolean }[] = []
  function textValue(nodes: ReactNode): string {
    return Children.toArray(nodes)
      .map((node) => (isValidElement<{ children?: ReactNode }>(node) ? textValue(node.props.children) : String(node)))
      .join('')
  }
  function collect(nodes: ReactNode) {
    Children.forEach(nodes, (child) => {
      if (!isValidElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>(child)) return
      if (child.type === 'option') {
        options.push({
          value: String(child.props.value ?? ''),
          label: textValue(child.props.children),
          disabled: child.props.disabled,
        })
      } else {
        collect(child.props.children)
      }
    })
  }
  collect(children)
  const selected = options.find((o) => o.value === String(value))
  return (
    <div
      id={id}
      data-testid={id ?? label}
      data-value={value}
      className={cn(
        'flex h-9 min-h-9 min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-card pl-3 pr-1 text-body',
        className,
      )}
    >
      <span className="min-w-0 truncate whitespace-nowrap">{selected?.label ?? value}</span>
      {!disabled && (
        <MenuButton
          label={label}
          icon={ChevronDown}
          buttonClassName="size-7 min-h-7 min-w-7"
          sections={[
            {
              label,
              items: options
                .filter((o) => !o.disabled)
                .map((o) => ({
                  label: o.label,
                  checked: o.value === String(value),
                  onSelect: () => onChange?.({ target: { value: o.value } }),
                })),
            },
          ]}
        />
      )}
    </div>
  )
}

/**
 * Riga espandibile dentro un `SettingsGroup`: chevron che ruota di 90°, testo principale a
 * sinistra e riepilogo muted a destra. Sostituisce `<details>` e frecce nude.
 */
export function SettingsDisclosure({
  id,
  label,
  summary,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  children,
  className,
}: {
  id?: string
  label: ReactNode
  summary?: ReactNode
  defaultOpen?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children: ReactNode
  className?: string
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen)
  const isOpen = controlledOpen ?? uncontrolledOpen
  const contentId = useId()
  const rootRef = useRef<HTMLDivElement>(null)

  const setOpen = useCallback(
    (next: boolean) => {
      if (controlledOpen === undefined) setUncontrolledOpen(next)
      onOpenChange?.(next)
    },
    [controlledOpen, onOpenChange],
  )

  useEffect(() => {
    const onReveal = (event: Event) => {
      const targetId = (event as CustomEvent<{ id?: string }>).detail?.id
      if (!targetId || !rootRef.current) return
      if (id === targetId || rootRef.current.querySelector(`#${CSS.escape(targetId)}`)) {
        setOpen(true)
      }
    }
    window.addEventListener('rt-settings-reveal', onReveal)
    return () => window.removeEventListener('rt-settings-reveal', onReveal)
  }, [id, setOpen])

  return (
    <div ref={rootRef} id={id} className={cn('min-w-0', className)}>
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls={contentId}
        onClick={() => setOpen(!isOpen)}
        className="flex min-h-12 w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="flex min-w-0 items-center gap-2">
          <ChevronRight
            className={cn('size-4 shrink-0 text-muted-foreground transition-transform duration-150', isOpen && 'rotate-90')}
            aria-hidden
          />
          <span className="min-w-0 truncate text-body font-medium text-foreground">{label}</span>
        </span>
        {summary && <span className="shrink-0 text-meta text-muted-foreground">{summary}</span>}
      </button>
      {isOpen && (
        <div id={contentId} className="border-t border-border/60 px-4 py-3">
          {children}
        </div>
      )}
    </div>
  )
}

export type SettingsMatrixColumnGroup = {
  id: string
  label: string
  columns: { key: string; label: string }[]
}

export type SettingsMatrixRow = {
  id: string
  label: string
  testId?: string
  cells: Record<string, ReactNode>
}

/**
 * Tabella compatta di scelte a icone (es. Fonti): intestazione delle colonne UNA sola volta in
 * alto, righe con etichetta a sinistra e gruppi di icone allineati a destra.
 */
export function SettingsMatrix({
  columnGroups,
  rows,
  rowHeaderLabel = 'Tipo',
}: {
  columnGroups: SettingsMatrixColumnGroup[]
  rows: SettingsMatrixRow[]
  rowHeaderLabel?: string
}) {
  return (
    <div className="divide-y divide-border/60">
      <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2 bg-muted/30 px-4 py-2.5 text-meta text-muted-foreground">
        <span className="min-w-20 font-medium">{rowHeaderLabel}</span>
        <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
          {columnGroups.map((group) => (
            <div key={group.id} className="flex flex-col items-center gap-1">
              <span className="font-medium text-foreground/80">{group.label}</span>
              <div
                className="grid w-[9.75rem] text-center text-[11px] leading-tight text-muted-foreground sm:w-[11.25rem]"
                style={{ gridTemplateColumns: `repeat(${group.columns.length}, minmax(0, 1fr))` }}
              >
                {group.columns.map((col) => (
                  <span key={col.key} className="break-words px-0.5">
                    {col.label}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      {rows.map((row) => (
        <div
          key={row.id}
          data-testid={row.testId}
          className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2.5"
        >
          <span className="min-w-20 text-body font-medium text-foreground">{row.label}</span>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {columnGroups.map((group) => (
              <div key={group.id}>{row.cells[group.id]}</div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
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
