import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'

export type QuestionDefinition = Schemas['CustomQuestionType']
export type QuestionSettings = Schemas['QuestionSettings']
export const questionSettingsKey = ['settings', 'questions'] as const
export function useQuestionSettings() {
  return useQuery({ queryKey: questionSettingsKey, queryFn: () => unwrap(api.GET('/api/v1/settings/questions')) })
}
export function useSaveQuestionType() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ definition, id }: { definition: QuestionDefinition; id?: string }) => id
      ? unwrap(api.PUT('/api/v1/settings/questions/{identifier}', { params: { path: { identifier: id } }, body: definition }))
      : unwrap(api.POST('/api/v1/settings/questions', { body: definition })),
    onSuccess: () => invalidate(client),
  })
}
function invalidate(client: ReturnType<typeof useQueryClient>) {
  for (const key of [questionSettingsKey, ['recall-types'], ['classifier'], ['recall']]) void client.invalidateQueries({ queryKey: key })
}
export function useDeleteQuestionType() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (id: string) => unwrap(api.DELETE('/api/v1/settings/questions/{identifier}', { params: { path: { identifier: id } } })), onSuccess: () => invalidate(client) })
}
export function useImportQuestionType() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (definition: QuestionDefinition) => unwrap(api.POST('/api/v1/settings/questions/import', { body: definition })), onSuccess: () => invalidate(client) })
}
export function useQuestionTrial() {
  return useMutation({ mutationFn: (body: Schemas['QuestionTrialIn']) => unwrap(api.POST('/api/v1/settings/questions/trial', { body })) })
}
export async function exportQuestionType(id: string) {
  const definition = await unwrap(api.GET('/api/v1/settings/questions/{identifier}/export', { params: { path: { identifier: id } } }))
  const blob = new Blob([JSON.stringify(definition, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${id}.json`
  link.click()
  URL.revokeObjectURL(url)
}
