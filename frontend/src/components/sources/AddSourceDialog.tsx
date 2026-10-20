import { Archive, FileText, GitMerge, Image, Layers, Navigation, Type } from 'lucide-react'
import { useEffect, useState } from 'react'
import { archiveApi, compressPages, defaultExtraction, fileSha, type ArchiveLookup, type SourceOptions } from '@/api/archive'
import { errorMessage } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Modal } from '@/components/ui/modal'

export function UseOptions({ value, onChange }: { value: NonNullable<SourceOptions['uso']>; onChange: (value: NonNullable<SourceOptions['uso']>) => void }) {
  return <div className="flex items-center gap-1" aria-label="Uso">
    <IconButton icon={Navigation} label="Guida: fonte principale" active={value === 'guida'} onClick={() => onChange('guida')} />
    <IconButton icon={Layers} label="Contesto: arricchisce la fonte principale" active={value === 'contesto'} onClick={() => onChange('contesto')} />
    <IconButton icon={GitMerge} label="Integra: può aggiungere unità" active={value === 'integra'} onClick={() => onChange('integra')} />
    <span className="ml-2 text-meta text-muted-foreground">{{ guida: 'Guida', contesto: 'Contesto', integra: 'Integra' }[value]}</span>
  </div>
}

export function AddSourceDialog({ file, source, initial, hasSources, onClose, onSubmit, submitLabel = 'Aggiungi' }: {
  file?: File
  source?: { impronta: string; nome: string; pagine_totali?: number | null }
  initial?: SourceOptions
  hasSources: boolean
  onClose: () => void
  onSubmit: (options: SourceOptions) => Promise<void> | void
  submitLabel?: string
}) {
  const name = file?.name ?? source?.nome ?? ''
  const [entry, setEntry] = useState<ArchiveLookup | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [estrai, setEstrai] = useState(initial?.estrai ?? defaultExtraction(name))
  const [uso, setUso] = useState<NonNullable<SourceOptions['uso']>>(initial?.uso ?? (hasSources ? 'contesto' : 'guida'))
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const hasPages = /\.(pdf|pptx|docx|txt)$/i.test(name)
  const [pageText, setPageText] = useState<string | null>(Array.isArray(initial?.pagine) ? compressPages(initial.pagine) : initial?.pagine ?? null)
  useEffect(() => {
    let current = true
    async function load() {
      const sha = source?.impronta ?? (file ? await fileSha(file) : null)
      if (!sha) return
      const result = (await archiveApi.lookup([sha]))[sha]
      if (!current) return
      setEntry(result)
      if (!initial?.pagine) {
        const range = result?.da_continuare?.split('–')
        setFrom(range?.[0] ?? '1')
        setTo(range?.[1] ?? String(result?.pagine_totali ?? source?.pagine_totali ?? ''))
      }
    }
    void load().catch(() => { /* Il riconoscimento non impedisce l'aggiunta di un file nuovo. */ })
    return () => { current = false }
  }, [file, source, initial?.pagine])
  const used = entry?.usate.flatMap((u) => u.pagine ?? []) ?? []
  async function submit() {
    setBusy(true)
    setProblem(null)
    try {
      const pagine = pageText || (from && to ? `${from}-${to}` : null)
      if (hasPages && ((from && Number(from) < 1) || (to && Number(to) < Number(from)))) throw new Error('Pagine fuori intervallo')
      await onSubmit({ pagine: hasPages ? pagine : null, estrai, uso })
    } catch (error) { setProblem(errorMessage(error)) }
    finally { setBusy(false) }
  }
  return <Modal open title="Aggiungi fonte" onClose={onClose}>
    <div className="mt-4 flex flex-col gap-4">
      <div className="flex items-center gap-2"><FileText className="size-4" aria-hidden /><span className="truncate">{name}</span></div>
      {entry && <span className="flex items-center gap-1 text-meta text-muted-foreground"><Archive className="size-3" />Già nell'archivio</span>}
      {hasPages && <div><span className="text-meta">Pagine</span>
        {pageText ? <button className="ml-2 text-meta" onClick={() => { setPageText(null); setFrom('1'); setTo(String(entry?.pagine_totali ?? '')) }}>{pageText}</button> :
          <div className="mt-1 flex gap-2"><label>Da<input aria-label="Da" type="number" min="1" value={from} onChange={(e) => setFrom(e.target.value)} className="ml-2 w-20 rounded border p-1" /></label><label>A<input aria-label="A" type="number" min={from || '1'} max={entry?.pagine_totali ?? undefined} value={to} onChange={(e) => setTo(e.target.value)} className="ml-2 w-20 rounded border p-1" /></label></div>}
        {used.length > 0 && <span className="text-meta text-muted-foreground" title={entry?.usate.map((u) => `${u.data}: ${compressPages(u.pagine ?? [])}`).join(' · ')}>{compressPages(used)} già usate</span>}
      </div>}
      <div><span className="text-meta">Estrai</span><div className="flex gap-1">
        <IconButton icon={Type} label="Testo: niente immagini" active={estrai === 'testo'} onClick={() => setEstrai('testo')} />
        <IconButton icon={Image} label="Immagini: pagine e figure" active={estrai === 'immagini'} onClick={() => setEstrai('immagini')} />
      </div></div>
      <div><span className="text-meta">Uso</span><UseOptions value={uso} onChange={setUso} /></div>
      {problem && <Alert tone="danger">{problem}</Alert>}
      <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose} disabled={busy}>Annulla</Button><Button onClick={submit} disabled={busy}>{submitLabel}</Button></div>
    </div>
  </Modal>
}
