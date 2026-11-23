import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { vi } from 'vitest'

import { api } from '@/api/client'
import { HOLD_MS, SupportRailButton, shatterPieces } from './SupportRailButton'

function LocationDisplay() {
  return <output data-testid="location">{useLocation().pathname}</output>
}

function renderRailButton() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <nav>
          <SupportRailButton />
        </nav>
        <Routes>
          <Route path="*" element={<LocationDisplay />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function flushPromises() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })))
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('SupportRailButton', () => {
  it('non compare quando visible è false', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { visible: false, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderRailButton()
    await flushPromises()
    expect(screen.queryByTestId('support-rail-button')).toBeNull()
  })

  it('clic breve entro 350 ms invia POST opened, naviga a /impostazioni/supporta e sparisce', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { visible: true, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)
    const postSpy = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { visible: false, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderRailButton()
    await flushPromises()
    const button = screen.getByTestId('support-rail-button')

    fireEvent.pointerDown(button, { button: 0, pointerId: 1, pointerType: 'mouse' })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    fireEvent.pointerUp(button, { button: 0, pointerId: 1, pointerType: 'mouse' })
    await flushPromises()

    expect(postSpy).toHaveBeenCalledWith('/api/v1/system/support-prompt', { body: { event: 'opened' } })
    expect(screen.getByTestId('location')).toHaveTextContent('/impostazioni/supporta')
    expect(screen.queryByTestId('support-rail-button')).toBeNull()
  })

  it('pressione lunga di 900 ms invia POST hidden, nasconde il bottone e avvia la frammentazione', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { visible: true, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)
    const postSpy = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { visible: false, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderRailButton()
    await flushPromises()
    const button = screen.getByTestId('support-rail-button')

    fireEvent.pointerDown(button, { button: 0, pointerId: 1, pointerType: 'mouse' })
    act(() => {
      vi.advanceTimersByTime(HOLD_MS)
    })
    await flushPromises()

    expect(postSpy).toHaveBeenCalledWith('/api/v1/system/support-prompt', { body: { event: 'hidden' } })
    expect(screen.queryByTestId('support-rail-button')).toBeNull()
    expect(screen.getByTestId('support-shatter-overlay')).toBeInTheDocument()
  })

  it('rilascio a 500 ms annulla senza inviare nessuna POST', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { visible: true, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)
    const postSpy = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { visible: false, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderRailButton()
    await flushPromises()
    const button = screen.getByTestId('support-rail-button')

    fireEvent.pointerDown(button, { button: 0, pointerId: 1, pointerType: 'mouse' })
    act(() => {
      vi.advanceTimersByTime(500)
    })
    fireEvent.pointerUp(button, { button: 0, pointerId: 1, pointerType: 'mouse' })
    fireEvent.click(button) // il browser genera il click dopo il pointerup
    await flushPromises()

    expect(postSpy).not.toHaveBeenCalled()
    expect(screen.getByTestId('support-rail-button')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/')
  })

  it('tastiera: Invio apre, Spazio tenuto 900 ms nasconde e rilascio anticipato annulla', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { visible: true, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)
    const postSpy = vi.spyOn(api, 'POST').mockResolvedValue({
      data: { visible: false, url: 'https://ko-fi.com/example/donate' },
      error: undefined,
      response: new Response('{}', { status: 200 }),
    } as never)

    renderRailButton()
    await flushPromises()
    const button = screen.getByTestId('support-rail-button')

    fireEvent.keyDown(button, { key: ' ' })
    act(() => {
      vi.advanceTimersByTime(500)
    })
    fireEvent.keyUp(button, { key: ' ' })
    expect(postSpy).not.toHaveBeenCalled()

    fireEvent.keyDown(button, { key: 'Enter' })
    await flushPromises()
    expect(postSpy).toHaveBeenCalledWith('/api/v1/system/support-prompt', { body: { event: 'opened' } })
    expect(screen.getByTestId('location')).toHaveTextContent('/impostazioni/supporta')
  })

  it('shatterPieces(4, 0.28) genera 32 triangoli con vertici in [0, 1]', () => {
    const pieces = shatterPieces(4, 0.28)
    expect(pieces).toHaveLength(32)
    for (const piece of pieces) {
      expect(piece.vertices).toHaveLength(3)
      for (const v of piece.vertices) {
        expect(v.x).toBeGreaterThanOrEqual(0)
        expect(v.x).toBeLessThanOrEqual(1)
        expect(v.y).toBeGreaterThanOrEqual(0)
        expect(v.y).toBeLessThanOrEqual(1)
      }
      expect(piece.cx).toBeGreaterThanOrEqual(0)
      expect(piece.cx).toBeLessThanOrEqual(1)
      expect(piece.cy).toBeGreaterThanOrEqual(0)
      expect(piece.cy).toBeLessThanOrEqual(1)
    }
  })
})
