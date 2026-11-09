import { Brackets, Files, FileText, Image, Shield } from 'lucide-react'
import type { ReactNode, SVGProps } from 'react'

import { textOnly, type Extraction, type SourceOptions } from '@/api/archive'
import { IconButton } from '@/components/ui/icon-button'
import { EXTRACTIONS, USES, isImageName, pageRange, type Reasons, type Uso } from '@/lib/sourceDefaults'
import { cn } from '@/lib/utils'

const USE_HINTS: Record<Uso, string> = {
  guida: 'Guida: fonte principale',
  contesto: 'Contesto: arricchisce la fonte principale',
  integra: 'Integra: può aggiungere unità',
}

/** Gruppo di pulsanti a icona come il selettore della vista del calendario. */
export function Segmented({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div role="group" aria-label={label} className={cn('flex items-center gap-0.5 rounded-lg bg-muted p-0.5', className)}>
      {children}
    </div>
  )
}

export function ExtractOptions({ value, onChange, unavailable = {} }: { value: Extraction; onChange: (value: Extraction) => void; unavailable?: Reasons<Extraction> }) {
  return (
    <Segmented label="Estrai">
      {EXTRACTIONS.map(([key, icon, label]) => (
        <IconButton key={key} icon={icon} label={label} active={value === key} aria-pressed={value === key}
          unavailable={unavailable[key]} onClick={() => onChange(key)} />
      ))}
    </Segmented>
  )
}

export function UseOptions({ value, onChange, unavailable = {}, off }: { value: Uso; onChange: (value: Uso) => void; unavailable?: Reasons<Uso>; off?: string | null }) {
  return (
    <div className="flex items-center gap-2">
      <Segmented label="Uso">
        {USES.map(([key, icon]) => (
          <IconButton key={key} icon={icon} label={USE_HINTS[key]} active={!off && value === key} aria-pressed={!off && value === key}
            unavailable={off || unavailable[key]} onClick={() => onChange(key)} />
        ))}
      </Segmented>
      <span className="min-w-16 text-meta text-muted-foreground">{off ? '—' : USES.find(([key]) => key === value)?.[2]}</span>
    </div>
  )
}

export function PagesOptions({ value, total, onChange }: { value: string | number[] | null | undefined; total: number | null; onChange: (value: string | null) => void }) {
  const range = pageRange(value)
  const [from, to] = range ?? [1, total ?? 1]
  const set = (a: number, b: number) => onChange(`${a}-${b}`)
  return (
    <div className="flex items-center gap-2 text-meta">
      <Segmented label="Pagine">
        <IconButton icon={Files} label="Tutte le pagine" active={!range} aria-pressed={!range} onClick={() => onChange(null)} />
        <IconButton icon={Brackets} label="Intervallo di pagine" active={!!range} aria-pressed={!!range} onClick={() => set(from, to)} />
      </Segmented>
      {range && (
        <>
          <label className="flex items-center gap-1.5">Da
            <input aria-label="Da" type="number" min={1} max={total ?? undefined} value={from}
              onChange={(e) => set(Number(e.target.value) || 1, to)} className="h-9 w-16 rounded-md border bg-card px-2" />
          </label>
          <label className="flex items-center gap-1.5">A
            <input aria-label="A" type="number" min={from} max={total ?? undefined} value={to}
              onChange={(e) => set(from, Number(e.target.value) || from)} className="h-9 w-16 rounded-md border bg-card px-2" />
          </label>
        </>
      )}
    </div>
  )
}

function PdfIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
      <text x="12" y="17.5" textAnchor="middle" fontSize="6.5" fontWeight="700" fill="currentColor" stroke="none">PDF</text>
    </svg>
  )
}

/** Tre icone: PDF (e presentazioni), documento di testo, immagine. */
export function SourceFileIcon({ name, className }: { name: string; className?: string }) {
  if (isImageName(name)) return <Image className={className} aria-hidden />
  if (textOnly(name)) return <FileText className={className} aria-hidden />
  return <PdfIcon className={className} aria-hidden />
}

export type Affidabilita = 'alta' | 'normale' | 'bassa'

export function ReliabilityOptions({
  value = 'normale',
  onChange,
}: {
  value?: Affidabilita | null
  onChange: (value: Affidabilita) => void
}) {
  const current = value ?? 'normale'
  return (
    <div className="flex items-center gap-2">
      <Segmented label="Affidabilità">
        {(['alta', 'normale', 'bassa'] as const).map((key) => {
          const label = key === 'alta' ? 'Alta' : key === 'normale' ? 'Normale' : 'Bassa'
          const active = current === key
          return (
            <button
              key={key}
              type="button"
              aria-label={label}
              aria-pressed={active}
              onClick={() => onChange(key)}
              className={cn(
                'rounded-md px-2 py-1 text-meta font-medium transition-colors cursor-pointer',
                active ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {label}
            </button>
          )
        })}
      </Segmented>
      <span className="min-w-16 text-meta text-muted-foreground">
        {current === 'alta' ? 'Alta' : current === 'normale' ? 'Normale' : 'Bassa'}
      </span>
    </div>
  )
}

/** Modalità e uso in piccolo sulla miniatura. */
export function SourceBadges({ options }: { options: SourceOptions }) {
  const Mode = EXTRACTIONS.find(([key]) => key === (options.estrai ?? 'immagini'))?.[1]
  const Use = options.estrai === 'solo_immagini' ? null : USES.find(([key]) => key === (options.uso ?? 'contesto'))?.[1]
  const affidabilita = options.affidabilita
  return (
    <span className="absolute right-1 bottom-1 flex gap-0.5 text-muted-foreground [&_svg]:size-3" aria-hidden={!affidabilita ? true : undefined}>
      {Mode && <Mode />}
      {Use && <Use />}
      {affidabilita === 'alta' && (
        <span title="Affidabilità alta" aria-label="Affidabilità alta" data-testid="badge-reliability-alta">
          <Shield className="fill-current" />
        </span>
      )}
      {affidabilita === 'bassa' && (
        <span title="Affidabilità bassa" aria-label="Affidabilità bassa" data-testid="badge-reliability-bassa">
          <Shield />
        </span>
      )}
    </span>
  )
}
