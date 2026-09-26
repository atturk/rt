import { act, fireEvent, render, screen } from '@testing-library/react'

import { isNearBottom, useFollowTail } from './followTail'

function Log({ lines }: { lines: number }) {
  const { ref, onScroll, following, jumpToLatest } = useFollowTail<HTMLDivElement>(lines)
  return (
    <>
      <div ref={ref} onScroll={onScroll} data-testid="log" data-following={following} />
      {!following && <button onClick={jumpToLatest}>Vai agli ultimi</button>}
    </>
  )
}

/** jsdom non fa layout: altezze e scroll si impostano a mano. */
function setBox(el: HTMLElement, box: { scrollHeight: number; clientHeight: number; scrollTop?: number }) {
  Object.defineProperty(el, 'scrollHeight', { configurable: true, value: box.scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: box.clientHeight })
  if (box.scrollTop != null) el.scrollTop = box.scrollTop
}

describe('isNearBottom', () => {
  it('considera "in fondo" entro la soglia', () => {
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 200, scrollTop: 790 })).toBe(true)
    expect(isNearBottom({ scrollHeight: 1000, clientHeight: 200, scrollTop: 700 })).toBe(false)
  })
})

describe('useFollowTail', () => {
  it('segue la coda, si ferma se si scorre in alto e riprende tornando in fondo', () => {
    const { rerender } = render(<Log lines={1} />)
    const log = screen.getByTestId('log')
    setBox(log, { scrollHeight: 500, clientHeight: 100 })
    rerender(<Log lines={2} />)
    expect(log.scrollTop).toBe(500) // nuova riga: scorre all'ultima

    setBox(log, { scrollHeight: 500, clientHeight: 100, scrollTop: 100 })
    fireEvent.scroll(log)
    expect(log.dataset.following).toBe('false')
    setBox(log, { scrollHeight: 800, clientHeight: 100 })
    rerender(<Log lines={3} />)
    expect(log.scrollTop).toBe(100) // l'utente sta leggendo: non si sposta

    act(() => screen.getByRole('button', { name: 'Vai agli ultimi' }).click())
    expect(log.scrollTop).toBe(800)
    expect(log.dataset.following).toBe('true')

    setBox(log, { scrollHeight: 800, clientHeight: 100, scrollTop: 300 })
    fireEvent.scroll(log)
    setBox(log, { scrollHeight: 800, clientHeight: 100, scrollTop: 700 })
    fireEvent.scroll(log) // tornato in fondo a mano
    expect(log.dataset.following).toBe('true')
  })
})
