import { useQuery } from '@tanstack/react-query'

import { api, errorMessage, unwrap } from '@/api/client'
import type { Element } from '@/api/enrichment'
import type { components } from '@/api/schema'
import { Modal } from '@/components/ui/modal'
import { kindLabel } from '@/lib/enrichment'

export type ImageInfo = components['schemas']['ImageInfo']
export type ImageInfoTarget = { lessonId: number; name: string } | { sha: string; page: number } | { enrichment: Element }

const ROLES: Record<string, string> = { introduttiva: 'Introduttiva', irrilevante: 'Irrilevante' }
const FIELDS: [string, string][] = [['slide_title', 'Titolo'], ['visual_elements', 'Elementi'], ['summary_keywords', 'Parole chiave'], ['alt_text', 'Alt']]

function fetchInfo(target: ImageInfoTarget) {
  if ('enrichment' in target) return Promise.resolve(null)
  return 'sha' in target
    ? unwrap(api.GET('/api/v1/archive/{sha}/pages/{n}/info', { params: { path: { sha: target.sha, n: target.page } } }))
    : unwrap(api.GET('/api/v1/lessons/{lesson_id}/media/info', { params: { path: { lesson_id: target.lessonId }, query: { name: target.name } } }))
}

export function EnrichmentInfoContent({ element }: { element: Element }) {
  const modeLabel = element.mode === 'interactive' || element.asset_mode === 'interactive' ? 'Interattiva' : 'Statica'
  return (
    <div className="flex max-h-[60vh] select-text flex-col gap-3 overflow-y-auto text-sm" data-testid="enrichment-info">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-fit rounded-full bg-muted px-2 py-0.5 text-meta font-medium">{kindLabel(element.kind)}</span>
        <span className="w-fit rounded-full bg-muted px-2 py-0.5 text-meta text-muted-foreground">Unità {element.unit_id}</span>
        <span className="w-fit rounded-full bg-muted px-2 py-0.5 text-meta text-muted-foreground">{modeLabel}</span>
      </div>
      {element.title && (
        <section>
          <h3 className="text-meta font-semibold text-muted-foreground">Titolo</h3>
          <p className="font-medium">{element.title}</p>
        </section>
      )}
      {element.description && (
        <section>
          <h3 className="text-meta font-semibold text-muted-foreground">Descrizione</h3>
          <p className="whitespace-pre-wrap">{element.description}</p>
        </section>
      )}
      {element.prompt && (
        <details className="group rounded border p-2 text-meta">
          <summary className="cursor-pointer font-semibold text-muted-foreground select-none">Prompt</summary>
          <p className="mt-1.5 whitespace-pre-wrap text-foreground">{element.prompt}</p>
        </details>
      )}
    </div>
  )
}

/** Testo estratto, descrizione e ruolo di un'immagine: solo le parti presenti. */
export function ImageInfoContent({ info }: { info: ImageInfo }) {
  const description = FIELDS.filter(([key]) => info.descrizione?.[key])
  const role = info.ruolo ? ROLES[info.ruolo] : undefined
  if (!info.testo && description.length === 0 && !role) return <p className="text-meta text-muted-foreground">Nessuna informazione</p>
  return (
    <div className="flex max-h-[60vh] select-text flex-col gap-3 overflow-y-auto text-sm" data-testid="image-info">
      {role && <span className="w-fit rounded-full bg-muted px-2 py-0.5 text-meta">{role}</span>}
      {info.testo && <section><h3 className="text-meta font-semibold text-muted-foreground">Testo</h3><p className="whitespace-pre-wrap">{info.testo}</p></section>}
      {description.length > 0 && <section><h3 className="text-meta font-semibold text-muted-foreground">Descrizione</h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">{description.map(([key, label]) => <div key={key} className="contents"><dt className="text-muted-foreground">{label}</dt><dd className="whitespace-pre-wrap">{info.descrizione?.[key]}</dd></div>)}</dl>
      </section>}
    </div>
  )
}

export function ImageInfoModal({ target, onClose }: { target: ImageInfoTarget | null; onClose: () => void }) {
  const isEnrichment = target !== null && 'enrichment' in target
  const query = useQuery({ queryKey: ['image-info', target], queryFn: () => fetchInfo(target!), enabled: target !== null && !isEnrichment })
  return (
    <Modal open={target !== null} onClose={onClose} title="Informazioni" compact testId="image-info-modal">
      {isEnrichment && target?.enrichment ? (
        <EnrichmentInfoContent element={target.enrichment} />
      ) : query.data ? (
        <ImageInfoContent info={query.data} />
      ) : query.isError ? (
        <p className="text-meta text-danger">{errorMessage(query.error)}</p>
      ) : null}
    </Modal>
  )
}
