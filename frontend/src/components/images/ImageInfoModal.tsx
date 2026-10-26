import { useQuery } from '@tanstack/react-query'

import { api, errorMessage, unwrap } from '@/api/client'
import type { components } from '@/api/schema'
import { Modal } from '@/components/ui/modal'

export type ImageInfo = components['schemas']['ImageInfo']
export type ImageInfoTarget = { lessonId: number; name: string } | { sha: string; page: number }

const ROLES: Record<string, string> = { introduttiva: 'Introduttiva', irrilevante: 'Irrilevante' }
const FIELDS: [string, string][] = [['slide_title', 'Titolo'], ['visual_elements', 'Elementi'], ['summary_keywords', 'Parole chiave'], ['alt_text', 'Alt']]

function fetchInfo(target: ImageInfoTarget) {
  return 'sha' in target
    ? unwrap(api.GET('/api/v1/archive/{sha}/pages/{n}/info', { params: { path: { sha: target.sha, n: target.page } } }))
    : unwrap(api.GET('/api/v1/lessons/{lesson_id}/media/info', { params: { path: { lesson_id: target.lessonId }, query: { name: target.name } } }))
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
  const query = useQuery({ queryKey: ['image-info', target], queryFn: () => fetchInfo(target!), enabled: target !== null })
  return (
    <Modal open={target !== null} onClose={onClose} title="Informazioni" compact testId="image-info-modal">
      {query.data ? <ImageInfoContent info={query.data} /> : query.isError ? <p className="text-meta text-danger">{errorMessage(query.error)}</p> : null}
    </Modal>
  )
}
