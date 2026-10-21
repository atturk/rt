import { fireEvent, render, screen } from '@testing-library/react'
import { Check } from 'lucide-react'
import { describe, expect, it, vi } from 'vitest'

import { IconButton } from './icon-button'

describe('IconButton', () => {
  it('quando disabled è true, usa aria-disabled invece dell\'attributo disabled e blocca il clic', () => {
    const handleClick = vi.fn()
    render(<IconButton label="Azione" icon={Check} disabled onClick={handleClick} />)

    const btn = screen.getByRole('button', { name: 'Azione' })
    expect(btn).not.toHaveAttribute('disabled')
    expect(btn).toHaveAttribute('aria-disabled', 'true')

    fireEvent.click(btn)
    expect(handleClick).not.toHaveBeenCalled()
  })

  it('quando disabled è true in un form, Invio e Spazio non inviano il form', () => {
    const handleSubmit = vi.fn((e) => e.preventDefault())
    render(
      <form onSubmit={handleSubmit}>
        <IconButton label="Invia" icon={Check} type="submit" disabled />
      </form>,
    )

    const btn = screen.getByRole('button', { name: 'Invia' })
    fireEvent.keyDown(btn, { key: 'Enter', code: 'Enter' })
    fireEvent.keyDown(btn, { key: ' ', code: 'Space' })
    fireEvent.click(btn)
    expect(handleSubmit).not.toHaveBeenCalled()
  })

  it('mostra il motivo nel suggerimento se unavailable è specificato, e solo il nome se è solo disabled', () => {
    const { rerender } = render(<IconButton label="Documenti" icon={Check} disabled />)
    const btn = screen.getByRole('button', { name: 'Documenti' })
    expect(btn).toHaveAccessibleName('Documenti')
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveTextContent('Documenti')

    rerender(<IconButton label="Documenti" icon={Check} unavailable="nessun file" />)
    expect(btn).toHaveAccessibleName('Documenti')
    expect(btn).toHaveAccessibleDescription('Documenti: nessun file')
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveTextContent('Documenti: nessun file')
  })
})
