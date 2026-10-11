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

it('il portale esce dal contenitore e il clic su una voce resta interno al menu', () => {
  const select = vi.fn()
  const { container } = render(<div style={{ overflow: 'hidden' }}><LinkMenuButton label="Azioni" icon={Archive} items={[
    { label: 'Opzione', checked: false, onSelect: select },
  ]} /></div>)
  fireEvent.click(screen.getByRole('button', { name: 'Azioni' }))
  expect(container).not.toContainElement(screen.getByRole('menu'))
  const item = screen.getByRole('menuitemcheckbox')
  fireEvent.pointerDown(item)
  fireEvent.click(item)
  expect(select).toHaveBeenCalledOnce()
  expect(screen.getByRole('menu')).toBeVisible()
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
})

it('le scelte radio nel portale conservano frecce, Home, End ed Esc', async () => {
  const { MenuButton } = await import('./menu')
  const select = vi.fn()
  render(<MenuButton label="Ordina" icon={Archive} sections={[{ label: 'Ordine', items: [
    { label: 'Data', checked: false, onSelect: select },
    { label: 'Titolo', checked: true, onSelect: select },
  ] }]} />)
  const trigger = screen.getByRole('button', { name: 'Ordina' })
  fireEvent.click(trigger)
  expect(screen.getByRole('menuitemradio', { name: 'Titolo' })).toHaveFocus()
  fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' })
  expect(screen.getByRole('menuitemradio', { name: 'Data' })).toHaveFocus()
  fireEvent.keyDown(document.activeElement!, { key: 'End' })
  expect(screen.getByRole('menuitemradio', { name: 'Titolo' })).toHaveFocus()
  fireEvent.keyDown(document.activeElement!, { key: 'Home' })
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})
