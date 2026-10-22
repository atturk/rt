import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'
import { subjectsKeys } from './subjects'

export type CalendarWeekView = Schemas['CalendarWeekView']
export type CalendarDayView = Schemas['CalendarDayView']
export type CalendarEventView = Schemas['CalendarEventView']
export type CalendarTemplateEntryView = Schemas['CalendarTemplateEntryView']
export type CalendarTemplateEntryCreate = Schemas['CalendarTemplateEntryCreate']
export type CalendarOverrideView = Schemas['CalendarOverrideView']
export type CalendarOverrideCreate = Schemas['CalendarOverrideCreate']
export type CalendarDayStateView = Schemas['CalendarDayStateView']
export type CalendarDayStateSet = Schemas['CalendarDayStateSet']
export type CalendarEntryStateView = Schemas['CalendarEntryStateView']
export type CalendarEntryStateSet = Schemas['CalendarEntryStateSet']
export type CalendarLinkLessonRequest = Schemas['CalendarLinkLessonRequest']
export type CalendarLessonSummary = Schemas['CalendarLessonSummary']
export type CalendarToRecoverItem = Schemas['CalendarToRecoverItem']
export type CalendarWeekSummary = Schemas['CalendarWeekSummary']

export const calendarKeys = {
  all: ['calendar'] as const,
  week: (date?: string) => ['calendar', 'week', date ?? 'today'] as const,
  day: (date?: string) => ['calendar', 'day', date ?? 'today'] as const,
  template: () => ['calendar', 'template'] as const,
}

export const calendarApi = {
  getWeek: (date?: string): Promise<CalendarWeekView> =>
    unwrap(
      api.GET('/api/v1/calendar/week', {
        params: { query: date ? { date } : {} },
      }),
    ) as Promise<CalendarWeekView>,

  getDay: (date?: string): Promise<CalendarDayView> =>
    unwrap(
      api.GET('/api/v1/calendar/day', {
        params: { query: date ? { date } : {} },
      }),
    ) as Promise<CalendarDayView>,

  listTemplate: (): Promise<CalendarTemplateEntryView[]> =>
    unwrap(api.GET('/api/v1/calendar/template')) as Promise<CalendarTemplateEntryView[]>,

  createTemplate: (body: CalendarTemplateEntryCreate): Promise<CalendarTemplateEntryView> =>
    unwrap(
      api.POST('/api/v1/calendar/template', {
        body,
      }),
    ) as Promise<CalendarTemplateEntryView>,

  deleteTemplate: (entryId: number, from?: string, to?: string): Promise<void> =>
    unwrap(
      api.DELETE('/api/v1/calendar/template/{entry_id}', {
        params: { path: { entry_id: entryId }, query: { ...(from ? { from } : {}), ...(to ? { to } : {}) } },
      }),
    ) as Promise<void>,

  createOverride: (body: CalendarOverrideCreate): Promise<CalendarOverrideView> =>
    unwrap(
      api.POST('/api/v1/calendar/override', {
        body,
      }),
    ) as Promise<CalendarOverrideView>,

  deleteOverride: (overrideId: number): Promise<void> =>
    unwrap(
      api.DELETE('/api/v1/calendar/override/{override_id}', {
        params: { path: { override_id: overrideId } },
      }),
    ) as Promise<void>,

  setDayState: (body: CalendarDayStateSet): Promise<CalendarDayStateView> =>
    unwrap(
      api.POST('/api/v1/calendar/day-state', {
        body,
      }),
    ) as Promise<CalendarDayStateView>,

  setEntryState: (body: CalendarEntryStateSet): Promise<CalendarEntryStateView> =>
    unwrap(
      api.POST('/api/v1/calendar/entry-state', {
        body,
      }),
    ) as Promise<CalendarEntryStateView>,

  linkLesson: (body: CalendarLinkLessonRequest): Promise<CalendarEntryStateView> =>
    unwrap(
      api.POST('/api/v1/calendar/link-lesson', {
        body,
      }),
    ) as Promise<CalendarEntryStateView>,
}

export function useCalendarWeek(date?: string) {
  return useQuery({
    queryKey: calendarKeys.week(date),
    queryFn: () => calendarApi.getWeek(date),
  })
}

export function useCalendarDay(date?: string) {
  return useQuery({
    queryKey: calendarKeys.day(date),
    queryFn: () => calendarApi.getDay(date),
  })
}

export function useCalendarTemplate() {
  return useQuery({
    queryKey: calendarKeys.template(),
    queryFn: () => calendarApi.listTemplate(),
  })
}

export function useCreateTemplateEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarTemplateEntryCreate) => calendarApi.createTemplate(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
      qc.invalidateQueries({ queryKey: subjectsKeys.all })
    },
  })
}

export function useDeleteTemplateEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, from, to }: { id: number; from?: string; to?: string }) => calendarApi.deleteTemplate(id, from, to),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useCreateOverride() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarOverrideCreate) => calendarApi.createOverride(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
      qc.invalidateQueries({ queryKey: subjectsKeys.all })
    },
  })
}

export function useDeleteOverride() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => calendarApi.deleteOverride(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useSetDayState() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarDayStateSet) => calendarApi.setDayState(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useSetEntryState() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarEntryStateSet) => calendarApi.setEntryState(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useLinkLesson() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CalendarLinkLessonRequest) => calendarApi.linkLesson(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export type CalendarYearWeek = Schemas['CalendarYearWeek']
export type CalendarSchedule = Schemas['CalendarSchedule']
export type CalendarPasteEntry = Schemas['CalendarPasteEntry']
export type CalendarImportResult = Schemas['CalendarImportResult']
export const calendarTransferApi = {
  year: (start: string): Promise<CalendarYearWeek[]> => unwrap(api.GET('/api/v1/calendar/year', { params: { query: { start } } })),
  paste: (weeks: string[], entries: CalendarPasteEntry[]) => unwrap(api.POST('/api/v1/calendar/paste', { body: { weeks, entries } })),
  export: (): Promise<CalendarSchedule> => unwrap(api.GET('/api/v1/calendar/export')),
  import: (data: Record<string, unknown>, dry_run: boolean, from?: string, to?: string): Promise<CalendarImportResult> => unwrap(api.POST('/api/v1/calendar/import', {
    body: { data, dry_run, ...(from ? { from, to } : {}) },
  })),
}
export function useCalendarYear(start: string, enabled = true) {
  return useQuery({ queryKey: [...calendarKeys.all, 'year', start], queryFn: () => calendarTransferApi.year(start), enabled })
}
export function usePasteCalendar() {
  const client = useQueryClient()
  return useMutation({ mutationFn: ({ weeks, entries }: { weeks: string[]; entries: CalendarPasteEntry[] }) => calendarTransferApi.paste(weeks, entries),
    onSuccess: () => { void client.invalidateQueries({ queryKey: calendarKeys.all }); void client.invalidateQueries({ queryKey: subjectsKeys.all }) },
  })
}

export function useMissingLessons(enabled = true) {
  return useQuery({ queryKey: [...calendarKeys.all, 'missing'], queryFn: () => unwrap(api.GET('/api/v1/calendar/missing')), enabled })
}

export function useSetPeriodStart() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (date: string | null) => unwrap(api.PUT('/api/v1/calendar/period-start', { body: { date } })),
    onSuccess: () => { void client.invalidateQueries({ queryKey: calendarKeys.all }) },
  })
}
