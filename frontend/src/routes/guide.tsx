import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  BookOpen,
  Calendar,
  ChevronRight,
  Download,
  FileArchive,
  FileText,
  GraduationCap,
  KeyRound,
  LifeBuoy,
  Lock,
  Mic,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Smartphone,
  X,
  type LucideIcon,
} from 'lucide-react'

import { PageBody, PageHeader } from '@/components/shell/PageHeader'
import { GuideMarkdown } from '@/components/guide/GuideMarkdown'
import { getGuidePage, getGuidePages, searchGuide, type GuidePage } from '@/lib/guideDocs'
import { useIsPhone } from '@/lib/phone'
import { useGuideReturnAddress } from '@/lib/returnAddress'
import { cn } from '@/lib/utils'

/** Icona di ogni argomento nella barra laterale, come le sezioni delle Impostazioni. */
const PAGE_ICONS: Record<string, LucideIcon> = {
  index: BookOpen,
  installazione: Download,
  'chiavi-e-costi': KeyRound,
  'nuova-lezione': Mic,
  fonti: FileText,
  verifica: ShieldCheck,
  studio: GraduationCap,
  ripasso: RotateCcw,
  calendario: Calendar,
  'file-di-rt': FileArchive,
  'iphone-e-agenti': Smartphone,
  'backup-e-aggiornamenti': RefreshCw,
  problemi: LifeBuoy,
  privacy: Lock,
}

export function GuidePage() {
  const { pagina } = useParams<{ pagina?: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const phone = useIsPhone()
  // Indietro riporta alla pagina da cui si è entrati nella guida (Impostazioni comprese).
  const backTarget = useGuideReturnAddress()

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

  const searchBox = (
    <div className="relative">
      <Search
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <input
        ref={searchInputRef}
        type="search"
        role="searchbox"
        aria-label="Cerca nella guida"
        placeholder="Cerca nella guida…"
        title="Minuscole e accenti non contano"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full rounded-lg border border-input bg-card py-2 pl-9 pr-9 text-body text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-search-cancel-button]:hidden"
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
  )

  return (
    <div className="flex min-h-dvh flex-col bg-background" data-testid="guide-page">
      <PageHeader title="Guida di RT" back={{ to: backTarget, label: 'Indietro' }} />
      <PageBody className="md:px-5">
        <div className="flex min-w-0 gap-8">
          {/* Argomenti a sinistra, come le sezioni delle Impostazioni */}
          {!phone && (
            <aside
              aria-label="Argomenti della guida"
              className="sticky top-20 flex h-fit max-h-[calc(100vh-6rem)] w-64 shrink-0 flex-col gap-3 overflow-y-auto"
            >
              {searchBox}
              <nav aria-label="Argomenti" className="flex flex-col gap-0.5">
                {allPages.map((p) => {
                  const Icon = PAGE_ICONS[p.slug] ?? FileText
                  const selected = !query.trim() && p.slug === activeSlug
                  return (
                    <NavLink
                      key={p.slug}
                      to={p.slug === 'index' ? '/guida' : `/guida/${p.slug}`}
                      end
                      onClick={() => setQuery('')}
                      aria-current={selected ? 'page' : undefined}
                      className={cn(
                        'flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-body transition-colors',
                        selected
                          ? 'bg-muted font-medium text-foreground'
                          : 'text-foreground/80 hover:bg-muted/60 hover:text-foreground',
                      )}
                    >
                      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="min-w-0">{p.title}</span>
                    </NavLink>
                  )
                })}
              </nav>
            </aside>
          )}

          <div className="flex min-w-0 flex-1 flex-col gap-6">
            {phone && (
              <div className="flex flex-col gap-3">
                {searchBox}
                <select
                  aria-label="Argomento della guida"
                  value={activeSlug}
                  onChange={(e) => {
                    setQuery('')
                    navigate(e.target.value === 'index' ? '/guida' : `/guida/${e.target.value}`)
                  }}
                  className="w-full rounded-lg border border-input bg-card px-3 py-2 text-body text-foreground"
                >
                  {allPages.map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.title}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {query.trim() ? (
              <section className="flex max-w-3xl flex-col gap-2" data-testid="guide-search-results">
                <p className="px-1 text-meta font-medium text-muted-foreground">
                  {searchResults.length === 0
                    ? `Nessun risultato per «${query}».`
                    : `${searchResults.length} risultat${searchResults.length === 1 ? 'o' : 'i'} per «${query}»`}
                </p>
                {searchResults.length > 0 && (
                  <ul className="min-w-0 divide-y divide-border/60 rounded-lg border bg-card">
                    {searchResults.map((res, i) => {
                      const targetUrl = `/guida/${res.pageSlug === 'index' ? '' : res.pageSlug}${
                        res.anchor ? `#${res.anchor}` : ''
                      }`
                      const Icon = PAGE_ICONS[res.pageSlug] ?? FileText
                      return (
                        <li key={i}>
                          <button
                            type="button"
                            onClick={() => {
                              setQuery('')
                              navigate(targetUrl)
                            }}
                            className="flex w-full cursor-pointer items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40"
                          >
                            <Icon className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden />
                            <span className="flex min-w-0 flex-col gap-0.5">
                              <span className="flex flex-wrap items-center gap-1.5 text-body font-medium text-foreground">
                                <span>{res.pageTitle}</span>
                                {res.sectionTitle !== res.pageTitle && (
                                  <>
                                    <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden />
                                    <span>{res.sectionTitle}</span>
                                  </>
                                )}
                              </span>
                              <span className="line-clamp-2 text-meta text-muted-foreground">{res.snippet}</span>
                            </span>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            ) : (
              <article className="min-w-0" data-testid="guide-article">
                {activePage ? (
                  <GuideMarkdown markdown={activePage.raw} />
                ) : (
                  <p className="text-muted-foreground">Pagina non trovata.</p>
                )}
              </article>
            )}
          </div>
        </div>
      </PageBody>
    </div>
  )
}
