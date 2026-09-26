import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'

export const telegramKeys = { daemon: ['telegram', 'daemon'] as const, notifications: ['telegram', 'notifications'] as const }

export function useTelegramDaemon() {
  return useQuery({
    queryKey: telegramKeys.daemon,
    queryFn: () => unwrap(api.GET('/api/v1/telegram/daemon')),
    refetchInterval: 10_000,
  })
}

/** Avvio e arresto: lo stato mostrato è sempre quello riletto dall'API. */
export function useTelegramDaemonAction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (action: 'start' | 'stop') =>
      action === 'start'
        ? unwrap(api.POST('/api/v1/telegram/daemon/start'))
        : unwrap(api.POST('/api/v1/telegram/daemon/stop')),
    onSettled: () => client.invalidateQueries({ queryKey: telegramKeys.daemon }),
  })
}

/** Ultime notifiche inviate dal bot (lezione pronta, issue, prove dei topic). */
export function useTelegramNotifications() {
  return useQuery({
    queryKey: telegramKeys.notifications,
    queryFn: () => unwrap(api.GET('/api/v1/telegram/notifications', { params: { query: { limit: 20 } } })),
    refetchInterval: 30_000,
  })
}
