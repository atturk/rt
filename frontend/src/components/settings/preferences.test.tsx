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
