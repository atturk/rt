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

/** Risultato del job telegram_topic_export: lo ZIP si scarica da topicArchiveUrl(job_id). */
export type TopicArchiveResult = { topic_id: number; file: string; size: number; messages: number; media_bytes: number }

export const topicArchiveUrl = (jobId: string) => `/api/v1/settings/telegram/user/archives/${encodeURIComponent(jobId)}`

/** "Esporta" di un topic con l'account utente: accoda il job telegram_topic_export (202). */
export function useExportTopicArchive() {
  return useMutation({
    mutationFn: (topicId: number) =>
      unwrap(api.POST('/api/v1/settings/telegram/user/topics/{topic_id}/archive', { params: { path: { topic_id: topicId } } })),
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
