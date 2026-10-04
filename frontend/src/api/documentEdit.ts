import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'
import { settingsKeys } from './settings'

export type Notice = 'preview_edit_beta'

/** "Non mostrare più": salvato nelle impostazioni lato server, vale per tutti i browser. */
export function useDismissNotice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (notice: Notice | 'setup_wizard') => unwrap(api.PUT('/api/v1/settings/notices', { body: { notice, dismissed: true } })),
    onSuccess: () => client.invalidateQueries({ queryKey: settingsKeys.all }),
  })
}
