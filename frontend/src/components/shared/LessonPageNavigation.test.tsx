import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { LessonPageNavigation } from './LessonPageNavigation'

vi.mock('@/api/hooks', () => ({
  useLessons: () => ({ data: [] }),
}))

describe('LessonPageNavigation', () => {
  function renderNav(panel: string | null = null) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <LessonPageNavigation id={1} panel={panel} title={<h1>Titolo</h1>}>
            <div>Contenuto</div>
          </LessonPageNavigation>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('mostra le zone laterali solo da md con hover per evitare overflow orizzontale a finestra stretta', () => {
    renderNav(null)
    const leftZone = screen.getByTestId('lesson-jump-zone-left')
    const rightZone = screen.getByTestId('lesson-jump-zone-right')

    expect(leftZone.className).toContain('md:[@media(hover:hover)]:block')
    expect(leftZone.className).not.toContain(' [@media(hover:hover)]:block')
    expect(rightZone.className).toContain('md:[@media(hover:hover)]:block')
  })

  it('mostra le zone laterali da xl con hover quando un pannello laterale è aperto', () => {
    renderNav('verifica')
    const leftZone = screen.getByTestId('lesson-jump-zone-left')
    const rightZone = screen.getByTestId('lesson-jump-zone-right')

    expect(leftZone.className).toContain('xl:[@media(hover:hover)]:block')
    expect(rightZone.className).toContain('xl:[@media(hover:hover)]:block')
  })
})
