// Contratto 4.2.5b2: alla fusione si passa a schema.d.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from './client'

export type SubjectItem = {
  nome: string
  lezioni: number
}

export const subjectsKeys = {
  all: ['subjects'] as const,
}

export const subjectsApi = {
  list: (): Promise<SubjectItem[]> =>
    unwrap((api as any).GET('/api/v1/subjects')),

  create: (nome: string): Promise<SubjectItem> =>
    unwrap((api as any).POST('/api/v1/subjects', { body: { nome } })),

  delete: (nome: string): Promise<void> =>
    unwrap((api as any).DELETE(`/api/v1/subjects/${encodeURIComponent(nome)}`)),
}

export function useSubjects() {
  return useQuery({
    queryKey: subjectsKeys.all,
    queryFn: () => subjectsApi.list(),
  })
}

export function useCreateSubject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (nome: string) => subjectsApi.create(nome),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: subjectsKeys.all })
    },
  })
}

export function useDeleteSubject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (nome: string) => subjectsApi.delete(nome),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: subjectsKeys.all })
    },
  })
}
