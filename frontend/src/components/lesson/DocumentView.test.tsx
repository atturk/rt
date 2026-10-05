import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { AudioProvider } from './audio'
import { DocumentView } from './DocumentView'

const doc = {
  final: false, pending: false,
  markdown: '',
  sections: [],
  html: '<h3 data-unit-id="1.1">Primo</h3><p>uno</p><h3 data-unit-id="1.2">Secondo</h3><p>due</p>',
}

describe('DocumentView', () => {
  it('il link "Vai all\'unità" (#unit-<id>) porta in vista e segna quell\'unità', () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/lezioni/1#unit-1.2']}>
          <AudioProvider><DocumentView document={doc} hasAudio={false} lessonId={1} /></AudioProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const marked = Array.from(container.querySelectorAll('.rt-claim-unit')).map((el) => el.textContent)
    expect(marked).toEqual(['Secondo', 'due'])
    expect(scroll).toHaveBeenCalledOnce()
  })
})
