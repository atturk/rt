import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { subjectsKeys } from '@/api/subjects'
import { AddEventPopup } from './CalendarPopups'

vi.mock('@/api/hooks', () => ({ useLessons: () => ({ data: [] }) }))

function popup() {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  client.setQueryData(subjectsKeys.all, [
    { nome: 'Biologia', lezioni: 0, docenti: ['Rossi'] },
    { nome: 'Chimica', lezioni: 0, docenti: ['Verdi'] },
  ])
  const onAdd = vi.fn(), onClose = vi.fn()
  render(<QueryClientProvider client={client}><AddEventPopup scope="week" weekNumber="43" anchor={{ x: 10, y: 10, width: 10, height: 10 }} onAdd={onAdd} onClose={onClose} /></QueryClientProvider>)
  return { onAdd, onClose }
}
it('propone i docenti della materia e Invio conferma dal campo Fine', async () => {
  const { onAdd, onClose } = popup()
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'biologia' } })
  const list = document.getElementById(screen.getByLabelText('Docente').getAttribute('list')!)!
  expect(within(list).getAllByRole('option', { hidden: true }).map(el => el.getAttribute('value'))).toEqual(['Rossi'])
  fireEvent.change(screen.getByLabelText('Materia'), { target: { value: 'Chimica' } })
  expect(within(list).getAllByRole('option', { hidden: true }).map(el => el.getAttribute('value'))).toEqual(['Verdi'])
  await userEvent.type(screen.getByLabelText('Fine'), '{Enter}')
  expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ materia: 'Chimica' }))
  expect(onClose).toHaveBeenCalledOnce()
})
it('Invio con materia vuota non salva', async () => {
  const { onAdd, onClose } = popup()
  await userEvent.type(screen.getByLabelText('Fine'), '{Enter}')
  expect(onAdd).not.toHaveBeenCalled()
  expect(onClose).not.toHaveBeenCalled()
})
