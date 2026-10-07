import { Archive } from 'lucide-react'
import { fireEvent, render, screen } from '@testing-library/react'
import { LinkMenuButton } from './menu'

it('il menu export mescola link, caselle e azioni con la stessa tastiera', () => {
  const toggle = vi.fn()
  const download = vi.fn()
  render(<LinkMenuButton label="Esporta" icon={Archive} side="top" items={[
    { label: 'Markdown', href: '/download' },
    { label: 'Includi lo stato di studio', checked: true, onSelect: toggle },
    { label: 'Scarica zip', onSelect: download },
  ]} />)
  const button = screen.getByRole('button', { name: 'Esporta' })
  fireEvent.click(button)
  const link = screen.getByRole('menuitem', { name: 'Markdown' })
  expect(link).toHaveFocus()
  fireEvent.keyDown(link, { key: 'ArrowDown' })
  const check = screen.getByRole('menuitemcheckbox', { name: 'Includi lo stato di studio' })
  expect(check).toHaveFocus()
  fireEvent.click(check)
  expect(toggle).toHaveBeenCalledOnce()
  expect(screen.getByRole('menu')).toBeInTheDocument()
  fireEvent.keyDown(check, { key: 'ArrowDown' })
  expect(screen.getByRole('menuitem', { name: 'Scarica zip' })).toHaveFocus()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Scarica zip' }))
  expect(download).toHaveBeenCalledOnce()
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})
