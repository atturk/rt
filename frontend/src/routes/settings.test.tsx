import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { SETUP_PATH, SetupGate } from './settings'

function mockSettings(setupRequired: boolean) {
  vi.spyOn(api, 'GET').mockResolvedValue({
    data: { setup_required: setupRequired },
    error: undefined,
    response: new Response('{}', { status: 200 }),
  } as never)
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<SetupGate />}>
            <Route path="/" element={<p>Lezioni</p>} />
            <Route path="/impostazioni" element={<p>Impostazioni</p>} />
            <Route path={SETUP_PATH} element={<p>Configurazione guidata</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('SetupGate', () => {
  it('al primo avvio porta alla configurazione guidata', async () => {
    mockSettings(true)
    renderAt('/')
    expect(await screen.findByText('Configurazione guidata')).toBeInTheDocument()
  })
  it('lascia raggiungibili le impostazioni', async () => {
    mockSettings(true)
    renderAt('/impostazioni')
    expect(await screen.findByText('Impostazioni')).toBeInTheDocument()
  })
  it('a configurazione fatta non devia', async () => {
    mockSettings(false)
    renderAt('/')
    expect(await screen.findByText('Lezioni')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText('Configurazione guidata')).not.toBeInTheDocument()
  })
})
