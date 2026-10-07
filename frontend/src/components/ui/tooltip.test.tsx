import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { Tooltip } from './tooltip'

const tick = (ms: number) => act(() => vi.advanceTimersByTime(ms))
function triggers() {
  render(<>{['Uno', 'Due'].map(name => <Tooltip key={name} content={`Aiuto ${name}`}>
    {props => <button {...props}>{name}</button>}
  </Tooltip>)}</>)
  return [screen.getByRole('button', { name: 'Uno' }), screen.getByRole('button', { name: 'Due' })]
}
let now = Date.parse('2030-01-01')
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(now += 10000)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
})
afterEach(() => { cleanup(); tick(1000); vi.unstubAllGlobals(); vi.useRealTimers() })

it('aspetta 600 ms e annulla l’apertura se il mouse esce prima', () => {
  const [one] = triggers()
  fireEvent.mouseEnter(one); tick(599)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  tick(1)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Aiuto Uno')
  fireEvent.mouseLeave(one); tick(301)
  fireEvent.mouseEnter(one); tick(500); fireEvent.mouseLeave(one); tick(100)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
})
it('apre subito con un altro aperto o chiuso da meno di 300 ms', () => {
  const [one, two] = triggers()
  fireEvent.mouseEnter(one); tick(600); fireEvent.mouseEnter(two)
  expect(screen.getAllByRole('tooltip')).toHaveLength(1)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Aiuto Due')
  fireEvent.mouseLeave(two); tick(299); fireEvent.mouseEnter(one)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Aiuto Uno')
  fireEvent.mouseLeave(one); tick(300); fireEvent.mouseEnter(two)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  tick(600)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Aiuto Due')
})
it('pointerdown chiude e blocca il focus fino al nuovo hover', () => {
  const [one] = triggers()
  vi.spyOn(one, 'matches').mockReturnValue(true)
  fireEvent.mouseEnter(one); tick(600)
  fireEvent.pointerDown(one); fireEvent.focus(one); tick(1000)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  fireEvent.mouseLeave(one); fireEvent.mouseEnter(one); tick(600)
  expect(screen.getByRole('tooltip')).toBeVisible()
})
it('il focus deve essere visibile; blur ed Esc chiudono', () => {
  const [one] = triggers()
  const matches = vi.spyOn(one, 'matches').mockReturnValue(false)
  fireEvent.focus(one); tick(600)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  matches.mockReturnValue(true); fireEvent.focus(one)
  expect(matches).toHaveBeenCalledWith(':focus-visible')
  expect(screen.getByRole('tooltip')).toBeVisible()
  fireEvent.keyDown(one, { key: 'Escape' })
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  fireEvent.focus(one); fireEvent.blur(one)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
})
it('senza hover non si apre mai', () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
  const [one] = triggers()
  vi.spyOn(one, 'matches').mockReturnValue(true)
  fireEvent.mouseEnter(one); fireEvent.focus(one); tick(1000)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
})
