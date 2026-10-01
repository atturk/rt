import type { Element } from '@/api/enrichment'

export const kindLabel = (kind: Element['kind']) => kind === 'infographic' ? 'Infografica' : 'Visualizzazione'
export const assetUrl = (lessonId: number, path: string) => `/api/v1/lessons/${lessonId}/${path}`
