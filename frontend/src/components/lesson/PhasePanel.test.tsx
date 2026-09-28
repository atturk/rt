import { fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'

import { PhasePanel } from './PhasePanel'

const mutate = vi.fn()
vi.mock('@/api/jobs', () => ({ useOutline: () => ({ data: { macro_sections: [{ units: [{ id: '1.1', title: 'Uno' }, { id: '1.2', title: 'Due' }] }] } }) }))
vi.mock('@/api/hooks', () => ({
  isActiveJob: () => false,
  useLessonJobs: () => ({ data: [] }),
  useWorkers: () => ({ data: [{}] }),
  useRunJob: () => ({ mutate, isPending: false }),
  usePhases: () => ({ data: { phases: ['rewrite', 'review'].map((phase) => ({ phase, status: 'VALID', reason: '' })) } }),
}))

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
})
