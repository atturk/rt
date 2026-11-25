import { type ReactNode } from 'react'
import { Link } from 'react-router'
import { slugify } from '@/lib/guideDocs'
import { cn } from '@/lib/utils'

const imageModules = import.meta.glob('../../../../docs/guida/immagini/*', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

function renderInline(text: string): ReactNode[] {
  // Regex per catturare inline code, link, bold, italic
  const parts: ReactNode[] = []
  let remaining = text
  let key = 0

  while (remaining) {
    // Prova a fare match del primo costrutto inline
    // 1. Link [label](url)
    const linkMatch = remaining.match(/^\[([^\]]+)\]\(([^)]+)\)/)
    if (linkMatch) {
      const [full, label, url] = linkMatch
      if (url.startsWith('/') || url.startsWith('#')) {
        parts.push(
          <Link key={key++} to={url} className="text-accent underline hover:text-foreground">
            {renderInline(label)}
          </Link>,
        )
      } else {
        parts.push(
          <a
            key={key++}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline hover:text-foreground"
          >
            {renderInline(label)}
          </a>,
        )
      }
      remaining = remaining.slice(full.length)
      continue
    }

    // 2. Inline code `code`
    const codeMatch = remaining.match(/^`([^`]+)`/)
    if (codeMatch) {
      const [full, codeText] = codeMatch
      parts.push(
        <code key={key++} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]">
          {codeText}
        </code>,
      )
      remaining = remaining.slice(full.length)
      continue
    }

    // 3. Bold **bold**
    const boldMatch = remaining.match(/^\*\*([^*]+)\*\*/)
    if (boldMatch) {
      const [full, boldText] = boldMatch
      parts.push(<strong key={key++} className="font-semibold">{renderInline(boldText)}</strong>)
      remaining = remaining.slice(full.length)
      continue
    }

    // 4. Italic *italic*
    const italicMatch = remaining.match(/^\*([^*]+)\*/)
    if (italicMatch) {
      const [full, italicText] = italicMatch
      parts.push(<em key={key++} className="italic">{renderInline(italicText)}</em>)
      remaining = remaining.slice(full.length)
      continue
    }

    // Testo normale fino al prossimo carattere speciale [ ` *
    const nextSpecial = remaining.search(/[[`*]/)
    if (nextSpecial === -1) {
      parts.push(remaining)
      break
    } else if (nextSpecial === 0) {
      // Carattere speciale non corrispondente a un pattern valido, trattalo come testo
      parts.push(remaining[0])
      remaining = remaining.slice(1)
    } else {
      parts.push(remaining.slice(0, nextSpecial))
      remaining = remaining.slice(nextSpecial)
    }
  }

  return parts
}

interface GuideSectionBlock {
  title: string
  anchor: string
  body: ReactNode[]
}

/** Pagina della guida nello stile delle Impostazioni: titolo e introduzione in testa,
 * poi ogni sezione «##» come gruppo con etichetta sopra una card. */
export function GuideMarkdown({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/)
  const intro: ReactNode[] = []
  const sections: GuideSectionBlock[] = []
  let pageTitle: ReactNode = null
  // Dove finiscono i blocchi: introduzione o corpo della sezione corrente.
  let elements: ReactNode[] = intro

  let inCodeBlock = false
  let codeBlockLines: string[] = []
  let listType: 'ul' | 'ol' | null = null
  let listItems: string[] = []
  let blockquoteLines: string[] = []
  let key = 0

  const flushList = () => {
    if (!listType || listItems.length === 0) return
    const Tag = listType
    elements.push(
      <Tag key={key++} className={listType === 'ul' ? 'my-3 list-disc pl-5' : 'my-3 list-decimal pl-5'}>
        {listItems.map((item, i) => (
          <li key={i} className="my-1">
            {renderInline(item)}
          </li>
        ))}
      </Tag>,
    )
    listType = null
    listItems = []
  }

  const flushBlockquote = () => {
    if (blockquoteLines.length === 0) return
    const text = blockquoteLines.join('\n')
    const isNote = text.includes('[!NOTE]')
    const isTip = text.includes('[!TIP]')
    const isWarning = text.includes('[!WARNING]')
    const cleanText = text
      .replace(/^\[!(NOTE|TIP|WARNING)\]\s*/i, '')
      .trim()

    let toneClass = 'border-l-4 border-border bg-muted/30 text-foreground'
    if (isNote) toneClass = 'border-l-4 border-accent bg-accent/10 text-foreground'
    if (isTip) toneClass = 'border-l-4 border-emerald-500 bg-emerald-500/10 text-foreground'
    if (isWarning) toneClass = 'border-l-4 border-amber-500 bg-amber-500/10 text-foreground'

    elements.push(
      <blockquote key={key++} className={`my-4 rounded-r-md p-3 ${toneClass}`}>
        <p className="m-0 leading-relaxed">{renderInline(cleanText)}</p>
      </blockquote>,
    )
    blockquoteLines = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    // Fenced code block
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        elements.push(
          <pre
            key={key++}
            className="my-4 overflow-x-auto rounded-lg border bg-muted/60 p-3 font-mono text-[13px] leading-relaxed"
          >
            <code>{codeBlockLines.join('\n')}</code>
          </pre>,
        )
        inCodeBlock = false
        codeBlockLines = []
      } else {
        flushList()
        flushBlockquote()
        inCodeBlock = true
      }
      continue
    }

    if (inCodeBlock) {
      codeBlockLines.push(line)
      continue
    }

    // Blockquote
    if (trimmed.startsWith('>')) {
      flushList()
      blockquoteLines.push(trimmed.slice(1).trim())
      continue
    } else if (blockquoteLines.length > 0) {
      flushBlockquote()
    }

    // Blank line
    if (!trimmed) {
      flushList()
      continue
    }

    // Image on a line of its own: ![alt](immagini/name.png)
    const imgMatch = trimmed.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
    if (imgMatch) {
      flushList()
      flushBlockquote()
      const altText = imgMatch[1]
      const rawPath = imgMatch[2].trim()
      const fileName = rawPath.replace(/^(\.\/)?immagini\//, '')
      const matchKey = Object.keys(imageModules).find(
        (k) => k.endsWith('/' + fileName) || k === fileName,
      )
      const url = matchKey ? imageModules[matchKey] : null
      if (url) {
        elements.push(
          <img
            key={key++}
            src={url}
            alt={altText}
            loading="lazy"
            className="my-4 max-w-full rounded border border-border/60"
          />,
        )
      } else {
        elements.push(
          <p key={key++} className="my-3 italic text-muted-foreground">
            {altText}
          </p>,
        )
      }
      continue
    }

    // Headings
    if (trimmed.startsWith('# ')) {
      flushList()
      pageTitle = renderInline(trimmed.slice(2).trim())
      continue
    }

    if (trimmed.startsWith('## ')) {
      flushList()
      const title = trimmed.slice(3).trim()
      const section: GuideSectionBlock = { title, anchor: slugify(title), body: [] }
      sections.push(section)
      elements = section.body
      continue
    }

    if (trimmed.startsWith('### ')) {
      flushList()
      const title = trimmed.slice(4).trim()
      elements.push(
        <h3 key={key++} className="mt-5 mb-2 text-body font-semibold text-foreground">
          {renderInline(title)}
        </h3>,
      )
      continue
    }

    // Unordered list
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      if (listType !== 'ul') {
        flushList()
        listType = 'ul'
      }
      listItems.push(trimmed.slice(2).trim())
      continue
    }

    // Ordered list
    const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/)
    if (olMatch) {
      if (listType !== 'ol') {
        flushList()
        listType = 'ol'
      }
      listItems.push(olMatch[2].trim())
      continue
    }

    // Regular paragraph
    flushList()
    elements.push(
      <p key={key++} className="my-3 leading-relaxed text-foreground">
        {renderInline(trimmed)}
      </p>,
    )
  }

  flushList()
  flushBlockquote()

  // Margini interni: niente spazio sopra il primo blocco e sotto l'ultimo di ogni card.
  const flow = '[&>*:first-child]:mt-0 [&>*:last-child]:mb-0'
  return (
    <div className="flex max-w-3xl flex-col gap-8 text-body leading-relaxed text-foreground">
      {(pageTitle || intro.length > 0) && (
        <header className="flex flex-col gap-1">
          {pageTitle && <h1 className="text-heading font-semibold tracking-tight">{pageTitle}</h1>}
          {intro.length > 0 && <div className={cn('text-muted-foreground [&_p]:text-muted-foreground', flow)}>{intro}</div>}
        </header>
      )}
      {sections.map((section, i) => {
        const headingId = `${section.anchor || 'sezione'}-titolo-${i}`
        return (
          <section
            key={i}
            id={section.anchor}
            aria-labelledby={headingId}
            className="flex min-w-0 scroll-mt-20 flex-col gap-2"
          >
            <h2 id={headingId} className="group flex items-center gap-2 px-1 text-body font-semibold text-foreground">
              <a href={`#${section.anchor}`} className="hover:underline">
                {renderInline(section.title)}
              </a>
              <a
                href={`#${section.anchor}`}
                className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                aria-label={`Link alla sezione ${section.title}`}
              >
                #
              </a>
            </h2>
            {section.body.length > 0 && (
              <div className={cn('min-w-0 rounded-lg border bg-card px-4 py-3', flow)}>{section.body}</div>
            )}
          </section>
        )
      })}
    </div>
  )
}
