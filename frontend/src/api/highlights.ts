import { api, unwrap, type Schemas } from './client'

export type StudyHighlight = Schemas['Highlight']
export type HighlightSourceData = StudyHighlight['source']

/** Evidenziazioni dello Studio di un'unità (4.2.2, H1): solo su RT, non nel documento. */
export const highlightsApi = {
  list: (lessonId: number, unit: string) =>
    unwrap(api.GET('/api/v1/lessons/{lesson_id}/highlights', { params: { path: { lesson_id: lessonId }, query: { unit } } })),
  add: (lessonId: number, body: Schemas['HighlightIn']) =>
    unwrap(api.POST('/api/v1/lessons/{lesson_id}/highlights', { params: { path: { lesson_id: lessonId } }, body })),
  remove: (lessonId: number, id: number) =>
    unwrap(api.DELETE('/api/v1/lessons/{lesson_id}/highlights/{highlight_id}', { params: { path: { lesson_id: lessonId, highlight_id: id } } })),
  clear: (lessonId: number, unit: string) =>
    unwrap(api.DELETE('/api/v1/lessons/{lesson_id}/highlights', { params: { path: { lesson_id: lessonId }, query: { unit } } })),
}
