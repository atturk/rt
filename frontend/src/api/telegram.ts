import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'

export const telegramKeys = { notifications: ['telegram', 'notifications'] as const }

/** Ultime notifiche inviate (lezione pronta, decisioni, errori, prove). */
export function useTelegramNotifications() {
  return useQuery({
    queryKey: telegramKeys.notifications,
    queryFn: () => unwrap(api.GET('/api/v1/telegram/notifications', { params: { query: { limit: 20 } } })),
    // Polling lento voluto: le notifiche le manda il worker, senza eventi live propri.
    refetchInterval: 30_000,
  })
}

/** "Prova": un messaggio nella chat collegata; l'esito è nella risposta. */
export function useTelegramTest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/settings/telegram/test')),
    onSettled: () => client.invalidateQueries({ queryKey: telegramKeys.notifications }),
  })
}
