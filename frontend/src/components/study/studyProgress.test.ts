import {
  initialStudyUnit,
  nextStudyStatus,
  resolveStatusOrder,
  resolveStudyStatus,
  studyDate,
  type CustomStudyStatus,
} from './studyProgress'

it('apre la prima unità non appresa, oppure la prima quando sono tutte apprese', () => {
  expect(initialStudyUnit([{ status: 'appreso' }, { status: 'in-apprendimento' }, {}])).toBe(1)
  expect(initialStudyUnit([{ status: 'appreso' }, { status: 'appreso' }])).toBe(0)
  expect(initialStudyUnit([{ status: 'ignorata' }, { status: 'appreso' }, {}])).toBe(2)
  expect(initialStudyUnit([{ status: 'ignorata' }, { status: 'appreso' }])).toBe(0)
  expect(initialStudyUnit([])).toBe(0)
  // Uno stato personalizzato conta come non appreso
  expect(initialStudyUnit([{ status: 'appreso' }, { status: 'c1' as never }])).toBe(1)
  // …a meno che sia segnato «Salta in Studio»
  const custom = [{ id: 'c1', nome: 'Anki', colore: 'text-indigo-500', icona: 'Star', salta: true }]
  expect(initialStudyUnit([{ status: 'appreso' }, { status: 'c1' as never }, {}], custom)).toBe(2)
  expect(initialStudyUnit([{ status: 'c2' as never }, { status: 'c1' as never }], custom)).toBe(0)
})

it('cicla i quattro stati senza promozioni automatiche', () => {
  expect(nextStudyStatus()).toBe('in-apprendimento')
  expect(nextStudyStatus('in-apprendimento')).toBe('appreso')
  expect(nextStudyStatus('appreso')).toBe('ignorata')
  expect(nextStudyStatus('ignorata')).toBe('da-imparare')
})

it('cicla con 2 stati personalizzati posizionati fra i default', () => {
  const customStatuses: CustomStudyStatus[] = [
    { id: 'c1', nome: 'Da rileggere', colore: 'text-amber-500', icona: 'Bookmark' },
    { id: 'c2', nome: 'Difficile', colore: 'text-rose-500', icona: 'Flame' },
  ]
  const savedOrder = ['da-imparare', 'c1', 'in-apprendimento', 'c2', 'appreso', 'ignorata']
  const order = resolveStatusOrder(customStatuses, savedOrder)

  expect(order).toEqual(savedOrder)

  expect(nextStudyStatus('da-imparare', order)).toBe('c1')
  expect(nextStudyStatus('c1', order)).toBe('in-apprendimento')
  expect(nextStudyStatus('in-apprendimento', order)).toBe('c2')
  expect(nextStudyStatus('c2', order)).toBe('appreso')
  expect(nextStudyStatus('appreso', order)).toBe('ignorata')
  expect(nextStudyStatus('ignorata', order)).toBe('da-imparare')

  // Risoluzione etichette e icone
  const c1Def = resolveStudyStatus('c1', customStatuses)
  expect(c1Def.label).toBe('Da rileggere')
  expect(c1Def.isDefault).toBe(false)

  const c2Def = resolveStudyStatus('c2', customStatuses)
  expect(c2Def.label).toBe('Difficile')
  expect(c2Def.isDefault).toBe(false)
})

it('reintegra i default mancanti e posiziona nuovi custom in fondo', () => {
  const customStatuses: CustomStudyStatus[] = [
    { id: 'c1', nome: 'Stato 1', colore: 'text-blue-500', icona: 'Star' },
    { id: 'c2', nome: 'Stato 2', colore: 'text-emerald-500', icona: 'Flag' },
  ]
  // L'ordine salvato manca di 'ignorata' e di 'c2'
  const savedOrder = ['da-imparare', 'c1', 'in-apprendimento', 'appreso']
  const order = resolveStatusOrder(customStatuses, savedOrder)

  // 'ignorata' viene reintegrata e 'c2' aggiunto in coda
  expect(order).toContain('ignorata')
  expect(order).toContain('c2')
  expect(order.indexOf('c2')).toBe(order.length - 1)
})

it('mostra oggi, ieri e la data per i cambi precedenti, anche attraverso il cambio di mese', () => {
  const now = new Date(2026, 9, 1, 12)
  expect(studyDate(new Date(2026, 9, 1, 8).toISOString(), now)).toBe('oggi')
  expect(studyDate(new Date(2026, 8, 30, 23).toISOString(), now)).toBe('ieri')
  expect(studyDate(new Date(2026, 8, 28).toISOString(), now)).toBe('28 set')
  expect(studyDate(null, now)).toBe('')
})
