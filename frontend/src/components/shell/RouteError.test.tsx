import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { RouteError } from './RouteError'

vi.mock('@/lib/clientLog', () => ({ reportClientLog: vi.fn() }))

function Broken(): never {
  throw new Error('unità mancante')
}

describe('RouteError', () => {
  it('mostra un errore in italiano e lo manda nel registro', async () => {
    const { reportClientLog } = await import('@/lib/clientLog')
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const router = createMemoryRouter([{ path: '/', element: <Broken />, errorElement: <RouteError /> }])
    render(<RouterProvider router={router} />)
    expect(await screen.findByText('Questa pagina ha avuto un problema')).toBeInTheDocument()
    expect(screen.getByText('unità mancante')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ricarica la pagina' })).toBeInTheDocument()
    expect(reportClientLog).toHaveBeenCalledWith('error', 'Pagina andata in errore: unità mancante', expect.stringContaining('unità mancante'))
  })
})
