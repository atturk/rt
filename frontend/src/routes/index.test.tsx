import { describe, expect, it } from 'vitest'
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router'
import { render, screen } from '@testing-library/react'

import { areas } from './index'

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname + loc.search}</div>
}

function testRedirect(initialEntry: string, expectedLocation: string) {
  const router = createMemoryRouter(
    [
      {
        path: '/',
        children: [
          { index: true, element: <LocationProbe /> },
          { path: 'lezioni', element: <LocationProbe /> },
          { path: 'lezioni/:lessonId', element: <LocationProbe /> },
          ...areas.flatMap((a) => a.routes).filter((r) => !r.index && r.path !== 'lezioni/:lessonId'),
        ],
      },
    ],
    { initialEntries: [initialEntry] },
  )

  const { unmount } = render(<RouterProvider router={router} />)
  expect(screen.getByTestId('location')).toHaveTextContent(expectedLocation)
  unmount()
}

describe('A5: redirect delle pagine tolte', () => {
  it('redirect /recall -> /', () => {
    testRedirect('/recall', '/')
  })

  it('redirect /recall/materie -> /', () => {
    testRedirect('/recall/materie', '/')
  })

  it('redirect /recall/materie/:materia -> /?materia=:materia', () => {
    testRedirect('/recall/materie/Biochimica', '/?materia=Biochimica')
  })

  it('redirect /recall/giorno/:day -> /', () => {
    testRedirect('/recall/giorno/2026-10-01', '/')
  })

  it('redirect /review -> /', () => {
    testRedirect('/review', '/')
  })

  it('redirect /lezioni/:lessonId/revisione -> /lezioni/:lessonId?panel=verifica', () => {
    testRedirect('/lezioni/12/revisione', '/lezioni/12?panel=verifica')
  })

  it('redirect /lezioni/:lessonId/rilevanza -> /lezioni/:lessonId?panel=classificatore', () => {
    testRedirect('/lezioni/12/rilevanza', '/lezioni/12?panel=classificatore')
  })

  it('redirect /lezioni/:lessonId/relevance -> /lezioni/:lessonId?panel=classificatore', () => {
    testRedirect('/lezioni/12/relevance', '/lezioni/12?panel=classificatore')
  })

  it('redirect /lezioni/:lessonId/outline -> /lezioni/:lessonId', () => {
    testRedirect('/lezioni/12/outline', '/lezioni/12')
  })

  it('redirect /arricchimento -> /', () => {
    testRedirect('/arricchimento', '/')
  })

  it('redirect /immagini -> /', () => {
    testRedirect('/immagini', '/')
  })

  it('redirect /lezioni/:lessonId/arricchimento -> /lezioni/:lessonId?panel=arricchimento', () => {
    testRedirect('/lezioni/12/arricchimento', '/lezioni/12?panel=arricchimento')
  })

  it('redirect /lezioni/:lessonId/immagini -> /lezioni/:lessonId?panel=arricchimento', () => {
    testRedirect('/lezioni/12/immagini', '/lezioni/12?panel=arricchimento')
  })

  it('redirect /importa -> /', () => {
    testRedirect('/importa', '/')
  })

  it('redirect /lezioni/:lessonId/recall/domande -> /lezioni/:lessonId?panel=domande', () => {
    testRedirect('/lezioni/12/recall/domande', '/lezioni/12?panel=domande')
  })

  it('redirect /lezioni -> /', () => {
    testRedirect('/lezioni', '/')
  })
})
