import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { api, type Schemas } from './client'
import { lessonKeys, reviewKeys, useDecideIssue, useUndoDecision } from './hooks'

const list = (): Schemas['IssueList'] => ({
  items: ['sci_1', 'sci_2'].map(id => ({ issue: { id, unit_id: '1.1', claim: 'Errato', anchor: { quote: 'Errato', prefix: '', suffix: '', start: 0, end: 6 } }, fix_text: 'Corretto', needs_reconfirmation: false, decision: null })),
  pending: 2, total: 2, review_complete: false,
})
const confirmed: Schemas['Decision'] = { issue_id: 'sci_1', decision: 'accepted', resolved_text: 'Corretto', resolved_by: 'api', timestamp: '2026-10-10T10:00:00', channel: 'api' }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(reviewKeys.issues(7), list())
  client.setQueryData(reviewKeys.decisions(7), [])
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const issues = () => client.getQueryData<Schemas['IssueList']>(reviewKeys.issues(7))!
  const decisions = () => client.getQueryData<Schemas['Decision'][]>(reviewKeys.decisions(7))!
  return { client, invalidate, wrapper, issues, decisions }
}
afterEach(() => vi.restoreAllMocks())

it('decide prima della risposta, conferma il registro locale e rilegge solo tre query', async () => {
  const { wrapper, issues, decisions, invalidate } = setup()
  const response = deferred<unknown>()
  vi.spyOn(api, 'POST').mockReturnValue(response.promise as never)
  const { result } = renderHook(() => useDecideIssue(7), { wrapper })
  act(() => result.current.mutate({ issueId: 'sci_1', decision: 'accepted' }))
  await waitFor(() => expect(issues().items[0].decision?.decision).toBe('accepted'))
  expect(issues().pending).toBe(1)
  expect(issues().items[1].decision).toBeNull()
  expect(decisions()).toHaveLength(1)
  expect(result.current.isPending).toBe(true)
  expect(invalidate).not.toHaveBeenCalled()
  response.resolve({ data: confirmed, error: undefined, response: new Response('{}') })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(issues().items[0].decision).toEqual(confirmed)
  expect(decisions()).toEqual([confirmed])
  expect(invalidate.mock.calls.map(([filters]) => filters)).toEqual([
    { queryKey: reviewKeys.issues(7), exact: true }, { queryKey: reviewKeys.units(7), exact: true }, { queryKey: lessonKeys.document(7), exact: true },
  ])
})

it('torna indietro su errore 409 senza perdere issue arrivate nel frattempo', async () => {
  const { client, wrapper, issues, decisions } = setup()
  const response = deferred<unknown>()
  vi.spyOn(api, 'POST').mockReturnValue(response.promise as never)
  const { result } = renderHook(() => useDecideIssue(7), { wrapper })
  act(() => result.current.mutate({ issueId: 'sci_1', decision: 'edited', text: 'Modificato' }))
  await waitFor(() => expect(issues().items[0].decision?.resolved_text).toBe('Modificato'))
  act(() => client.setQueryData<Schemas['IssueList']>(reviewKeys.issues(7), old => ({ ...old!, items: [...old!.items, { issue: { id: 'live' }, needs_reconfirmation: false }], total: 3, pending: 2 })))
  response.resolve({ error: { error: { code: 'unit_in_review', message: 'Unità in verifica' } }, response: new Response('{}', { status: 409 }) })
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(issues().items[0].decision).toBeNull()
  expect(issues().items.map(i => i.issue.id)).toEqual(['sci_1', 'sci_2', 'live'])
  expect(issues().pending).toBe(3)
  expect(decisions()).toEqual([])
})

it('Annulla riapre subito e ripristina la decisione se il server risponde errore', async () => {
  const { client, wrapper, issues, decisions } = setup()
  client.setQueryData(reviewKeys.decisions(7), [confirmed])
  client.setQueryData(reviewKeys.issues(7), { ...list(), items: [{ ...list().items[0], decision: confirmed }, list().items[1]], pending: 1 })
  const response = deferred<unknown>()
  vi.spyOn(api, 'POST').mockReturnValue(response.promise as never)
  const { result } = renderHook(() => useUndoDecision(7), { wrapper })
  act(() => result.current.mutate('sci_1'))
  await waitFor(() => expect(issues().items[0].decision).toBeNull())
  expect(issues().pending).toBe(2)
  expect(decisions()).toEqual([])
  response.resolve({ error: { error: { code: 'undo_rejected', message: 'Annullamento rifiutato' } }, response: new Response('{}', { status: 409 }) })
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(issues().items[0].decision).toEqual(confirmed)
  expect(issues().pending).toBe(1)
  expect(decisions()).toEqual([confirmed])
})
