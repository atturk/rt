import { Archive } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  archiveApi,
  compressPages,
  fileFacts,
  type ArchiveLookup,
  type Extraction,
  type SourceOptions,
} from '@/api/archive'
import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { defaultOptions, sourceReasons, useSourceDefaults, type Uso } from '@/lib/sourceDefaults'
import { ExtractOptions, SourceFileIcon, UseOptions } from './SourceControls'

export { UseOptions } from './SourceControls'

export function AddSourceDialog({
  file,
  source,
  initial,
  hasSources,
  hasAudio = false,
  isGuide = false,
  onClose,
  onSubmit,
  submitLabel = 'Aggiungi',
}: {
  file?: File
  source?: { impronta: string; nome: string; pagine_totali?: number | null }
  initial?: SourceOptions
  hasSources: boolean
  /** Con una registrazione la guida è l'audio. */
  hasAudio?: boolean
  /** La fonte è la guida della lezione: deve restarlo finché non se ne sceglie un'altra. */
  isGuide?: boolean
  onClose: () => void
  onSubmit: (options: SourceOptions) => Promise<void> | void
  submitLabel?: string
}) {
  const name = file?.name ?? source?.nome ?? ''
  const [entry, setEntry] = useState<ArchiveLookup | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [defaults] = useSourceDefaults()
  const [estrai, setEstrai] = useState<Extraction>(initial?.estrai ?? defaultOptions(name, defaults).estrai ?? 'immagini')
  const [uso, setUso] = useState<Uso>(
    initial?.uso ?? (hasSources || hasAudio ? defaultOptions(name, defaults).uso ?? 'contesto' : 'guida'),
  )
  const reasons = sourceReasons({ name, options: { estrai }, hasAudio, isGuide })
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const hasPages = /\.(pdf|pptx|docx|txt)$/i.test(name)
  const [pageText, setPageText] = useState<string | null>(
    Array.isArray(initial?.pagine) ? compressPages(initial.pagine) : (initial?.pagine ?? null),
  )
  useEffect(() => {
    let current = true
    async function load() {
      let result: ArchiveLookup | null = null
      let pages: number | null = null
      if (source) {
        result = (await archiveApi.lookup([source.impronta]))[source.impronta]
        pages = result?.pagine_totali ?? null
        if (current && result?.estrai && !initial?.estrai) setEstrai(defaultOptions(name, defaults, result.estrai).estrai ?? 'immagini')
      } else if (file) {
        const facts = await fileFacts(file)
        pages = facts.pagine_totali
        result = facts.entry
        if (current && facts.estrai && !initial?.estrai) setEstrai(defaultOptions(name, defaults, facts.estrai).estrai ?? 'immagini')
      }
      if (!current) return
      setEntry(result)
      if (!initial?.pagine) {
        const range = result?.da_continuare?.split('–')
        setFrom(range?.[0] ?? '1')
        setTo(range?.[1] ?? String(pages ?? source?.pagine_totali ?? ''))
      }
    }
    void load().catch(() => {
      /* Il riconoscimento non impedisce l'aggiunta di un file nuovo. */
    })
    return () => {
      current = false
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- i default contano solo all'apertura
  }, [file, source, initial?.pagine])
  const used = entry?.usate.flatMap((u) => u.pagine ?? []) ?? []
  async function submit() {
    setBusy(true)
    setProblem(null)
    try {
      const pagine = pageText || (from && to ? `${from}-${to}` : null)
      if (hasPages && ((from && Number(from) < 1) || (to && Number(to) < Number(from))))
        throw new Error('Pagine fuori intervallo')
      await onSubmit({ pagine: hasPages ? pagine : null, estrai, uso: estrai === 'solo_immagini' ? 'contesto' : uso })
    } catch (error) {
      setProblem(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open title="Aggiungi fonte" onClose={onClose}>
      <div className="mt-4 flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <SourceFileIcon name={name} className="size-4" />
          <span className="truncate">{name}</span>
        </div>
        {entry && (
          <span className="flex items-center gap-1 text-meta text-muted-foreground">
            <Archive className="size-3" />
            Già nell'archivio
          </span>
        )}
        {hasPages && (
          <div>
            <span className="text-meta">Pagine</span>
            {pageText ? (
              <button
                className="ml-2 text-meta"
                onClick={() => {
                  setPageText(null)
                  setFrom('1')
                  setTo(String(entry?.pagine_totali ?? ''))
                }}
              >
                {pageText}
              </button>
            ) : (
              <div className="mt-1 flex gap-2">
                <label>
                  Da
                  <input
                    aria-label="Da"
                    type="number"
                    min="1"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                    className="ml-2 w-20 rounded border p-1"
                  />
                </label>
                <label>
                  A
                  <input
                    aria-label="A"
                    type="number"
                    min={from || '1'}
                    max={entry?.pagine_totali ?? undefined}
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                    className="ml-2 w-20 rounded border p-1"
                  />
                </label>
              </div>
            )}
            {used.length > 0 && (
              <span
                className="text-meta text-muted-foreground"
                title={entry?.usate.map((u) => `${u.data}: ${compressPages(u.pagine ?? [])}`).join(' · ')}
              >
                {compressPages(used)} già usate
              </span>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <ExtractOptions value={estrai} onChange={setEstrai} unavailable={reasons.extract} />
          <UseOptions value={uso} onChange={setUso} unavailable={reasons.use} off={reasons.off} />
        </div>
        {problem && <Alert tone="danger">{problem}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={busy}>
            {submitLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
