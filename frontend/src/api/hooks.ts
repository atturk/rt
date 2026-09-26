import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'

export const queryKeys = {
  me: ['auth', 'me'] as const,
  health: ['health'] as const,
  lessons: (filters: LessonFilters) => ['lessons', filters] as const,
  allLessons: ['lessons'] as const,
  lesson: (id: number) => ['lesson', id] as const,
  costs: ['costs'] as const,
}

export type LessonFilters = { materia?: string; state?: string; q?: string }

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => unwrap(api.GET('/api/v1/auth/me')),
    retry: false,
    staleTime: 60_000,
  })
}

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health, queryFn: () => unwrap(api.GET('/api/v1/health')), staleTime: 60_000 })
}

export function useLessons(filters: LessonFilters = {}) {
  const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) as LessonFilters
  return useQuery({
    queryKey: queryKeys.lessons(query),
    queryFn: () => unwrap(api.GET('/api/v1/lessons', { params: { query } })),
  })
}

export function useLesson(id: number) {
  return useQuery({
    queryKey: queryKeys.lesson(id),
    queryFn: () => unwrap(api.GET('/api/v1/lessons/{lesson_id}', { params: { path: { lesson_id: id } } })),
    enabled: Number.isFinite(id),
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => unwrap(api.POST('/api/v1/auth/session', { body: { token } })),
    onSuccess: () => client.invalidateQueries(),
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/auth/session')),
    onSettled: () => client.clear(),
  })
}
