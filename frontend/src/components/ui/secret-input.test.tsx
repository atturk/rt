import { render, screen } from '@testing-library/react'

import { SecretInput } from './secret-input'

describe('SecretInput', () => {
  it('non è un campo password: niente suggerimenti del portachiavi né dei gestori di password', () => {
    render(<SecretInput id="stt-key" aria-label="Chiave" />)
    const input = screen.getByLabelText('Chiave')
    expect(input).toHaveAttribute('type', 'text')
    expect(input).toHaveAttribute('autocomplete', 'off')
    expect(input).toHaveAttribute('data-1p-ignore')
    expect(input).toHaveAttribute('data-lpignore', 'true')
    expect(input).toHaveAttribute('name', 'stt-key')
    expect(input).toHaveClass('secret-mask')
    expect(input.getAttribute('name')).not.toMatch(/password/i)
  })
})
