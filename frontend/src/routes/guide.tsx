import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { Search, X, BookOpen, ChevronRight } from 'lucide-react'

import { PageHeader } from '@/components/shell/PageHeader'
import { GuideMarkdown } from '@/components/guide/GuideMarkdown'
import { getGuidePage, getGuidePages, searchGuide, type GuidePage } from '@/lib/guideDocs'
import { useReturnAddress } from '@/lib/returnAddress'
import { cn } from '@/lib/utils'

export function GuidePage() {
  const { pagina } = useParams<{ pagina?: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const returnAddress = useReturnAddress()

  const [query, setQuery] = useState('')
  const [searchParams] = useSearchParams()
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (searchParams.get('cerca') === '1' && searchInputRef.current) {
      searchInputRef.current.focus()
    }
  }, [searchParams])

  // Pagina attiva (se non specificata, usa 'index')
  const activeSlug = pagina || 'index'
  const activePage: GuidePage = useMemo(() => {
    return getGuidePage(activeSlug) || getGuidePage('index')!
  }, [activeSlug])

  const allPages = useMemo(() => getGuidePages(), [])

  // Risultati di ricerca
  const searchResults = useMemo(() => {
    return query.trim() ? searchGuide(query) : []
  }, [query])

  // Gestione dello scorrimento verso l'ancora indicata nell'hash (#ancora)
  useEffect(() => {
    if (query) return
    const hash = location.hash.replace(/^#/, '')
    if (hash) {
      // Piccolo ritardo per assicurarsi che il DOM sia renderizzato
      const timer = setTimeout(() => {
        const el = document.getElementById(hash)
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      }, 50)
      return () => clearTimeout(timer)
    } else {
      window.scrollTo({ top: 0, behavior: 'instant' })
    }
  }, [location.pathname, location.hash, query])

  const backTarget =
    !returnAddress ||
    returnAddress === '/' ||
    returnAddress.startsWith('/guida') ||
    returnAddress.startsWith('/impostazioni')
      ? '/'
      : returnAddress

  return (
    <div className="flex min-h-dvh flex-col bg-background" data-testid="guide-page">
      <PageHeader
        title="Guida di RT"
        back={{ to: backTarget, label: 'Indietro' }}
      />

      {/* Barra di ricerca in cima */}
      <div className="sticky top-(--header-height) z-10 border-b bg-background/95 px-6 py-3 backdrop-blur-xs">
        <div className="mx-auto flex max-w-5xl items-center gap-2">
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              ref={searchInputRef}
              type="search"
              role="searchbox"
              aria-label="Cerca nella guida"
              placeholder="Cerca nella guida (minuscole, senza accenti)…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-md border border-input bg-card py-2 pl-9 pr-9 text-body text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label="Cancella ricerca"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-5xl flex-1 px-6 py-6 max-md:px-4">
        {/* Se c'è una ricerca attiva mostra i risultati, altrimenti la guida a 2 colonne */}
        {query.trim() ? (
          <div className="w-full" data-testid="guide-search-results">
            <p className="mb-4 text-meta text-muted-foreground">
              {searchResults.length === 0
                ? `Nessun risultato per «${query}».`
                : `${searchResults.length} risultat${searchResults.length === 1 ? 'o' : 'i'} per «${query}»:`}
            </p>

            <ul className="flex flex-col divide-y rounded-lg border bg-card">
              {searchResults.map((res, i) => {
                const targetUrl = `/guida/${res.pageSlug === 'index' ? '' : res.pageSlug}${
                  res.anchor ? `#${res.anchor}` : ''
                }`
                return (
                  <li key={i}>
                    <button
                      type="button"
                      onClick={() => {
                        setQuery('')
                        navigate(targetUrl)
                      }}
                      className="flex w-full flex-col p-4 text-left transition-colors hover:bg-muted/50 cursor-pointer"
                    >
                      <div className="flex items-center gap-2 text-sm font-semibold text-accent">
                        <span>{res.pageTitle}</span>
                        {res.sectionTitle !== res.pageTitle && (
                          <>
                            <ChevronRight className="size-3.5 text-muted-foreground" />
                            <span>{res.sectionTitle}</span>
                          </>
                        )}
                      </div>
                      <p className="mt-1 text-meta text-muted-foreground line-clamp-2">
                        {res.snippet}
                      </p>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : (
          <div className="flex w-full gap-8">
            {/* Indice argomenti laterale (desktop) */}
            <aside
              aria-label="Argomenti della guida"
              className="hidden w-56 shrink-0 md:block"
            >
              <div className="sticky top-[calc(var(--header-height)+60px)] flex max-h-[calc(100vh-var(--header-height)-96px)] flex-col gap-1 overflow-y-auto text-meta">
                <div className="mb-2 flex items-center gap-2 font-semibold text-foreground">
                  <BookOpen className="size-4" />
                  <span>Argomenti</span>
                </div>
                <nav className="flex flex-col gap-0.5">
                  {allPages.map((p) => {
                    const to = p.slug === 'index' ? '/guida' : `/guida/${p.slug}`
                    const isSelected = p.slug === activeSlug
                    return (
                      <Link
                        key={p.slug}
                        to={to}
                        className={cn(
                          'rounded-md px-2.5 py-1.5 transition-colors',
                          isSelected
                            ? 'bg-accent/15 font-semibold text-accent'
                            : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                        )}
                      >
                        {p.title}
                      </Link>
                    )
                  })}
                </nav>
              </div>
            </aside>

            {/* Contenuto della pagina attiva */}
            <article className="min-w-0 flex-1" data-testid="guide-article">
              {activePage ? (
                <GuideMarkdown markdown={activePage.raw} />
              ) : (
                <p className="text-muted-foreground">Pagina non trovata.</p>
              )}
            </article>
          </div>
        )}
      </div>
    </div>
  )
}
