import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'

import { PhasePanel } from './PhasePanel'

const mutate = vi.fn()
const validate = vi.fn()
const phases = vi.hoisted(() => ({ list: [] as Record<string, unknown>[] }))
vi.mock('@/api/jobs', () => ({ useOutline: () => ({ data: { macro_sections: [{ units: [{ id: '1.1', title: 'Uno' }, { id: '1.2', title: 'Due' }] }] } }) }))
vi.mock('@/api/hooks', () => ({
  isActiveJob: () => false,
  useLessonJobs: () => ({ data: [] }),
  useWorkers: () => ({ data: [{}] }),
  useRunJob: () => ({ mutate, isPending: false }),
  useValidatePhase: () => ({ mutate: validate, reset: vi.fn(), isPending: false, isError: false }),
  usePhases: () => ({ data: { phases: phases.list } }),
}))

beforeEach(() => {
  phases.list = ['rewrite', 'review'].map((phase) => ({ phase, status: 'VALID', reason: '' }))
  validate.mockReset()
})

const row = (phase: string) => document.querySelector(`[data-phase-row=${phase}]`) as HTMLElement

describe('PhasePanel', () => {
  it('le unità scelte per la riscrittura non passano alla revisione, che elenca solo la bozza', () => {
    render(<PhasePanel lessonId={1} units={[{ unit_id: '1.1', title: 'Uno' } as never]} />)
    fireEvent.click(within(row('rewrite')).getByLabelText('1.2 Due'))
    expect(within(row('review')).queryByLabelText('1.2 Due')).toBeNull()
    expect(within(row('review')).getByLabelText('1.1 Uno')).not.toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: /Esegui Revisione|Esegui review/i }))
    expect(mutate.mock.calls[0][0]).toMatchObject({ phase: 'review', units: undefined })
    fireEvent.click(within(row('rewrite')).getByRole('button', { name: /Esegui/ }))
    expect(mutate.mock.calls[1][0]).toMatchObject({ phase: 'rewrite', units: ['1.2'] })
  })

  it('con Option premuto "Esegui" diventa "Valida", solo per le fasi STALE o PARZIALI, e chiede conferma', () => {
    phases.list = [
      { phase: 'outline', status: 'STALE', reason: 'segments.json modificato' },
      { phase: 'rewrite', status: 'VALID', reason: '' },
      { phase: 'build', status: 'MISSING', reason: 'Artefatto build mancante',
        manual_validation: null },
    ]
    render(<PhasePanel lessonId={1} units={[]} />)
    expect(screen.queryByRole('button', { name: /^Valida/ })).toBeNull()
    act(() => { fireEvent.keyDown(window, { key: 'Alt' }) })
    expect(within(row('outline')).getByRole('button', { name: /^Valida/ })).toBeEnabled()
    expect(within(row('rewrite')).getByRole('button', { name: /^Valida/ })).toBeDisabled()
    expect(within(row('build')).getByRole('button', { name: /^Valida/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /^Esegui/ })).toBeNull()

    fireEvent.click(within(row('outline')).getByRole('button', { name: /^Valida/ }))
    expect(screen.getByText(/senza eseguirla di nuovo/)).toBeInTheDocument()
    expect(validate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Valida' }))
    expect(validate.mock.calls[0][0]).toBe('outline')

    act(() => { fireEvent.keyUp(window, { key: 'Alt' }) })
    expect(within(row('outline')).getByRole('button', { name: /^Esegui/ })).toBeInTheDocument()
  })

  it('dice quando una fase è stata validata a mano', () => {
    phases.list = [{ phase: 'rewrite', status: 'VALID', reason: 'ok',
      manual_validation: { at: '2026-09-29T10:00:00', previous_status: 'STALE' } }]
    render(<PhasePanel lessonId={1} units={[]} />)
    expect(screen.getByTestId('manual-validation-rewrite')).toHaveTextContent('Validata a mano')
    expect(screen.getByTestId('manual-validation-rewrite')).toHaveTextContent('era STALE')
  })
})
