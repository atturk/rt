import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'
import { lessonKeys } from './hooks'
import { formData } from './jobStatus'

export type LessonImage = Schemas['LessonImage']

export const imageKeys = { list: (id: number) => ['images', id] as const }

const path = (id: number) => ({ path: { lesson_id: id } })

export function useLessonImages(id: number) {
  return useQuery({
    queryKey: imageKeys.list(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}/images', { params: path(id) })),
  })
}

/** perUnit: immagini da cercare sul web per ogni unità (0 = nessuna ricerca); units: le unità
 *  scelte, null = tutte. */
export function useAddImages(id: number) {
  return useMutation({
    mutationFn: (vars: {
      files?: File[]
      perUnit?: number
      units?: string[] | null
      selected_images?: string[] | null
      pages_only?: boolean
    }) =>
      unwrap(
        api.POST('/api/v1/lessons/{lesson_id}/images', {
          params: path(id),
          body: { mock: false, pages_only: !!vars.pages_only },
          bodySerializer: () =>
            formData({
              files: vars.files && vars.files.length ? vars.files : null,
              web_search: vars.perUnit && vars.perUnit > 0 ? vars.perUnit : null,
              units: vars.perUnit && vars.perUnit > 0 && vars.units ? vars.units : null,
              selected_images: vars.selected_images && vars.selected_images.length ? vars.selected_images : null,
              pages_only: vars.pages_only ? true : null,
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
      client.invalidateQueries({ queryKey: lessonKeys.all(id) }),
    ])
}

/** Caricamento diretto dall'editor: nessun job LLM, il file è già un media della lezione. */
export function uploadEditorImage(id: number, file: File, leaseToken: string) {
  return unwrap(api.POST('/api/v1/lessons/{lesson_id}/media/images', {
    params: path(id), body: { file: file.name, lease_token: leaseToken },
    bodySerializer: () => formData({ file, lease_token: leaseToken }),
  }))
}

/** Copia una pagina dei materiali in assets/images per l'inserimento nel documento. */
export function copyMaterialPage(id: number, sourceId: string, page: number, leaseToken?: string) {
  return unwrap(api.POST('/api/v1/lessons/{lesson_id}/media/material-page', {
    params: path(id),
    body: { source_id: sourceId, page, lease_token: leaseToken },
  }))
}

/** Toglie dal documento e da placement i riferimenti alle immagini indicate. */
export function removeFromText(id: number, imageNames: string[], leaseToken?: string) {
  return unwrap(api.POST('/api/v1/lessons/{lesson_id}/media/remove-from-text', {
    params: path(id),
    body: { image_names: imageNames, lease_token: leaseToken },
  }))
}

/** Ritaglia un'immagine (come nuova immagine o sostituzione). */
export function cropMediaImage(
  id: number,
  imageName: string,
  rect: [number, number, number, number],
  replace: boolean = false,
  leaseToken?: string,
) {
  return unwrap(api.POST('/api/v1/lessons/{lesson_id}/media/crop', {
    params: path(id),
    body: {
      image_name: imageName,
      rect,
      replace,
      lease_token: leaseToken ?? null,
    },
  }))
}



