import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { WelcomeBox } from './WelcomeBox'

function renderComponent(props: Partial<React.ComponentProps<typeof WelcomeBox>> = {}) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const defaultProps = {
    onNewLesson: vi.fn(),
    onSampleImported: vi.fn(),
    onDismiss: vi.fn(),
    ...props,
  }
  const result = render(
    <QueryClientProvider client={client}>
      <WelcomeBox {...defaultProps} />
    </QueryClientProvider>,
  )
  return { ...result, props: defaultProps }
}

describe('WelcomeBox', () => {
  it('mostra il benvenuto, i pulsanti e la stima dei costi', async () => {
    vi.spyOn(api, 'GET').mockImplementation((path) => {
      if (path === '/api/v1/settings/estimate') {
        return Promise.resolve({
          data: { eur: 0.05, formatted: 'circa 0,05 € a lezione (stima)' },
          response: new Response(null, { status: 200 }),
        } as never)
      }
      return Promise.reject(new Error('unhandled'))
    })

    const { props } = renderComponent()
    expect(screen.getByRole('heading', { name: 'Benvenuto in RT' })).toBeInTheDocument()
    expect(screen.getByTestId('welcome-import-sample')).toBeInTheDocument()
    expect(screen.getByTestId('welcome-create-lesson')).toBeInTheDocument()
    expect(screen.getByTestId('welcome-dismiss')).toBeInTheDocument()

    expect(await screen.findByTestId('welcome-estimate')).toHaveTextContent('circa 0,05 € a lezione (stima)')

    fireEvent.click(screen.getByTestId('welcome-create-lesson'))
    expect(props.onNewLesson).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByTestId('welcome-dismiss'))
    expect(props.onDismiss).toHaveBeenCalledTimes(1)
  })

  it('importa la lezione di esempio con successo', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { eur: null, formatted: 'stima non disponibile' },
      response: new Response(null, { status: 200 }),
    } as never)
    const postSpy = vi.spyOn(api, 'POST').mockImplementation((path) => {
      if (path === '/api/v1/lessons/sample') {
        return Promise.resolve({
          data: { lesson_id: 1, materia: 'ESEMPIO', titolo: 'Introduzione a RT' },
          response: new Response(null, { status: 201 }),
        } as never)
      }
      return Promise.reject(new Error('unhandled'))
    })

    const { props } = renderComponent()
    fireEvent.click(screen.getByTestId('welcome-import-sample'))

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith('/api/v1/lessons/sample')
      expect(props.onSampleImported).toHaveBeenCalledTimes(1)
    })
  })

  it('mostra errore se l importazione fallisce', async () => {
    vi.spyOn(api, 'GET').mockResolvedValue({
      data: { eur: null, formatted: 'stima non disponibile' },
      response: new Response(null, { status: 200 }),
    } as never)
    vi.spyOn(api, 'POST').mockImplementation((path) => {
      if (path === '/api/v1/lessons/sample') {
        return Promise.resolve({
          error: { error: { code: 'sample_error', message: 'Impossibile importare' } },
          response: new Response(null, { status: 500 }),
        } as never)
      }
      return Promise.reject(new Error('unhandled'))
    })

    renderComponent()
    fireEvent.click(screen.getByTestId('welcome-import-sample'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Impossibile importare')
  })
})
