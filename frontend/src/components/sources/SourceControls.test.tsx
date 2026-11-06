import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ReliabilityOptions, SourceBadges } from './SourceControls'

describe('ReliabilityOptions', () => {
  it('mostra le tre opzioni e chiama onChange al clic', () => {
    const onChange = vi.fn()
    render(<ReliabilityOptions value="normale" onChange={onChange} />)

    const altaBtn = screen.getByRole('button', { name: 'Alta' })
    const normaleBtn = screen.getByRole('button', { name: 'Normale' })
    const bassaBtn = screen.getByRole('button', { name: 'Bassa' })

    expect(normaleBtn).toHaveAttribute('aria-pressed', 'true')
    expect(altaBtn).toHaveAttribute('aria-pressed', 'false')
    expect(bassaBtn).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(altaBtn)
    expect(onChange).toHaveBeenCalledWith('alta')

    fireEvent.click(bassaBtn)
    expect(onChange).toHaveBeenCalledWith('bassa')
  })
})

describe('SourceBadges', () => {
  it('mostra lo scudo per alta e bassa e niente per normale', () => {
    const { rerender } = render(<SourceBadges options={{ affidabilita: 'alta' }} />)
    expect(screen.getByTestId('badge-reliability-alta')).toBeInTheDocument()
    expect(screen.getByTitle('Affidabilità alta')).toBeInTheDocument()

    rerender(<SourceBadges options={{ affidabilita: 'bassa' }} />)
    expect(screen.getByTestId('badge-reliability-bassa')).toBeInTheDocument()
    expect(screen.getByTitle('Affidabilità bassa')).toBeInTheDocument()

    rerender(<SourceBadges options={{ affidabilita: 'normale' }} />)
    expect(screen.queryByTestId('badge-reliability-alta')).not.toBeInTheDocument()
    expect(screen.queryByTestId('badge-reliability-bassa')).not.toBeInTheDocument()
  })
})
