import { render, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MathText } from './MathText'

describe('MathText', () => {
  it('rende le formule fra delimitatori e lascia il resto come testo', async () => {
    const { container } = render(<MathText text={'Come determina $Q_1 Q_2$ il verso di $\\underline{i}_{r12}$?'} />)
    await waitFor(() => expect(container.querySelectorAll('math')).toHaveLength(2))
    expect(container.textContent).toContain('Come determina')
  })

  it('senza formule resta testo', () => {
    const { container } = render(<MathText text="Costa 5$ e 10$" />)
    expect(container.querySelector('math')).toBeNull()
    expect(container.textContent).toBe('Costa 5$ e 10$')
  })

  it('aggiorna quando cambia il testo', async () => {
    const { container, rerender } = render(<MathText text="$a$" />)
    await waitFor(() => expect(container.querySelector('math')).not.toBeNull())
    rerender(<MathText text="solo testo" />)
    expect(container.textContent).toBe('solo testo')
  })
})
