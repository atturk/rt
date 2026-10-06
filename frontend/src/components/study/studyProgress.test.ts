import { initialStudyUnit, nextStudyStatus, studyDate } from './studyProgress'

it('apre la prima unità non appresa, oppure la prima quando sono tutte apprese', () => {
  expect(initialStudyUnit([{ status: 'appreso' }, { status: 'in-apprendimento' }, {}])).toBe(1)
  expect(initialStudyUnit([{ status: 'appreso' }, { status: 'appreso' }])).toBe(0)
  expect(initialStudyUnit([{ status: 'ignorata' }, { status: 'appreso' }, {}])).toBe(2)
  expect(initialStudyUnit([{ status: 'ignorata' }, { status: 'appreso' }])).toBe(0)
  expect(initialStudyUnit([])).toBe(0)
})

it('cicla i quattro stati senza promozioni automatiche', () => {
  expect(nextStudyStatus()).toBe('in-apprendimento')
  expect(nextStudyStatus('in-apprendimento')).toBe('appreso')
  expect(nextStudyStatus('appreso')).toBe('ignorata')
  expect(nextStudyStatus('ignorata')).toBe('da-imparare')
})

it('mostra oggi, ieri e la data per i cambi precedenti, anche attraverso il cambio di mese', () => {
  const now = new Date(2026, 9, 1, 12)
  expect(studyDate(new Date(2026, 9, 1, 8).toISOString(), now)).toBe('oggi')
  expect(studyDate(new Date(2026, 8, 30, 23).toISOString(), now)).toBe('ieri')
  expect(studyDate(new Date(2026, 8, 28).toISOString(), now)).toBe('28 set')
  expect(studyDate(null, now)).toBe('')
})
