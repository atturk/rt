/**
 * Gestione offline dei file di documentazione in docs/guida/*.md.
 * I file vengono inclusi a build time da Vite senza alcuna richiesta di rete.
 */

export interface GuideSection {
  id: string
  title: string
  content: string
}

export interface GuidePage {
  slug: string
  title: string
  raw: string
  sections: GuideSection[]
}

export interface GuideSearchResult {
  pageSlug: string
  pageTitle: string
  sectionTitle: string
  anchor: string
  snippet: string
}

export function slugify(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

export function normalizeSearchText(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

// Inclusione a build time di tutti i file markdown della guida e dell'indice
import rawIndex from '../../../docs/guida/indice.yml?raw'

const rawFiles = import.meta.glob('../../../docs/guida/*.md', {
  query: '?raw',
  eager: true,
}) as Record<string, string | { default: string }>

export function parseGuideIndex(yamlText: string): string[] {
  const files: string[] = []
  for (const line of yamlText.split(/\r?\n/)) {
    const match = line.match(/^\s*-\s*file:\s*([a-zA-Z0-9_-]+)/)
    if (match) {
      files.push(match[1])
    }
  }
  return files
}

export const GUIDE_PAGE_ORDER = parseGuideIndex(rawIndex)

function parseMarkdownDocument(slug: string, raw: string): GuidePage {
  const lines = raw.split(/\r?\n/)
  let title = slug
  const sections: GuideSection[] = []

  let currentSectionTitle = ''
  let currentSectionId = ''
  let currentSectionLines: string[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('# ') && title === slug) {
      title = trimmed.slice(2).trim()
      continue
    }

    if (trimmed.startsWith('## ')) {
      if (currentSectionTitle) {
        sections.push({
          id: currentSectionId,
          title: currentSectionTitle,
          content: currentSectionLines.join(' ').trim(),
        })
      }
      currentSectionTitle = trimmed.slice(3).trim()
      currentSectionId = slugify(currentSectionTitle)
      currentSectionLines = []
      continue
    }

    if (currentSectionTitle) {
      currentSectionLines.push(trimmed)
    }
  }

  if (currentSectionTitle) {
    sections.push({
      id: currentSectionId,
      title: currentSectionTitle,
      content: currentSectionLines.join(' ').trim(),
    })
  }

  return {
    slug,
    title,
    raw,
    sections,
  }
}

const parsedPages: Map<string, GuidePage> = new Map()

for (const [path, mod] of Object.entries(rawFiles)) {
  const match = path.match(/\/([^/]+)\.md$/)
  if (!match) continue
  const slug = match[1]
  const raw = typeof mod === 'string' ? mod : mod.default ?? ''
  parsedPages.set(slug, parseMarkdownDocument(slug, raw))
}

export function getGuidePages(): GuidePage[] {
  const ordered: GuidePage[] = []
  for (const slug of GUIDE_PAGE_ORDER) {
    const p = parsedPages.get(slug)
    if (p) ordered.push(p)
  }
  return ordered
}

export function getGuidePage(slug: string): GuidePage | undefined {
  return parsedPages.get(slug) || (slug === '' ? parsedPages.get('index') : undefined)
}

export function searchGuide(query: string): GuideSearchResult[] {
  const normalized = normalizeSearchText(query.trim())
  if (!normalized) return []

  const terms = normalized.split(/\s+/).filter(Boolean)
  const results: GuideSearchResult[] = []

  for (const page of getGuidePages()) {
    const pageTitleNorm = normalizeSearchText(page.title)

    // Se il titolo della pagina contiene tutti i termini
    if (terms.every((t) => pageTitleNorm.includes(t))) {
      results.push({
        pageSlug: page.slug,
        pageTitle: page.title,
        sectionTitle: page.title,
        anchor: '',
        snippet: page.sections[0]?.content.slice(0, 160) || page.title,
      })
    }

    // Controlla ogni sezione
    for (const sec of page.sections) {
      const secTitleNorm = normalizeSearchText(sec.title)
      const secContentNorm = normalizeSearchText(sec.content)
      const fullText = `${secTitleNorm} ${secContentNorm}`

      if (terms.every((t) => fullText.includes(t))) {
        // Evita duplicati identici se già aggiunto per il titolo pagina
        if (results.some((r) => r.pageSlug === page.slug && r.anchor === sec.id)) {
          continue
        }

        // Estrai uno snippet attorno al primo termine trovato nel contenuto
        let snippet = sec.content.slice(0, 160)
        const firstIdx = secContentNorm.indexOf(terms[0])
        if (firstIdx > 40) {
          snippet = `…${sec.content.slice(firstIdx - 30, firstIdx + 130)}…`
        }

        results.push({
          pageSlug: page.slug,
          pageTitle: page.title,
          sectionTitle: sec.title,
          anchor: sec.id,
          snippet: snippet || sec.title,
        })
      }
    }
  }

  return results
}
