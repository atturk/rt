import { fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'

import { UnitSelector } from './UnitSelector'

const mutate = vi.fn()
let data = {
  custom: false,
  classifier: 'shadow',
  selected: 2,
  units: [
    { unit_id: '1.1', title: 'Introduzione al corso', category: 'organizational', score: 0.2, level: 0, confidence: 0.9, error: null, suggested: false, selected: false },
    { unit_id: '1.2', title: 'Infiammazione acuta', category: 'didactic', score: 1.8, level: 2, confidence: 0.8, error: null, suggested: true, selected: true },
    { unit_id: '1.3', title: 'Mediatori', category: null, score: null, level: null, confidence: null, error: null, suggested: true, selected: true },
  ],
}

vi.mock('@/api/recall', () => ({
  useRecallUnits: () => ({ isPending: false, isError: false, data }),
  useSelectRecallUnits: () => ({ mutate, isError: false }),
}))

beforeEach(() => mutate.mockReset())

describe('selettore delle unità del recall', () => {
  it('chiuso dice quante unità sono selezionate; aperto mostra score e livello', () => {
    render(<UnitSelector lessonId={1} />)
    expect(screen.getByTestId('unit-selector-count')).toHaveTextContent('2 di 3 selezionate · solo rilevanti')
    expect(screen.getByTestId('unit-selector')).not.toHaveAttribute('open')
    const row = document.querySelector<HTMLElement>('[data-unit-id="1.2"]')!
    expect(within(row).getByText('1,8')).toBeInTheDocument()
    expect(within(row).getByLabelText('livello 2')).toHaveTextContent('L2')
    expect(row.title).toContain('score 1,8')
    const excluded = document.querySelector<HTMLElement>('[data-unit-id="1.1"]')!
    expect(within(excluded).getByText('organizzativa')).toBeInTheDocument()
    expect(within(excluded).getByRole('checkbox')).not.toBeChecked()
  })

  it('una spunta salva la nuova selezione; Solo rilevanti torna a quella predefinita', () => {
    render(<UnitSelector lessonId={1} />)
    fireEvent.click(within(document.querySelector<HTMLElement>('[data-unit-id="1.1"]')!).getByRole('checkbox'))
    expect(mutate).toHaveBeenCalledWith(['1.1', '1.2', '1.3'])
    fireEvent.click(screen.getByRole('button', { name: 'Nessuna' }))
    expect(mutate).toHaveBeenLastCalledWith([])
    expect(screen.getByRole('button', { name: 'Solo rilevanti' })).toBeDisabled()
    data = { ...data, custom: true }
    render(<UnitSelector lessonId={1} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Solo rilevanti' })[1])
    expect(mutate).toHaveBeenLastCalledWith(null)
  })
})
