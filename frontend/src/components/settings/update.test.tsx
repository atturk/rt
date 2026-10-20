import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { api, type Schemas } from '@/api/client'
import { UpdateSection } from './update'

const idle = { phase: 'idle', downloaded: 0, total: null, error: null, target: null }
const base: Schemas['AppUpdate'] = {
  supported: true,
  current: '4.2.5',
  latest: '4.3.0',
  available: true,
  channel: 'stable',
  prerelease: false,
  ready: false,
  asset_name: 'RT-4.3.0-windows-x64-setup.exe',
  asset_size: 300 * 1024 * 1024,
  notes_url: 'https://github.com/atturk/rt/releases/tag/v4.3.0',
  releases_url: 'https://github.com/atturk/rt/releases',
  error: null,
  progress: idle,
}

function result(data: unknown, status = 200) {
  return { data, response: new Response('{}', { status }) }
}

function renderUpdate(data: Schemas['AppUpdate']) {
  vi.spyOn(api, 'GET').mockImplementation((() => Promise.resolve(result(data))) as never)
  const post = vi.spyOn(api, 'POST').mockImplementation((() =>
    Promise.resolve(
      result(
        {
          ...data,
          progress: {
            ...idle,
            phase: 'downloading',
            downloaded: 150 * 1024 * 1024,
            total: 300 * 1024 * 1024,
            target: '4.3.0',
          },
        },
        202,
      ),
    )) as never)
  const put = vi.spyOn(api, 'PUT').mockImplementation((() =>
    Promise.resolve(
      result(
        {
          ...data,
          channel: 'beta',
        },
        200,
      ),
    )) as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <UpdateSection />
    </QueryClientProvider>,
  )
  return { post, put }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Aggiornamenti', () => {
  it("nell'app installata scarica la versione disponibile e propone installa se pronta", async () => {
    const { post } = renderUpdate(base)
    expect(await screen.findByText('4.3.0')).toBeVisible()
    const downloadBtn = screen.getByRole('button', { name: /Scarica/ })
    await userEvent.click(downloadBtn)
    expect(post).toHaveBeenCalledWith('/api/v1/system/update')
    expect(await screen.findByRole('status')).toHaveTextContent('Scarico RT 4.3.0 (50%)')
  })

  it('quando il file è pronto mostra Installa e riavvia', async () => {
    const { post } = renderUpdate({ ...base, ready: true, progress: { ...idle, phase: 'ready' } })
    expect(await screen.findByRole('button', { name: /Installa e riavvia/ })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: /Installa e riavvia/ }))
    expect(post).toHaveBeenCalledWith('/api/v1/system/update/install')
  })

  it('senza app installata non offre il pulsante', async () => {
    renderUpdate({ ...base, supported: false, available: false })
    expect(await screen.findByText(/Ultima versione/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /Scarica/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Pagina delle release' })).toHaveAttribute('href', base.releases_url)
  })

  it('aggiornato: nessun pulsante di download o installazione', async () => {
    renderUpdate({ ...base, latest: '4.2.5', available: false })
    expect(await screen.findByText('RT è aggiornato.')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Scarica/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Installa e riavvia/ })).not.toBeInTheDocument()
  })

  it('cambia canale con lo switch Beta', async () => {
    const { put } = renderUpdate(base)
    const betaSwitch = await screen.findByRole('switch', { name: /Beta/i })
    expect(betaSwitch).not.toBeChecked()
    await userEvent.click(betaSwitch)
    expect(put).toHaveBeenCalledWith('/api/v1/system/update/channel', { body: { channel: 'beta' } })
  })
})
