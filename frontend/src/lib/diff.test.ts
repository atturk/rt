import { wordDiff } from './diff'

it('segna parole tolte e aggiunte', () => {
  expect(wordDiff('il glicerolo libero', 'il glicerolo 3-fosfato')).toEqual([
    { type: 'same', text: 'il glicerolo ' },
    { type: 'removed', text: 'libero' },
    { type: 'added', text: '3-fosfato' },
  ])
})

it('testi uguali', () => {
  expect(wordDiff('a b', 'a b')).toEqual([{ type: 'same', text: 'a b' }])
})
