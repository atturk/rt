import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'
import { lessonKeys } from './hooks'
import { settingsKeys } from './settings'

/** Modifica dell'anteprima del documento (RT4-FA3, beta): controllo senza salvare e
 * salvataggio nella bozza. Dopo il salvataggio si rilegge tutta la lezione (documento, fasi,
 * build da rifare, issue orfane). */

export function useCheckDocument(lessonId: number) {
  return useMutation({
    mutationFn: (markdown: string) =>
      unwrap(api.POST('/api/v1/lessons/{lesson_id}/document/check', { params: { path: { lesson_id: lessonId } }, body: { markdown } })),
  })
}

export function useSaveDocument(lessonId: number, leaseToken?: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (markdown: string) =>
      unwrap(api.PUT('/api/v1/lessons/{lesson_id}/document/draft', { params: { path: { lesson_id: lessonId } }, body: { markdown, lease_token: leaseToken } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: lessonKeys.all(lessonId) })
      void client.invalidateQueries({ queryKey: ['lessons'] })
    },
  })
}

export type Notice = 'preview_edit_beta' | 'preview_edit_issues'

/** "Non mostrare più": salvato nelle impostazioni lato server, vale per tutti i browser. */
export function useDismissNotice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (notice: Notice) => unwrap(api.PUT('/api/v1/settings/notices', { body: { notice, dismissed: true } })),
    onSuccess: () => client.invalidateQueries({ queryKey: settingsKeys.all }),
  })
}
