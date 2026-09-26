import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { SubjectIcon } from './SubjectIcon'
import { SubjectRail } from './SubjectRail'
import { subjectIcons } from '@/lib/subjectIcon'

const LESSONS = [
  { id: 1, materia: 'ANATOMIA PATOLOGICA', data: '2026-09-20', titolo: 'Neoplasie', folder_name: 'a', argomenti: '', phases: {}, pending_issues: 2 },
  { id: 2, materia: 'ANATOMIA PATOLOGICA', data: '2026-09-10', titolo: 'Infiammazione', folder_name: 'b', argomenti: '', phases: {}, pending_issues: 0 },
  { id: 3, materia: 'BIOCHIMICA', data: '2026-09-05', titolo: 'Lipidi', folder_name: 'c', argomenti: '', phases: {}, pending_issues: 0 },
]

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function renderRail() {
  vi.spyOn(api, 'GET').mockResolvedValue({ data: LESSONS, error: undefined, response: new Response('[]') } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <SubjectRail />
        <button type="button">fuori</button>
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SubjectIcon', () => {
  it('mostra le iniziali con la disposizione e il colore della materia', () => {
    const icon = subjectIcons(['Patologia generale 1']).get('PATOLOGIA GENERALE 1')!
    render(<SubjectIcon icon={icon} />)
    const el = screen.getByTestId('subject-icon')
    expect(el).toHaveAttribute('data-layout', 'triangle')
    expect(el).toHaveAttribute('aria-hidden')
    expect(el.textContent).toBe('PG1')
    expect(el.style.backgroundColor).not.toBe('')
  })
})

describe('SubjectRail', () => {
  it('una icona per materia con nome completo e tooltip al focus', async () => {
    renderRail()
    const user = userEvent.setup()
    const anatomy = await screen.findByRole('button', { name: /ANATOMIA PATOLOGICA: 2 lezioni/ })
    expect(screen.getByRole('button', { name: /BIOCHIMICA: 1 lezione/ })).toBeInTheDocument()
    await user.tab()
    expect(anatomy).toHaveFocus()
    expect(screen.getByRole('tooltip')).toHaveTextContent('ANATOMIA PATOLOGICA')
    expect(screen.getByRole('tooltip')).toBeVisible()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('frecce fra le materie, Invio apre il pannello, Esc lo chiude', async () => {
    renderRail()
    const user = userEvent.setup()
    const anatomy = await screen.findByRole('button', { name: /ANATOMIA PATOLOGICA/ })
    const biochem = screen.getByRole('button', { name: /BIOCHIMICA/ })
    anatomy.focus()
    await user.keyboard('{ArrowDown}')
    expect(biochem).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(anatomy).toHaveFocus()

    await user.keyboard('{Enter}')
    const panel = screen.getByRole('dialog', { name: 'ANATOMIA PATOLOGICA' })
    expect(anatomy).toHaveAttribute('aria-expanded', 'true')
    const links = within(panel).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual([
      expect.stringContaining('Neoplasie'),
      expect.stringContaining('Infiammazione'),
    ])
    expect(links[0]).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(anatomy).toHaveFocus()
  })

  it('un clic su una lezione naviga e chiude il pannello; un clic fuori lo chiude', async () => {
    renderRail()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /BIOCHIMICA/ }))
    await user.click(screen.getByRole('button', { name: 'fuori' }))
    expect(screen.queryByRole('dialog')).toBeNull()

    await user.click(screen.getByRole('button', { name: /ANATOMIA PATOLOGICA/ }))
    await user.click(within(screen.getByRole('dialog')).getByRole('link', { name: /Infiammazione/ }))
    expect(screen.getByTestId('where')).toHaveTextContent('/lezioni/2')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: /ANATOMIA PATOLOGICA: 2 lezioni, lezione aperta/ })).toBeInTheDocument()
  })
})
