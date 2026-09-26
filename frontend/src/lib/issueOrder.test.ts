import { parseIssueOrder, sortIssues, type SortableIssue } from './issueOrder'

type Item = SortableIssue & { id: string }
const ids = (items: Item[]) => items.map((i) => i.id)
const key = (i: Item) => i

const items: Item[] = [
  { id: 'a', type: 'ERR_ASR_ST', severity: 'high', startSeconds: 10 },
  { id: 'b', type: 'ERR_CONCETTUALE', severity: 'low', startSeconds: 20 },
  { id: 'c', type: 'ERR_CONCETTUALE', severity: 'high', startSeconds: 300 },
  { id: 'd', type: 'ERR_REWRITE_DRIFT', severity: 'high', startSeconds: 5 },
  { id: 'e', type: 'ERR_CONCETTUALE', severity: 'medium', startSeconds: null },
  { id: 'f', type: 'ERR_CONCETTUALE', severity: 'high', startSeconds: 40 },
  { id: 'g', type: 'ERR_ASR_LLM', severity: 'low', startSeconds: 1 },
]

it('cronologico: per timecode, senza timecode in fondo', () => {
  expect(ids(sortIssues(items, 'cronologico', key))).toEqual(['g', 'd', 'a', 'b', 'f', 'c', 'e'])
})

it('per tipo e gravità: prima gli errori concettuali più gravi, poi per timecode', () => {
  expect(ids(sortIssues(items, 'gravita', key))).toEqual(['f', 'c', 'e', 'b', 'd', 'g', 'a'])
})

it('tipi e gravità sconosciuti dopo quelli noti', () => {
  const odd: Item[] = [
    { id: 'x', type: 'ALTRO', severity: 'high', startSeconds: 1 },
    { id: 'y', type: 'ERR_ASR_ST', severity: 'boh', startSeconds: 2 },
    { id: 'z', type: 'ERR_ASR_ST', severity: 'low', startSeconds: 3 },
  ]
  expect(ids(sortIssues(odd, 'gravita', key))).toEqual(['z', 'y', 'x'])
})

it("a parità mantiene l'ordine dell'API e non modifica l'originale", () => {
  const same: Item[] = [
    { id: '1', type: 'ERR_CONCETTUALE', severity: 'high', startSeconds: 7 },
    { id: '2', type: 'ERR_CONCETTUALE', severity: 'high', startSeconds: 7 },
    { id: '3', type: 'ERR_CONCETTUALE', severity: 'high', startSeconds: 7 },
  ]
  const copy = [...same]
  expect(ids(sortIssues(same, 'gravita', key))).toEqual(['1', '2', '3'])
  expect(ids(sortIssues(same, 'cronologico', key))).toEqual(['1', '2', '3'])
  expect(same).toEqual(copy)
})

it("legge l'ordine dall'URL con il cronologico come predefinito", () => {
  expect(parseIssueOrder('gravita')).toBe('gravita')
  expect(parseIssueOrder('cronologico')).toBe('cronologico')
  expect(parseIssueOrder(null)).toBe('cronologico')
  expect(parseIssueOrder('boh')).toBe('cronologico')
})
