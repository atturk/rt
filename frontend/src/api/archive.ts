import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'
import { formData } from './jobStatus'

export type Extraction = 'testo' | 'immagini' | 'solo_immagini'
export type SourceOptions = {
  pagine?: string | number[] | null
  estrai?: Extraction
  uso?: 'guida' | 'contesto' | 'integra'
}
export type ArchiveUsage = {
  lezione_id: number | null
  titolo: string
  data: string
  pagine: number[] | null
  materia: string
}
export type ArchiveLookup = {
  impronta: string
  pagine_totali: number | null
  usate: ArchiveUsage[]
  da_continuare: string | null
  estrai?: Extraction
}
export type InspectedFile = { pagine_totali: number | null; estrai: Extraction }
export const archiveApi = {
  lookup: (sha: string[]): Promise<Record<string, ArchiveLookup | null>> =>
    unwrap(api.POST('/api/v1/archive/lookup', { body: { sha } })),
  /** Pagine e modalità predefinita di un file nuovo (un PDF orizzontale sono slide). */
  inspect: (file: File): Promise<InspectedFile> =>
    unwrap(api.POST('/api/v1/archive/inspect', { body: { file: '' }, bodySerializer: () => formData({ file }) })),
}

export type FileFacts = { entry: ArchiveLookup | null; pagine_totali: number | null; estrai: Extraction | null }
const NO_FACTS: FileFacts = { entry: null, pagine_totali: null, estrai: null }

/** Cosa si sa di un file prima di caricarlo: dall'archivio se c'è, altrimenti (PDF e presentazioni) dal server. */
export async function fileFacts(file: File): Promise<FileFacts> {
  try {
    const sha = await fileSha(file)
    const entry = (await archiveApi.lookup([sha]))[sha]
    if (entry) return { entry, pagine_totali: entry.pagine_totali, estrai: entry.estrai ?? null }
  } catch {
    /* Il riconoscimento non impedisce l'aggiunta di un file nuovo. */
  }
  if (!/\.(pdf|pptx)$/i.test(file.name)) return NO_FACTS
  try {
    const inspected = await archiveApi.inspect(file)
    return { ...NO_FACTS, pagine_totali: inspected.pagine_totali, estrai: inspected.estrai }
  } catch {
    return NO_FACTS
  }
}

export async function fileSha(file: File): Promise<string> {
  const data =
    typeof file.arrayBuffer === 'function'
      ? await file.arrayBuffer()
      : await new Promise<ArrayBuffer>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as ArrayBuffer)
          reader.onerror = () => reject(reader.error)
          reader.readAsArrayBuffer(file)
        })
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, '0')).join('')
}

export function compressPages(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b)
  const runs: string[] = []
  for (let i = 0; i < sorted.length; i++) {
    const first = sorted[i]
    let last = first
    while (sorted[i + 1] === last + 1) last = sorted[++i]
    runs.push(first === last ? String(first) : `${first}–${last}`)
  }
  return runs.join(', ')
}
/** Word, TXT e Markdown si leggono solo come testo. */
export const textOnly = (name: string) => /\.(docx|txt|md)$/i.test(name)
/** Default prima di guardare il file; per i PDF lo decide l'orientamento (archiveApi.inspect). */
export const defaultExtraction = (name: string): Extraction => (textOnly(name) ? 'testo' : 'immagini')

export type ArchiveRow = {
  impronta: string
  nome: string
  tipo: string
  pagine_totali: number | null
  durata_s: number | null
  dimensione: number
  materie: string[]
  usi: number
  da_continuare: string | null
}
export type ArchivePage = { numero: number; ignorata: boolean; lezione_id: number | null }
export type ArchiveDetail = ArchiveRow & {
  pagine: ArchivePage[]
  lezioni: { id: number | null; titolo: string; data: string; pagine: number[] | null }[]
  trascrizione_inizio: string
}
export const archiveFilesApi = {
  list: (filters: { materia?: string; tipo?: string; q?: string }): Promise<ArchiveRow[]> =>
    unwrap(api.GET('/api/v1/archive', { params: { query: filters } })),
  detail: (sha: string): Promise<ArchiveDetail> =>
    unwrap(api.GET('/api/v1/archive/{sha}', { params: { path: { sha } } })),
  ignore: (sha: string, pagine: number[], ignorata: boolean) =>
    unwrap(
      api.PUT('/api/v1/archive/{sha}/ignored', { params: { path: { sha } }, body: { pagine, ignorata } }),
    ),
  deletePages: (sha: string, pagine: number[]) =>
    unwrap(api.POST('/api/v1/archive/{sha}/pages/delete', { params: { path: { sha } }, body: { pagine } })),
  crop: (sha: string, n: number, rect: [number, number, number, number], sostituisci: boolean) =>
    unwrap(
      api.POST('/api/v1/archive/{sha}/pages/{n}/crop', {
        params: { path: { sha, n } },
        body: { rect, sostituisci },
      }),
    ),
  delete: (sha: string) => unwrap(api.DELETE('/api/v1/archive/{sha}', { params: { path: { sha } } })),
  addToLesson: (
    sha: string,
    lesson_id: number,
    pagine: number[] | null,
    uso: NonNullable<SourceOptions['uso']>,
    estrai: Extraction,
  ) =>
    unwrap(
      api.POST('/api/v1/archive/{sha}/add-to-lesson', {
        params: { path: { sha } },
        body: { lesson_id, pagine, uso, estrai },
      }),
    ),
  addToMedia: (sha: string, lesson_id: number, pagine: number[]) =>
    unwrap(
      api.POST('/api/v1/archive/{sha}/add-to-media', {
        params: { path: { sha } },
        body: { lesson_id, pagine },
      }),
    ),
  summary: (materia?: string | null): Promise<ArchiveSummary> =>
    unwrap(api.GET('/api/v1/archive/summary', { params: { query: { materia: materia || undefined } } })),
}

export type ArchiveSummary = { file: number; da_continuare: number }

export function useArchiveSummary(materia?: string | null) {
  return useQuery({
    queryKey: ['archive', 'summary', materia ?? ''],
    queryFn: () => archiveFilesApi.summary(materia),
  })
}
