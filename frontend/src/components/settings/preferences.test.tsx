import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { PREFERENCES_KEY } from '@/lib/preferences'
import { getZoom, resetZoom, setZoom } from '@/lib/zoom'
import { AppearanceSection } from './preferences'
import { testSettings } from './testSettings'

let client: QueryClient

beforeEach(() => {
  localStorage.clear()
  resetZoom()
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(PREFERENCES_KEY, {})
  vi.spyOn(api, 'GET').mockImplementation(() => Promise.resolve({ data: testSettings, response: new Response('{}', { status: 200 }) }) as never)
})

afterEach(() => {
  cleanup()
  client.clear()
  vi.restoreAllMocks()
  resetZoom()
  localStorage.clear()
})

it('cambiare la Select aggiorna lo zoom e il pulsante 100% lo azzera', async () => {
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )

  const menuButton = screen.getByRole('button', { name: 'Zoom' })
  expect(menuButton).toBeInTheDocument()
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('100%')

  // Scegli 125%
  await userEvent.click(menuButton)
  const option125 = screen.getByRole('menuitemradio', { name: '125%' })
  await userEvent.click(option125)

  expect(getZoom()).toBe(1.25)
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('125%')

  // Pulsante 100%
  const resetBtn = screen.getByRole('button', { name: '100%' })
  expect(resetBtn).not.toBeDisabled()
  await userEvent.click(resetBtn)

  expect(getZoom()).toBe(1)
  expect(resetBtn).toBeDisabled()
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('100%')
})

it('evento rt-zoom-change aggiorna il controllo', async () => {
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )

  act(() => {
    setZoom(1.5)
  })
  expect(screen.getByTestId('pref-zoom')).toHaveTextContent('150%')
})

it('Aspetto non ha più la sezione Studio né i colori dell’evidenziatore', () => {
  render(
    <QueryClientProvider client={client}>
      <AppearanceSection settings={testSettings} />
    </QueryClientProvider>,
  )
  expect(screen.queryByText('Studio')).not.toBeInTheDocument()
  expect(screen.queryByText(/Colori dell.evidenziatore/)).not.toBeInTheDocument()
  expect(screen.queryByText('Frecce per cambiare unità')).not.toBeInTheDocument()
})

it('Fonti: i default per tipo di file, con Solo immagini l’uso si spegne e la guida si sceglie nell’import', async () => {
  const { SourceDefaultsSection } = await import('./preferences')
  const stored: Record<string, unknown> = {}
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => Promise.resolve({ data: path === '/api/v1/preferences' ? stored : testSettings, response: new Response('{}') })) as never)
  vi.spyOn(api, 'PUT').mockImplementation(((_path: string, { params, body }: { params: { path: { name: string } }; body: unknown }) => {
    stored[params.path.name] = body
    return Promise.resolve({ data: body, response: new Response('{}') })
  }) as never)
  render(<QueryClientProvider client={client}><SourceDefaultsSection /></QueryClientProvider>)
  const { within } = await import('@testing-library/react')
  const slide = within(screen.getByTestId('source-default-slide'))
  expect(slide.getByRole('button', { name: 'Testo e immagini' })).toHaveAttribute('aria-pressed', 'true')
  expect(within(screen.getByTestId('source-default-testo')).getByRole('button', { name: 'Testo' })).toHaveAttribute('aria-pressed', 'true')
  expect(slide.getByRole('button', { name: 'Guida: fonte principale' })).toHaveAttribute('aria-disabled', 'true')
  await userEvent.click(slide.getByRole('button', { name: 'Solo immagini' }))
  expect(slide.getByRole('button', { name: 'Solo immagini' })).toHaveAttribute('aria-pressed', 'true')
  expect(slide.getByRole('button', { name: 'Integra: può aggiungere unità' })).toHaveAttribute('aria-disabled', 'true')
})
