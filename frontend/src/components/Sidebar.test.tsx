import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { Sidebar } from './Sidebar'

function mount() {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={query}><MemoryRouter><Sidebar /></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })

it('ricorda una materia chiusa dopo il rimontaggio', async () => {
  vi.spyOn(api, 'GET').mockResolvedValue({ data: [{ id: 1, materia: 'BIOCHIMICA', data: '2026-01-01', titolo: 'Lipidi', phases: {}, pending_issues: 0 }], error: undefined, response: new Response('[]') } as never)
  const first = mount()
  const details = (await screen.findByText('BIOCHIMICA')).closest('details')!
  expect(details.open).toBe(true)
  details.open = false
  fireEvent(details, new Event('toggle'))
  expect(details.open).toBe(false)
  first.unmount()
  mount()
  expect((await screen.findByText('BIOCHIMICA')).closest('details')!.open).toBe(false)
})
