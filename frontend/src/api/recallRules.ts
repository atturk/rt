import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'

export const recallRulesKey = ['recall-rules'] as const
export function useRecallRules() {
  return useQuery({ queryKey: recallRulesKey, queryFn: () => unwrap(api.GET('/api/v1/settings/recall-rules')) })
}
export function useSaveRecallVotes() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: Schemas['RecallVoteSettings']) => unwrap(api.PUT('/api/v1/settings/recall-votes', { body })),
    onSuccess: data => client.setQueryData(recallRulesKey, data) })
}
export function useEditRecallRules() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: Schemas['RecallRuleEdit']) => unwrap(api.PUT('/api/v1/settings/recall-rules', { body })),
    onSuccess: data => client.setQueryData(recallRulesKey, data) })
}
export function useUpdateRecallRules() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: Schemas['RecallRuleUpdate']) => unwrap(api.POST('/api/v1/settings/recall-rules/update', { body })),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['jobs'] }) } })
}
