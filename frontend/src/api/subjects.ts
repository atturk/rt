import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'

export type SubjectItem = Schemas['SubjectView']
export const subjectsKeys = { all: ['subjects'] as const }
export const subjectsApi = {
  list: (): Promise<SubjectItem[]> => unwrap(api.GET('/api/v1/subjects')),
  create: (nome: string): Promise<SubjectItem> => unwrap(api.POST('/api/v1/subjects', { body: { nome } })),
  delete: (nome: string): Promise<void> => unwrap(api.DELETE('/api/v1/subjects/{nome}', { params: { path: { nome } } })),
  addTeacher: (materia: string, nome: string): Promise<SubjectItem> => unwrap(api.POST('/api/v1/subjects/{nome}/teachers', {
    params: { path: { nome: materia } }, body: { nome },
  })),
  deleteTeacher: (materia: string, docente: string): Promise<void> => unwrap(api.DELETE('/api/v1/subjects/{nome}/teachers/{docente}', {
    params: { path: { nome: materia, docente } },
  })),
}
export function useSubjects() {
  return useQuery({ queryKey: subjectsKeys.all, queryFn: () => subjectsApi.list() })
}
// Maiuscole espanse dopo le minuscole: comprende ß/SS e sigma, preservando la ı turca.
const fold = (value: string) => Array.from(value).map(char => char === 'ı' ? char : char.toLowerCase().toUpperCase()).join('')
export function useTeacherSuggestions(materia: string): string[] {
  const { data } = useSubjects()
  const subjects = Array.isArray(data) ? data : []
  const subject = subjects.find(item => fold(item.nome) === fold(materia.trim()))
  const teachers = (subject ? [subject] : subjects).flatMap(item => item.docenti ?? [])
  return [...new Map(teachers.map(name => [fold(name), name])).values()].sort((a, b) => a.localeCompare(b))
}
export function useCreateSubject() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: subjectsApi.create, onSuccess: () => {
    void queryClient.invalidateQueries({ queryKey: subjectsKeys.all })
  } })
}
export function useDeleteSubject() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: subjectsApi.delete, onSuccess: () => {
    void queryClient.invalidateQueries({ queryKey: subjectsKeys.all })
  } })
}
export function useSubjectTeachers() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ materia, nome, remove }: { materia: string; nome: string; remove?: boolean }) => {
      if (remove) await subjectsApi.deleteTeacher(materia, nome)
      else await subjectsApi.addTeacher(materia, nome)
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: subjectsKeys.all }) },
  })
}
