import { act, fireEvent, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { mountDomTooltip } from './dom-tooltip'

it('i widget DOM usano il suggerimento e il ritardo condivisi di RT', async () => {
  const button = document.createElement('button')
  button.textContent = 'Icona'
  document.body.append(button)
  let dispose!: () => void
  await act(async () => { dispose = mountDomTooltip(button, 'Riduci sezione') })
  expect(button).not.toHaveAttribute('title')
  fireEvent.mouseEnter(button)
  expect(await screen.findByRole('tooltip', { name: 'Riduci sezione' })).toBeVisible()
  await act(async () => { dispose(); button.remove() })
  expect(screen.queryByRole('tooltip', { name: 'Riduci sezione' })).not.toBeInTheDocument()
})
