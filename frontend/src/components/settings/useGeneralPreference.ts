import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { type Settings } from '@/api/settings'

/** Salva solo il controllo cambiato, rileggendo i valori generali per non ripristinare la modalità. */
export function useGeneralPreference() {
  const client = useQueryClient()
  return useMutation({
    scope: { id: 'general-preferences' },
    mutationFn: async (change: Partial<NonNullable<Settings['preferences']>>) => {
      const latest = await unwrap(api.GET('/api/v1/settings'))
      return unwrap(api.PUT('/api/v1/settings/preferences', { body: {
        modalita_scaletta: 'auto', secondi_approvazione: 10, sfondo_gruppi: 'colori', modalita_arricchimento: 'manuale', chiusura_x: 'background', ...latest.preferences, ...change,
      } }))
    },
    onSuccess: settings => { client.setQueryData(['settings'], settings) },
  })
}
