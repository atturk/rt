import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, createMemoryRouter, RouterProvider, useLocation, Outlet } from 'react-router'
import { vi } from 'vitest'

import userEvent from '@testing-library/user-event'
import { areas } from './index'
import { testSettings, enrichmentSettings } from '@/components/settings/testSettings'
import { SETTINGS_REDIRECTS, SETTINGS_SECTIONS } from '@/lib/settings'
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

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear() })

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


// Navigazione delle route vere, isolata dal layout autenticato dell'app.
function realSettings(path: string, phone = false) {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: phone && query.includes('max-width'), addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve({
    data: path === '/api/v1/settings' ? testSettings : path === '/api/v1/settings/enrichment' ? enrichmentSettings
      : path === '/api/v1/system/cache' ? { audio: { entries: 0, bytes: 0 }, waveform: { entries: 0, bytes: 0 }, total: { entries: 0, bytes: 0 } } : {},
    response: new Response('{}', { status: 200 }),
  })) as never)
  const settings = areas.flatMap(a => a.routes).filter(r => r.path === 'impostazioni' || Object.keys(SETTINGS_REDIRECTS).includes(r.path ?? ''))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function Location() { return <output data-testid="location">{useLocation().pathname}{useLocation().search}</output> }
  const router = createMemoryRouter([{ element: <><Location /><Outlet /></>, children: settings }], { initialEntries: [path] })
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
}
describe('Le sette sezioni', () => {
  it('desktop: elenco a sinistra, sezione selezionata e contenuto insieme', async () => {
    realSettings('/impostazioni/aspetto')
    const nav = await screen.findByRole('navigation', { name: 'Sezioni delle impostazioni' })
    expect(within(nav).getAllByRole('link')).toHaveLength(7)
    expect(within(nav).getByRole('link', { name: 'Aspetto e lettura' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByRole('radiogroup', { name: 'Tema' })).toBeVisible()
    await userEvent.click(within(nav).getByRole('link', { name: 'Lavorazione delle lezioni' }))
    expect(await screen.findByRole('region', { name: 'Trascrizione' })).toBeVisible()
    expect(screen.queryByRole('radiogroup', { name: 'Tema' })).toBeNull()
  })
  it('telefono: elenco, pagina della sezione e freccia indietro', async () => {
    realSettings('/impostazioni', true)
    const nav = await screen.findByRole('navigation', { name: 'Sezioni delle impostazioni' })
    expect(screen.queryByRole('radiogroup', { name: 'Tema' })).toBeNull()
    await userEvent.click(within(nav).getByRole('link', { name: /Aspetto e lettura/ }))
    expect(await screen.findByRole('radiogroup', { name: 'Tema' })).toBeVisible()
    expect(screen.queryByRole('navigation', { name: 'Sezioni delle impostazioni' })).toBeNull()
    await userEvent.click(screen.getByRole('link', { name: 'Impostazioni' }))
    expect(await screen.findByRole('navigation', { name: 'Sezioni delle impostazioni' })).toBeVisible()
  })
  it.each(Object.entries(SETTINGS_REDIRECTS))('il vecchio URL %s porta alla sezione %s e conserva i parametri', async (old, next) => {
    realSettings(`/impostazioni/${old}?fase=rewrite`)
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(`/impostazioni/${next}?fase=rewrite`))
    await screen.findByRole('navigation', { name: 'Sezioni delle impostazioni' })
  })
  it('/bot porta a Telegram', async () => {
    realSettings('/bot')
    await screen.findByRole('navigation', { name: 'Sezioni delle impostazioni' })
    expect(screen.getByTestId('location')).toHaveTextContent('/impostazioni/telegram')
  })
  it('tutte le destinazioni hanno una route', () => {
    const routes = areas.flatMap(a => a.routes).find(r => r.path === 'impostazioni')!.children!
    expect(SETTINGS_SECTIONS.every(s => routes.some(r => r.path === s.path))).toBe(true)
  })
})
