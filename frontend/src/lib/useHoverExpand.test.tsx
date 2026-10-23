import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useHoverExpand } from './useHoverExpand'

function TestComponent() {
  const { open, ref } = useHoverExpand<HTMLDivElement>()
  return (
    <div>
      <div ref={ref} data-testid="group" data-open={open}>
        <button data-testid="btn-inside">Inside</button>
      </div>
      <button data-testid="btn-outside">Outside</button>
    </div>
  )
}

describe('useHoverExpand', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('resta aperto a 2,9 s e si chiude a 3 s dopo l uscita del puntatore', () => {
    render(<TestComponent />)
    const group = screen.getByTestId('group')
    expect(group.dataset.open).toBe('false')

    // Entrata del puntatore: si apre
    fireEvent.pointerEnter(group)
    expect(group.dataset.open).toBe('true')

    // Uscita del puntatore: parte il timer di 3 s
    fireEvent.pointerLeave(group)
    expect(group.dataset.open).toBe('true')

    // A 2,9 s resta ancora aperto
    act(() => {
      vi.advanceTimersByTime(2900)
    })
    expect(group.dataset.open).toBe('true')

    // A 3,0 s si chiude
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(group.dataset.open).toBe('false')
  })

  it('rientro prima dei 3 s: annulla il timer e resta aperto', () => {
    render(<TestComponent />)
    const group = screen.getByTestId('group')

    fireEvent.pointerEnter(group)
    expect(group.dataset.open).toBe('true')

    fireEvent.pointerLeave(group)
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(group.dataset.open).toBe('true')

    // Rientro prima dei 3 s
    fireEvent.pointerEnter(group)

    // Dopo altri 3 s dall'uscita originaria (totale 5 s) è ancora aperto perché siamo rientrati
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(group.dataset.open).toBe('true')

    // Nuova uscita: attende 3 s e poi si chiude
    fireEvent.pointerLeave(group)
    act(() => {
      vi.advanceTimersByTime(2900)
    })
    expect(group.dataset.open).toBe('true')
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(group.dataset.open).toBe('false')
  })

  it('clic fuori dal gruppo: si chiude subito', () => {
    render(<TestComponent />)
    const group = screen.getByTestId('group')
    const outside = screen.getByTestId('btn-outside')

    act(() => {
      fireEvent.pointerEnter(group)
    })
    expect(group.dataset.open).toBe('true')

    // Clic fuori: si chiude immediatamente, senza aspettare i 3 s
    act(() => {
      fireEvent.pointerDown(outside)
    })
    expect(group.dataset.open).toBe('false')
  })

  it('Esc: si chiude subito', () => {
    render(<TestComponent />)
    const group = screen.getByTestId('group')

    act(() => {
      fireEvent.pointerEnter(group)
    })
    expect(group.dataset.open).toBe('true')

    // Pressione del tasto Escape
    act(() => {
      fireEvent.keyDown(window, { key: 'Escape' })
    })
    expect(group.dataset.open).toBe('false')
  })

  it('il focus da tastiera dentro il gruppo lo tiene aperto', () => {
    render(<TestComponent />)
    const group = screen.getByTestId('group')
    const inside = screen.getByTestId('btn-inside')
    const outside = screen.getByTestId('btn-outside')

    // Focus dentro il gruppo: si apre
    act(() => {
      fireEvent.focusIn(group)
      inside.focus()
    })
    expect(group.dataset.open).toBe('true')

    // Anche dopo 3 s di puntatore fuori, resta aperto finché ha il focus
    act(() => {
      vi.advanceTimersByTime(3500)
    })
    expect(group.dataset.open).toBe('true')

    // Quando il focus si sposta fuori, si chiude
    act(() => {
      fireEvent.focusOut(group, { relatedTarget: outside })
      outside.focus()
    })
    expect(group.dataset.open).toBe('false')
  })
})
