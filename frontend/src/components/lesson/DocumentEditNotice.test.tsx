import { fireEvent, render, screen, within } from '@testing-library/react'
import { vi } from 'vitest'

import { DocumentEditNotice } from './DocumentEditNotice'

describe('DocumentEditNotice', () => {
  it('ogni avviso ha il suo "Non mostrare più" e la conferma passa solo quelli spuntati', () => {
    const onConfirm = vi.fn()
    const { container } = render(<DocumentEditNotice notices={['preview_edit_issues', 'preview_edit_beta']} onConfirm={onConfirm} onCancel={() => {}} />)
    const beta = container.querySelector('[data-notice=preview_edit_beta]') as HTMLElement
    const issues = container.querySelector('[data-notice=preview_edit_issues]') as HTMLElement
    expect(issues).toHaveTextContent('orfana')
    expect(beta).toHaveTextContent('editor esterno')
    fireEvent.click(within(beta).getByLabelText('Non mostrare più'))
    fireEvent.click(screen.getByRole('button', { name: 'Modifica', hidden: true }))
    expect(onConfirm).toHaveBeenCalledWith(['preview_edit_beta'])
  })
})
