import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage, unwrap, type Schemas } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'

type Row = Schemas['SectionLabelRow']
type Kind = 'esercizio' | 'caso'
const VALUES: Record<string, string> = {
  nessuno: 'nessuno',
  svolto: 'svolto',
  continua: 'continua il precedente',
  esplicito: 'esplicito',
  adattabile: 'si presta',
}
const KINDS: { kind: Kind; label: string }[] = [
  { kind: 'esercizio', label: 'Esercizio' },
  { kind: 'caso', label: 'Caso clinico' },
]

/** Etichette nascoste delle unità (sezioni della scaletta) da cui nascono casi clinici ed
 * esercizi: si vedono e si correggono solo qui. */
export function SectionLabelsCard({ lessonId }: { lessonId: number }) {
  const client = useQueryClient()
  const key = ['sections', lessonId]
  const data = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/sections', { params: { path: { lesson_id: lessonId } } })),
  })
  const update = useMutation({
    mutationFn: ({ row, kind, value }: { row: Row; kind: Kind; value: string | null }) =>
      unwrap(api.PUT('/api/v1/lessons/{lesson_id}/sections/{section_id}', {
        params: { path: { lesson_id: lessonId, section_id: row.section_id } }, body: { kind, value },
      })),
    onSuccess: (result) => client.setQueryData(key, result),
  })
  if (!data.data?.sections) return data.isError ? <Alert tone="danger">{errorMessage(data.error)}</Alert> : null
  const { mode, sections, options } = data.data
  return <Card className="flex flex-col gap-3 p-4 text-sm" data-testid="section-labels">
    <div>
      <h2 className="text-base font-bold">Casi clinici ed esercizi</h2>
      <p className="text-xs text-muted-foreground">
        Il classificatore legge ogni unità intera (tutte le sue subunità) e decide se contiene un esercizio svolto o casi
        clinici. Queste etichette non compaiono nello studio: servono solo a generare le domande «Casi» ed «Esercizi».
        Le unità si classificano alla prima generazione di queste domande.
      </p>
    </div>
    {mode === 'disabled' && <Alert tone="neutral">Classificatore spento: niente casi né esercizi.</Alert>}
    {update.isError && <Alert tone="danger">{errorMessage(update.error)}</Alert>}
    <ul aria-label="Etichette delle unità">
      {sections.map((row) => <li key={row.section_id} className="flex flex-wrap items-center gap-2 border-b py-2 last:border-b-0" data-testid="section-label">
        <span className="min-w-0 flex-1 font-medium">{row.section_id} · {row.title}
          <span className="ml-2 text-xs font-normal text-muted-foreground">{row.unit_ids.join(', ')}</span></span>
        {!row.fresh && <Badge tone="warning">Da classificare</Badge>}
        {row.error && <Badge tone="danger" title={row.error}>Non riuscita</Badge>}
        {KINDS.map(({ kind, label }) => {
          const predicted = row[kind] ?? null
          const override = row[kind === 'caso' ? 'override_caso' : 'override_esercizio'] ?? null
          const current = override ?? predicted ?? ''
          return <Select key={kind} className="w-auto" aria-label={`${label} in ${row.section_id}`} value={current}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ row, kind, value: e.target.value === predicted ? null : e.target.value })}>
            {!current && <option value="">{label}: ?</option>}
            {(options[kind] ?? []).map((v) => <option key={v} value={v}>{label}: {VALUES[v] ?? v}{override && v === override ? ' (corretta da te)' : ''}</option>)}
          </Select>
        })}
      </li>)}
    </ul>
    {sections.length === 0 && <p className="text-xs text-muted-foreground">Nessuna unità selezionata per il recaller.</p>}
  </Card>
}
