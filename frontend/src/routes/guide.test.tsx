import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, createMemoryRouter, RouterProvider } from 'react-router'
import { GuidePage } from './guide'
import { searchGuide, getGuidePage, GUIDE_PAGE_ORDER } from '@/lib/guideDocs'
import { GuideMarkdown } from '@/components/guide/GuideMarkdown'
import { ReturnAddressContext } from '@/lib/returnAddress'
import { PageHeader } from '@/components/shell/PageHeader'
import { Layout } from '@/components/Layout'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/api/hooks', () => ({
  useMe: () => ({ isSuccess: true, data: { username: 'test' } }),
}))
vi.mock('@/api/liveUpdates', () => ({
  useLiveUpdates: () => {},
}))
vi.mock('@/components/settings/useAppUpdate', () => ({
  useUpdatePopup: () => {},
}))
vi.mock('@/components/jobs/useDesktopJobSignals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/jobs/useDesktopJobSignals')>()
  return {
    ...actual,
    useDesktopJobSignals: () => {},
  }
})
vi.mock('@/lib/useOpenedFiles', () => ({
  useOpenedFiles: () => ({ error: null, clearError: () => {} }),
}))
vi.mock('@/lib/uploadQueue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/uploadQueue')>()
  return {
    ...actual,
    useUploadGuard: () => {},
  }
})

describe('Guide offline documentation & search', () => {
  it('searchGuide trova contenuti senza distinzione tra maiuscole/minuscole e accenti', () => {
    // Ricerca senza accenti per parola accentata "affidabilità"
    const results = searchGuide('affidabilita')
    expect(results.length).toBeGreaterThan(0)
    expect(results.some((r) => r.pageSlug === 'fonti')).toBe(true)

    // Ricerca per "zen"
    const zenResults = searchGuide('zen')
    expect(zenResults.some((r) => r.pageSlug === 'studio')).toBe(true)
  })

  it('renderizza la rotta /guida con la pagina iniziale', () => {
    render(
      <MemoryRouter initialEntries={['/guida']}>
        <Routes>
          <Route path="/guida" element={<GuidePage />} />
          <Route path="/guida/:pagina" element={<GuidePage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getAllByRole('heading', { level: 1, name: /Guida di RT/ }).length).toBeGreaterThan(0)
    expect(screen.getByText(/Benvenuto nella guida di RT/)).toBeInTheDocument()
  })

  it('renderizza la rotta /guida/:pagina per una pagina specifica', () => {
    render(
      <MemoryRouter initialEntries={['/guida/installazione']}>
        <Routes>
          <Route path="/guida" element={<GuidePage />} />
          <Route path="/guida/:pagina" element={<GuidePage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { level: 1, name: /Installazione/ })).toBeInTheDocument()
    expect(screen.getByText(/xattr -dr com\.apple\.quarantine/)).toBeInTheDocument()
  })

  it('con parametro ?cerca=1 il campo di ricerca riceve il focus', () => {
    render(
      <MemoryRouter initialEntries={['/guida?cerca=1']}>
        <Routes>
          <Route path="/guida" element={<GuidePage />} />
          <Route path="/guida/:pagina" element={<GuidePage />} />
        </Routes>
      </MemoryRouter>,
    )

    const searchInput = screen.getByRole('searchbox', { name: 'Cerca nella guida' })
    expect(searchInput).toHaveFocus()
  })

  it('ricerca dalla barra e mostra i risultati con ancore', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/guida']}>
        <Routes>
          <Route path="/guida" element={<GuidePage />} />
          <Route path="/guida/:pagina" element={<GuidePage />} />
        </Routes>
      </MemoryRouter>,
    )

    const searchInput = screen.getByRole('searchbox', { name: 'Cerca nella guida' })
    await user.type(searchInput, 'smartscreen')

    expect(screen.getByTestId('guide-search-results')).toBeInTheDocument()
    expect(screen.getByText(/Installazione/)).toBeInTheDocument()

    // Cliccando sul pulsante di cancellazione torna all'articolo
    const clearBtn = screen.getByRole('button', { name: 'Cancella ricerca' })
    await user.click(clearBtn)
    expect(screen.getByTestId('guide-article')).toBeInTheDocument()
  })

  it('PageHeader non mostra più il pulsante Guida · F1', () => {
    render(
      <MemoryRouter>
        <PageHeader title="Lezioni" />
      </MemoryRouter>,
    )

    const helpLink = screen.queryByRole('link', { name: 'Guida · F1' })
    expect(helpLink).not.toBeInTheDocument()
  })

  it('premere F1 e Cmd+? apre /guida', async () => {
    const qc = new QueryClient()
    const router = createMemoryRouter(
      [
        {
          element: <Layout />,
          children: [
            { path: '/', element: <div>Home</div> },
            { path: '/guida', element: <div data-testid="guida-route">Pagina Guida</div> },
          ],
        },
      ],
      { initialEntries: ['/'] },
    )

    render(
      <QueryClientProvider client={qc}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )

    expect(screen.getByText('Home')).toBeInTheDocument()

    // Premi F1
    fireEvent.keyDown(window, { key: 'F1' })
    await waitFor(() => {
      expect(screen.getByTestId('guida-route')).toBeInTheDocument()
    })
  })

  it('tutti i file in indice.yml esistono come pagine della guida', () => {
    expect(GUIDE_PAGE_ORDER.length).toBeGreaterThan(0)
    for (const slug of GUIDE_PAGE_ORDER) {
      expect(getGuidePage(slug), `Il file ${slug}.md in indice.yml deve esistere`).toBeDefined()
    }
  })

  it('GuideMarkdown renderizza correttamente le immagini e gestisce quelle mancanti', () => {
    const markdown = [
      '# Test immagini',
      '![Immagine test](immagini/test-image.png)',
      '![Immagine mancante](immagini/inesistente.png)',
    ].join('\n')

    render(<GuideMarkdown markdown={markdown} />)

    const img = screen.getByRole('img', { name: 'Immagine test' })
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveClass('max-w-full')

    // Immagine mancante mostra testo alternativo in corsivo
    expect(screen.getByText('Immagine mancante')).toHaveClass('italic')
  })

  it('bottone Indietro torna alla pagina di provenienza e non alle pagine precedenti della guida', () => {
    // Senza pagina precedente (aperta direttamente), il link Indietro va a /
    render(
      <MemoryRouter initialEntries={['/guida']}>
        <Routes>
          <Route path="/guida" element={<GuidePage />} />
        </Routes>
      </MemoryRouter>,
    )

    const backBtn = screen.getByRole('link', { name: 'Indietro' })
    expect(backBtn).toHaveAttribute('href', '/')
  })

  it('Indietro con ReturnAddressContext torna alla lezione ed esce dalla guida', () => {
    render(
      <MemoryRouter initialEntries={['/guida']}>
        <ReturnAddressContext.Provider value="/lezioni/15">
          <Routes>
            <Route path="/guida" element={<GuidePage />} />
          </Routes>
        </ReturnAddressContext.Provider>
      </MemoryRouter>,
    )

    const backBtn = screen.getByRole('link', { name: 'Indietro' })
    expect(backBtn).toHaveAttribute('href', '/lezioni/15')
  })

  it('Indietro da Impostazioni va a / e non a impostazioni', () => {
    render(
      <MemoryRouter initialEntries={['/guida']}>
        <ReturnAddressContext.Provider value="/impostazioni/aspetto">
          <Routes>
            <Route path="/guida" element={<GuidePage />} />
          </Routes>
        </ReturnAddressContext.Provider>
      </MemoryRouter>,
    )

    const backBtn = screen.getByRole('link', { name: 'Indietro' })
    expect(backBtn).toHaveAttribute('href', '/')
  })
})
