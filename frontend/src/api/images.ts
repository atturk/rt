import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { formData } from './jobStatus'

export type LessonImage = Schemas['LessonImage']

export const imageKeys = {
  list: (id: number) => ['images', id] as const,
  document: (id: number) => ['lesson', id, 'document'] as const,
}

const path = (id: number) => ({ path: { lesson_id: id } })

export function useLessonImages(id: number) {
  return useQuery({
    queryKey: imageKeys.list(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/images', { params: path(id) })),
  })
}

export function useLessonDocument(id: number) {
  return useQuery({
    queryKey: imageKeys.document(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/document', { params: path(id) })),
  })
}

export function useAddImages(id: number) {
  return useMutation({
    mutationFn: (vars: { files: File[]; webSearch: number; carousel: boolean }) =>
      unwrap(
        api.POST('/api/v1/lessons/{lesson_id}/images', {
          params: path(id),
          body: { carousel: vars.carousel, mock: false },
          bodySerializer: () =>
            formData({
              files: vars.files.length ? vars.files : null,
              web_search: vars.webSearch > 0 ? vars.webSearch : null,
              carousel: vars.carousel,
            }),
        }),
      ),
  })
}

/** Dopo il job add_images: rilegge immagini, documento e lezione dall'API. */
export function useRefreshImages(id: number) {
  const client = useQueryClient()
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: imageKeys.list(id) }),
      client.invalidateQueries({ queryKey: imageKeys.document(id) }),
      client.invalidateQueries({ queryKey: ['lesson', id] }),
    ])
}

/**
 * L'HTML del documento richiama le immagini con percorsi relativi alla lezione
 * (assets/images/<nome>): li porta all'endpoint dell'API che le serve.
 */
export function withImageUrls(html: string, id: number): string {
  return html.replace(/(<img\b[^>]*\bsrc=")(?:\.\/)?assets\/images\/([A-Za-z0-9_.-]+)"/g, (_m, head: string, name: string) => {
    return `${head}/api/v1/lessons/${id}/assets/images/${encodeURIComponent(name)}"`
  })
}
