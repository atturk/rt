import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { UnitStrip } from './UnitStrip'

it('mostra tacche piene, vuote e a righe, conteggio e classificatore aggiornato', () => {
  const onSelect = vi.fn(), onClassifier = vi.fn()
  render(<UnitStrip target="revisore" units={[
    { unit_id: '1.1', title: 'Uno', included: true }, { unit_id: '1.2', title: 'Due', included: false },
    { unit_id: '1.3', title: 'Tre', included: true, unclassified: true },
  ]} rule="Regola" onSelect={onSelect} classifierEnabled classifierUpdated onClassifier={onClassifier} />)
  const strip = screen.getByTestId('unit-strip-ticks')
  expect(strip.querySelectorAll('[data-state=included]')).toHaveLength(1)
  expect(strip.querySelectorAll('[data-state=excluded]')).toHaveLength(1)
  expect(strip.querySelector('[data-state=unclassified]')).toHaveClass('rt-unit-strip-unclassified')
  expect(screen.getByTestId('unit-strip-count')).toHaveTextContent('2/3')
  expect(screen.getByTestId('classifier-dot')).toHaveClass('bg-success')
  fireEvent.click(strip)
  expect(onSelect).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: 'Rivedi le etichette · classificatore aggiornato' }))
  expect(onClassifier).toHaveBeenCalledOnce()
})
it('il puntino è giallo da aggiornare e il classificatore spento non ha icona', () => {
  const props = { target: 'recaller' as const, units: [], rule: 'Scelta personalizzata', onSelect: vi.fn(), classifierUpdated: false }
  const view = render(<UnitStrip {...props} classifierEnabled />)
  expect(screen.getByTestId('classifier-dot')).toHaveClass('bg-warning')
  view.rerender(<UnitStrip {...props} classifierEnabled={false} />)
  expect(screen.queryByTestId('classifier-dot')).not.toBeInTheDocument()
})
