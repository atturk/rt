import type { Element } from '@/api/enrichment'

const KIND_LABELS: Record<Element['kind'], string> = { infographic: 'Infografica', visualization: 'Visualizzazione', image: 'Immagine IA' }

export const kindLabel = (kind: Element['kind']) => KIND_LABELS[kind] ?? 'Visualizzazione'
export const assetUrl = (lessonId: number, path: string) => `/api/v1/lessons/${lessonId}/${path}`
